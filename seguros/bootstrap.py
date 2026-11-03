"""Preparación local e idempotente de Ollama; no modifica la instalación global."""

import errno
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .model import OllamaModel


VERSION = "0.40.13"
ARCHIVE_URL = f"https://github.com/ollama/ollama/releases/download/v{VERSION}/ollama-windows-amd64.zip"
ARCHIVE_SHA256 = "7afa38624fa62ee5d8293422d0ab084c1bb4603134c7f4dafce11a033b57cc19"
ARCHIVE_BYTES = 1_601_969_847
GIB = 1024 ** 3
DEFAULT_MODEL = "qwen2.5:7b"


class SetupError(RuntimeError):
    """Error recuperable de preparación, para mostrar sin traceback en la CLI."""


def _json(base_url, endpoint, data=None, timeout=10):
    request = Request(base_url + endpoint, headers={"Content-Type": "application/json"},
                      data=json.dumps(data).encode("utf-8") if data is not None else None)
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise SetupError("La respuesta de Ollama excede el tamaño permitido.")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise SetupError("El servidor local devolvió una respuesta inválida.")
    if result.get("error"):
        raise SetupError("Ollama: " + str(result["error"])[:600])
    return result


def _probe(base_url):
    try:
        result = _json(base_url, "/api/version", timeout=3)
        if not isinstance(result.get("version"), str):
            raise SetupError("Hay un servicio local, pero no identifica una versión de Ollama.")
        return result
    except HTTPError as exc:
        raise SetupError(f"El servicio local respondió HTTP {exc.code}; no iniciaré otro servidor.") from exc
    except (URLError, OSError) as exc:
        cause = exc.reason if isinstance(exc, URLError) else exc
        code = getattr(cause, "winerror", None) or getattr(cause, "errno", None)
        if isinstance(cause, PermissionError) or code in {errno.EACCES, errno.EPERM, 10013}:
            raise SetupError("Los permisos del entorno impiden conectar con Ollama. No significa que falte la instalación; habilita el acceso local.") from exc
        if isinstance(cause, ConnectionRefusedError) or code in {errno.ECONNREFUSED, 10061}:
            return None
        raise SetupError("No pude comprobar Ollama: la conexión local está bloqueada o no responde. No iniciaré un servidor duplicado.") from exc


def _pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # acceso denegado no prueba ausencia
        try:
            code = ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def _setup_lock(runtime, progress, timeout=900):
    runtime.mkdir(parents=True, exist_ok=True)
    path = runtime / "setup.lock"
    token = uuid.uuid4().hex
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump({"pid": os.getpid(), "token": token}, stream)
            break
        except FileExistsError:
            try:
                owner = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(owner, dict) and not _pid_alive(owner.get("pid")):
                    path.unlink(missing_ok=True)
                    continue
            except (OSError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise SetupError("Otra preparación mantiene .runtime/setup.lock. Espera a que termine; si se interrumpió, revisa ese archivo antes de reintentar.")
            if not announced:
                progress("Otra preparación está en curso; esperando su resultado…")
                announced = True
            time.sleep(1)
    try:
        yield
    finally:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("token") == token:
                path.unlink()
        except (OSError, ValueError, AttributeError):
            pass


def _space(path, needed):
    if shutil.disk_usage(path).free < needed:
        raise SetupError(f"No hay espacio suficiente en {path}: se necesitan al menos {needed / GIB:.1f} GiB libres para esta etapa.")


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_archive(runtime, progress):
    archive = runtime / f"ollama-windows-amd64-{VERSION}.zip"
    partial = archive.with_suffix(".zip.part")
    if archive.is_file():
        if _hash(archive) != ARCHIVE_SHA256:
            archive.unlink()
            raise SetupError("La descarga guardada no coincide con el SHA256 oficial; se descartó y no se ejecutó.")
        return archive
    _space(runtime, 6 * GIB)
    progress(f"Descargando Ollama portátil {VERSION} (aprox. 1.6 GB); sin instalación global…")
    partial.unlink(missing_ok=True)
    try:
        digest = hashlib.sha256()
        received = 0
        last_percent = -10
        deadline = time.monotonic() + 900
        with urlopen(Request(ARCHIVE_URL, headers={"User-Agent": "SegurosHorizonte-LocalSetup/1"}), timeout=60) as response:
            if urlparse(response.geturl()).scheme != "https":
                raise SetupError("La descarga oficial redirigió a una conexión no segura.")
            with partial.open("wb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > ARCHIVE_BYTES or time.monotonic() > deadline:
                        raise SetupError("La descarga excedió el tamaño o tiempo previsto.")
                    stream.write(chunk)
                    digest.update(chunk)
                    percent = int(received * 100 / ARCHIVE_BYTES)
                    if percent >= last_percent + 10:
                        progress(f"Ollama portátil: {percent}%")
                        last_percent = percent
        if received != ARCHIVE_BYTES or digest.hexdigest() != ARCHIVE_SHA256:
            raise SetupError("La descarga no coincide con el tamaño y SHA256 oficiales. No se ejecutó ningún archivo.")
        os.replace(partial, archive)
        return archive
    finally:
        partial.unlink(missing_ok=True)


def _safe_extract(archive, target):
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        unpacked_bytes = sum(item.file_size for item in entries)
        if unpacked_bytes > 8 * GIB:
            raise SetupError("La distribución comprimida excede el tamaño permitido.")
        _space(target, unpacked_bytes + GIB)
        for item in entries:
            name = item.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            mode = item.external_attr >> 16
            if (not parts or name.startswith("/") or ".." in parts or any(":" in p for p in parts)
                    or stat.S_ISLNK(mode) or not (target / name).resolve().is_relative_to(target.resolve())):
                raise SetupError("La distribución contiene una ruta o enlace inseguro; no se extrajo.")
        bundle.extractall(target)


def _install_runtime(runtime, progress):
    archive = _download_archive(runtime, progress)
    stage = Path(tempfile.mkdtemp(prefix="ollama-extract-", dir=runtime))
    destination = runtime / "ollama"
    try:
        progress("Verificación SHA256 correcta. Extrayendo la distribución portátil…")
        _safe_extract(archive, stage)
        if not (stage / "ollama.exe").is_file():
            raise SetupError("La distribución no incluye ollama.exe; no se iniciará.")
        if destination.exists():
            raise SetupError(".runtime/ollama existe pero está incompleto. Revísalo antes de volver a preparar.")
        os.replace(stage, destination)
        (runtime / "instalacion.json").write_text(json.dumps({
            "version": VERSION, "url": ARCHIVE_URL, "sha256": ARCHIVE_SHA256,
            "ejecutable": str(destination / "ollama.exe")}, indent=2), encoding="utf-8")
        archive.unlink()
        return destination / "ollama.exe"
    finally:
        # Únicamente temporales creados por esta función, dentro de .runtime.
        if stage.exists():
            resolved = stage.resolve()
            if resolved.parent != runtime.resolve() or not resolved.name.startswith("ollama-extract-"):
                raise SetupError("Ruta temporal inesperada; no se eliminará.")
            shutil.rmtree(resolved)


def _binary(runtime):
    portable = runtime / "ollama" / "ollama.exe"
    if portable.is_file():
        return portable.resolve()
    candidates = []
    detected = shutil.which("ollama")
    if detected:
        candidates.append(Path(detected))
    if sys.platform == "win32":
        local = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        candidates += [local / "Programs" / "Ollama" / "ollama.exe", local / "Ollama" / "ollama.exe",
                       Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
                       Path(os.getenv("ProgramFiles", "C:/Program Files")) / "Ollama" / "ollama.exe"]
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _start_server(binary, runtime, base_url):
    parsed = urlparse(base_url)
    if parsed.scheme != "http":
        raise SetupError("El inicio automático requiere una URL http local; HTTPS necesita un servidor configurado por ti.")
    bind_host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    child_env = os.environ.copy()
    child_env.update({"OLLAMA_HOST": f"{bind_host}:{parsed.port or 80}",
                      "OLLAMA_MODELS": str(runtime / "models"), "OLLAMA_NO_CLOUD": "1",
                      "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_CONTEXT_LENGTH": "8192",
                      "USERPROFILE": str(runtime / "ollama-home")})
    (runtime / "ollama-home").mkdir(parents=True, exist_ok=True)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    with (runtime / "server.stdout.log").open("ab") as stdout, (runtime / "server.stderr.log").open("ab") as stderr:
        process = subprocess.Popen([str(binary), "serve"], cwd=runtime, env=child_env,
                                   stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                   startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW)
    (runtime / "server.pid").write_text(str(process.pid), encoding="ascii")
    return process


def _wait_ready(base_url, process, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        version = _probe(base_url)
        if version:
            return version
        if process.poll() is not None:
            raise SetupError("Ollama terminó antes de estar disponible; revisa .runtime/server.stderr.log.")
        time.sleep(1)
    raise SetupError("Ollama no respondió en 90 segundos; revisa .runtime/server.stderr.log.")


def _normal_model(name):
    name = name.removeprefix("registry.ollama.ai/").removeprefix("library/")
    return name if ":" in name.rsplit("/", 1)[-1] else name + ":latest"


def _has_model(tags, model):
    entries = tags.get("models")
    if not isinstance(entries, list):
        raise SetupError("Ollama no devolvió una lista de modelos válida.")
    return any(isinstance(entry, dict) and _normal_model(str(entry.get("name", entry.get("model", "")))) == _normal_model(model)
               for entry in entries)


def _pull_model(base_url, model, progress):
    progress(f"Descargando el modelo {model}; qwen2.5:7b ocupa aproximadamente 4.7 GB…")
    request = Request(base_url + "/api/pull", data=json.dumps({"model": model, "stream": True}).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    success = False
    last = None
    deadline = time.monotonic() + 1800
    with urlopen(request, timeout=120) as response:
        while True:
            line = response.readline(100_001)
            if not line:
                break
            if len(line) > 100_000 or time.monotonic() > deadline:
                raise SetupError("La descarga del modelo excedió los límites previstos.")
            event = json.loads(line)
            if not isinstance(event, dict):
                raise SetupError("Ollama devolvió un progreso de descarga inválido.")
            if event.get("error"):
                raise SetupError("La descarga del modelo falló: " + str(event["error"])[:600])
            status = str(event.get("status", ""))
            completed, total = event.get("completed", 0), event.get("total", 0)
            percent = int(completed * 100 / total) if isinstance(total, int) and total > 0 and isinstance(completed, int) else None
            key = (status, (percent // 10) if percent is not None else None)
            if key != last:
                progress(f"Modelo: {status}" + (f" ({percent}%)" if percent is not None else ""))
                last = key
            success = status == "success" or success
    if not success:
        raise SetupError("La descarga del modelo terminó sin confirmar éxito; no se ejecutarán casos.")


def ensure_ollama(modelo=None, base_url=None, root=None, prepare=True, progress=print):
    """Asegura servidor y modelo; prepare=True además lo carga sin inferencias."""
    root = Path(root).resolve() if root else Path(__file__).resolve().parents[1]
    model = modelo or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model):
        raise SetupError("El nombre del modelo no es válido.")
    if model.endswith(("-cloud", ":cloud")):
        raise SetupError("Esta preparación es para modelos locales, no modelos cloud.")
    try:
        base = OllamaModel(modelo=model, base_url=base_url).base_url
        parsed = urlparse(base)
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or parsed.port == 0:
            raise ValueError("La URL debe contener únicamente el servidor local y su puerto.")
    except ValueError as exc:
        raise SetupError(str(exc)) from exc
    runtime = root / ".runtime"
    if not runtime.resolve().is_relative_to(root):
        raise SetupError(".runtime debe estar dentro de la carpeta del proyecto.")
    result = {"modelo": model, "base_url": base, "servidor_iniciado": False,
              "runtime_descargado": False, "modelo_descargado": False, "preparado": False}
    progress(f"Preparando IA local: {model}. La primera ejecución puede descargar Ollama y el modelo.")
    try:
        # Probe antes de crear archivos: un permiso de red denegado no es ausencia.
        _probe(base)
        with _setup_lock(runtime, progress):
            version = _probe(base)  # otro proceso pudo completar la preparación
            if not version:
                if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"} or sys.maxsize <= 2 ** 32:
                    raise SetupError("La instalación automática está disponible para Windows x64. En este sistema inicia Ollama por tu cuenta; después el programa reutilizará su servicio local.")
                binary = _binary(runtime)
                if not binary:
                    binary = _install_runtime(runtime, progress)
                    result["runtime_descargado"] = True
                progress("Iniciando Ollama local en segundo plano…")
                process = _start_server(binary, runtime, base)
                result["servidor_iniciado"] = True
                try:
                    version = _wait_ready(base, process)
                except Exception:
                    # Solo el proceso creado aquí; nunca servicios ajenos.
                    if process.poll() is None:
                        process.terminate()
                    (runtime / "server.pid").unlink(missing_ok=True)
                    raise
            result["version"] = version["version"]
            tags = _json(base, "/api/tags")
            if not _has_model(tags, model):
                _space(runtime, 6 * GIB)
                _pull_model(base, model, progress)
                if not _has_model(_json(base, "/api/tags"), model):
                    raise SetupError("La descarga indicó éxito, pero el modelo no figura en Ollama.")
                result["modelo_descargado"] = True
            else:
                progress("Modelo encontrado; se reutiliza sin descargarlo de nuevo.")
            if prepare:
                progress("Cargando el modelo en memoria antes de atender consultas…")
                warmup = _json(base, "/api/generate", {"model": model, "prompt": "", "stream": False,
                      "keep_alive": "10m", "options": {"num_ctx": 8192}}, timeout=300)
                if warmup.get("done") is not True:
                    raise SetupError("Ollama no confirmó la carga del modelo; no se ejecutarán consultas.")
                result["preparado"] = True
            progress("IA local preparada.")
            return result
    except SetupError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise SetupError(f"No se pudo preparar Ollama ({type(exc).__name__}). Comprueba conexión, espacio y permisos; no se usará el modo offline como sustituto.") from exc
