"""Cliente HTTP pequeño para la API local de Ollama, sin dependencias externas."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def load_env(path: Path) -> None:
    """Carga valores simples sin ejecutar código ni sobreescribir el entorno."""
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() in {"AGENT_MODE", "OLLAMA_MODEL", "OLLAMA_BASE_URL"}:
                    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class ModelError(RuntimeError):
    pass


class OllamaModel:
    def __init__(self, modelo=None, base_url=None, timeout=120):
        self.modelo = modelo or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Ollama debe usar una dirección local (localhost).")
        self.timeout = timeout
        self.events = []
        self.telemetry_path = None

    def chat(self, messages, tools, format_schema=None):
        payload = {"model": self.modelo, "messages": messages, "tools": tools,
                   "stream": False, "keep_alive": "10m",
                   "options": {"temperature": 0, "num_predict": 600, "num_ctx": 8192}}
        if self.modelo.startswith("qwen3"):
            payload["think"] = False
        if format_schema:
            payload["format"] = format_schema
        request = Request(self.base_url + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        start = time.perf_counter()
        event = {"numero": len(self.events) + 1, "modelo": self.modelo,
                 "timestamp": datetime.now(timezone.utc).isoformat(), "estado": "error",
                 "etapa": "interpretacion_estructurada" if format_schema else "solicitud_modelo"}
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ModelError("La respuesta del modelo excedió el límite permitido.")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ModelError("Ollama devolvió un objeto de respuesta inválido.")
            # Preserve observed counters even when final message validation fails.
            # Agent marks such usage incomplete instead of claiming an exact sum.
            event.update({"prompt_eval_count": result.get("prompt_eval_count"),
                          "eval_count": result.get("eval_count")})
            message = result.get("message")
            if not isinstance(message, dict):
                raise ModelError("Ollama no devolvió un mensaje válido.")
            event.update({"estado": "ok", "respuesta_modelo": message,
                          "done_reason": result.get("done_reason")})
            return message
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            event["error_tipo"] = type(exc).__name__
            raise ModelError("No se pudo consultar Ollama. Comprueba el servicio local y el modelo configurado.") from exc
        finally:
            event["segundos"] = round(time.perf_counter() - start, 3)
            self.events.append(event)
            if self.telemetry_path:
                path = Path(self.telemetry_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
