"""Copia los resultados revisados en salidas/ y puede reunir los archivos del proyecto en un ZIP.
Primero debes ejecutar las 12 preguntas y su evaluación; aqui se usan los archivos guardados, sin consultar a Qwen.
Ejecuta ``python -m scripts.preparar_entrega`` desde la carpeta principal y usa --empaquetar después de revisar los documentos."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_IDS = ("CP-03", "CP-06", "CP-07", "CP-08", "CP-12")
ROOT_FILES = ("README.md", "DISENO.md", "RESULTADOS.md", ".env.example", ".gitignore")
PUBLIC_GROUPS = {"seguros": {".py"}, "tests": {".py"}, "datos": {".csv", ".md"},
                 "condicionados": {".md"}, "casos_prueba": {".md", ".json"},
                 "scripts": {".py", ".ps1"}}
DELIVERY_FILES = ("respuestas.json", "muestra_interacciones.jsonl", "muestra_tickets.jsonl",
                  "evaluacion_automatica.md", "evaluacion_automatica.json",
                  "VERIFICACION.md", "fuentes_sha256.json")
FALLBACK_MATRIX = """| Regla | Control que debe revisarse | Evidencia disponible |
| --- | --- | --- |
| 1. Fecha | Referencia fija del ejercicio; fechas relativas calculadas en código. | CP-02/04/05. |
| 2. Identidad | Rol e identificador vienen de la sesión, nunca del mensaje. | CP-09 y pruebas de sesión. |
| 3. Privacidad | Tablas filtradas por titularidad antes de consultar. | CP-06/11 y pruebas de aislamiento. |
| 4. Solo lectura | SQL restringido y ninguna acción de aprobación. | CP-09 y pruebas SQL. |
| 5. Sin inventar | Entidades literales, datos y artículos recuperados. | CP-03/05/11 y pruebas del resolutor. |
| 6. Trazabilidad | Fuentes y trazas por afirmación. | Respuestas y evaluación automática. |
| 7. Sin asesoría | Derivación con ticket local. | CP-07 y muestra de tickets. |
| 8. Registro | Consulta, usuario, herramientas, respuesta y métricas. | Muestra de interacciones. |"""


def digest(data):
    """Calcula una huella SHA-256 del contenido. Sirve para comprobar después si un archivo cambió."""
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    """Lee los datos de un archivo JSON, un formato de texto con campos y listas."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path):
    """Lee un archivo JSONL: cada línea contiene un registro separado."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path, content):
    """Guarda los datos en un archivo JSON con un formato fácil de leer."""
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def public_path(root, relative):
    """Revisa la ruta y rechaza los archivos excluidos de la copia pública.
    Busca señales de claves, correos personales y carpetas personales para evitar copiarlos."""
    relative = str(relative)
    posix = PurePosixPath(relative)
    if not relative or "\\" in relative or ":" in relative or posix.is_absolute() or any(part in {".", ".."} for part in relative.split("/")):
        raise ValueError("Ruta pública inválida: " + relative)
    forbidden = {".git", ".runtime", "__pycache__", ".entrega"}
    if any(part in forbidden or part.startswith("salidas_") for part in posix.parts) or posix.name in {".env", "ENUNCIADO.pdf"}:
        raise ValueError("Archivo excluido de la entrega pública: " + relative)
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("La ruta sale del proyecto: " + relative)
    if not path.is_file():
        raise ValueError("Falta el archivo público: " + relative)
    content = path.read_bytes()
    text = content.decode("utf-8-sig")
    if re.search(r"[A-Za-z]:[\\/]+Users[\\/]|[/]Users[/]|[/]home[/][^/\s]+[/]", text):
        raise ValueError("Un archivo público contiene una ruta de perfil: " + relative)
    if re.search(r"[\w.+-]+@(?:gmail|outlook|hotmail|yahoo)\.[A-Za-z.]+", text, re.I):
        raise ValueError("Un archivo público contiene un correo personal: " + relative)
    if re.search(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b", text):
        raise ValueError("Posible credencial en un archivo público: " + relative)
    return path, content


def public_files(root):
    """Devuelve la lista de archivos que se pueden incluir en el ZIP.
    Incluye código, comandos, pruebas, documentos y los resultados seleccionados de salidas/.
    Esta lista no copia todo lo que haya en la carpeta del proyecto."""
    paths = list(ROOT_FILES)
    for directory, suffixes in PUBLIC_GROUPS.items():
        paths.extend(path.relative_to(root).as_posix() for path in sorted((root / directory).iterdir())
                     if path.is_file() and path.suffix in suffixes)
    paths.extend("salidas/" + name for name in DELIVERY_FILES)
    if (root / "salidas/CONSULTAS_HISTORIAL.md").is_file():
        paths.append("salidas/CONSULTAS_HISTORIAL.md")
    paths.append("tests/fixtures/respuestas_pruebas.json")
    return sorted(set(paths))


def prepare(root, source):
    """Lee los resultados de una ejecución ya revisada y los copia a salidas/ para compartirlos.
    Conserva las 12 respuestas y selecciona cinco consultas registradas y el ticket relacionado.
    
    Comprueba que las respuestas, la evaluación y los contadores correspondan a la misma ejecución.
    También guarda huellas de los archivos originales para comprobar después que no cambiaron.
    Las muestras son datos ficticios de esta prueba; los archivos originales quedan intactos."""
    destination = root / "salidas"
    required = ("respuestas.json", "interactions.jsonl", "tickets.jsonl",
                "evaluacion_automatica.md", "evaluacion_automatica.json")
    snapshots = {name: (source / name).read_bytes() for name in required}
    for name in ("EVALUACION.md", "verificacion.json"):
        if (source / name).is_file():
            snapshots[name] = (source / name).read_bytes()
    responses = read_json(source / "respuestas.json")
    cases = read_json(root / "casos_prueba/casos_prueba.json")["casos"]
    if [row["id"] for row in responses] != [row["id"] for row in cases]:
        raise ValueError("Las respuestas no contienen exactamente los casos del paquete en su orden.")
    if not all(row.get("tokens_medicion_completa") is True for row in responses):
        raise ValueError("La evidencia seleccionada tiene mediciones incompletas.")
    # Los totales deben coincidir con lo registrado al responder estas 12 preguntas.
    verification = read_json(source / "verificacion.json") if "verificacion.json" in snapshots else None
    automatic = read_json(source / "evaluacion_automatica.json")
    if not automatic.get("todos_cumplen") or (verification is not None and verification.get("casos_manual_correctos") != len(cases)):
        raise ValueError("La entrega debe corresponder a la ejecución corregida y revisada.")
    calls = sum(row["llm_llamadas"] for row in responses)
    inputs = sum(row["tokens_entrada"] for row in responses)
    outputs = sum(row["tokens_salida"] for row in responses)
    seconds = round(sum(row["llm_segundos"] for row in responses), 3)
    for key, expected in (("llamadas_reales", calls), ("tokens_entrada", inputs),
                          ("tokens_salida", outputs), ("tokens_total", inputs + outputs), ("llm_segundos", seconds)):
        if verification is not None and verification.get(key) != expected:
            raise ValueError("La verificación no coincide con las respuestas: " + key)
    logs = read_jsonl(source / "interactions.jsonl")
    allowed_log_fields = ("timestamp", "consulta", "usuario", "respuesta", "herramientas", "fuentes",
                          "modo", "estado", "fecha_referencia", "estrategia", "modelo", "llm_llamadas",
                          "llm_segundos", "tokens_entrada", "tokens_salida", "tokens_total",
                          "tokens_medicion_completa", "tokens_contabilizados", "total_segundos")
    sample = []
    # Buscamos el mismo usuario, pregunta y respuesta para no copiar otra consulta.
    for identifier in SAMPLE_IDS:
        response = next(row for row in responses if row["id"] == identifier)
        case = next(row for row in cases if row["id"] == identifier)
        matches = [row for row in logs if row.get("consulta") == case["mensaje"]
                   and row.get("usuario") == {"rol": case["rol"], "usuario_id": case["usuario_id"]}
                   and row.get("respuesta") == response["respuesta"]]
        if len(matches) != 1:
            raise ValueError("No se encontró una interacción única para " + identifier)
        sample.append({"caso_id": identifier, **{key: matches[0][key] for key in allowed_log_fields if key in matches[0]}})
    sample_ticket_ids = {tool["resultado"]["ticket_id"] for row in sample for tool in row["herramientas"]
                         if tool["nombre"] == "escalar_humano" and "ticket_id" in tool["resultado"]}
    tickets = [row for row in read_jsonl(source / "tickets.jsonl") if row.get("ticket_id") in sample_ticket_ids]
    if {row["ticket_id"] for row in tickets} != sample_ticket_ids:
        raise ValueError("Falta la evidencia del ticket de escalamiento.")
    destination.mkdir(parents=True, exist_ok=True)
    # Copiamos las respuestas tal como se guardaron, sin cambiar su texto.
    (destination / "respuestas.json").write_bytes(snapshots["respuestas.json"])
    for name, rows in (("muestra_interacciones.jsonl", sample), ("muestra_tickets.jsonl", tickets)):
        (destination / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    (destination / "evaluacion_automatica.json").write_bytes(snapshots["evaluacion_automatica.json"])
    auto_text = snapshots["evaluacion_automatica.md"].decode("utf-8-sig")
    auto_text = re.sub(r"(?m)^Entrada:[^\r\n]*", "Entrada: salidas/respuestas.json", auto_text)
    (destination / "evaluacion_automatica.md").write_bytes(auto_text.encode("utf-8"))
    manual = snapshots.get("EVALUACION.md", b"").decode("utf-8-sig").replace("\r\n", "\n")
    matrix = manual.split("## Matriz de las ocho reglas\n", 1)[1].split("## Regresiones", 1)[0].strip() if manual else FALLBACK_MATRIX
    matrix = matrix.replace("interactions.jsonl: 12 registros", "respuestas.json: 12 casos; muestra_interacciones.jsonl: cinco registros")
    no_model = [row["id"] for row in responses if row["llm_llamadas"] == 0]
    model = ", ".join(sorted({row["modelo"] for row in responses if row.get("modelo")}))
    reviewed = verification is not None and bool(manual)
    review_text = ("Revisión de contenido con asistencia de Codex contra los CSV, los artículos y las trazas de herramientas. "
                   "Se verificaron las doce respuestas y las ocho reglas; no es una revisión humana independiente ni una garantía universal."
                   if reviewed else "Esta ejecución tiene evaluación automática, pero no una nueva revisión de contenido registrada. "
                   "La matriz describe controles que deben revisarse; no certifica que se hayan verificado manualmente. "
                   "Revisa este documento y RESULTADOS.md antes de publicar una ejecución regenerada.")
    test_count = verification.get("pruebas_aprobadas") if reviewed else "no registrada en esta ejecución"
    summary = (
        "# Verificación de la entrega\n\n"
        + review_text + "\n\n"
        + f"- Modelo de la ejecución real: {model}.\n"
        f"- Casos ejecutados: {len(cases)}; evaluación automática: {automatic['resumen']}.\n"
        f"- Llamadas reales: {calls}; controles sin modelo: {', '.join(no_model)}.\n"
        f"- Tokens: {inputs:,} de entrada + {outputs:,} de salida = {inputs + outputs:,}.\n"
        f"- Tiempo acumulado de inferencia: {seconds:.3f} segundos.\n"
        f"- Suite de regresión registrada: {test_count}" + (" pruebas aprobadas.\n\n" if reviewed else ".\n\n")
        + "## Matriz de las ocho reglas\n\n" + matrix + "\n\n"
        "## Evidencia y límites\n\n"
        "[respuestas.json](respuestas.json) conserva exactamente las respuestas de la ejecución revisada. "
        "[muestra_interacciones.jsonl](muestra_interacciones.jsonl) conserva cinco interacciones ficticias con sus campos de auditoría; "
        "se excluyen los eventos internos del modelo. [muestra_tickets.jsonl](muestra_tickets.jsonl) contiene el ticket real local de CP-07. "
        "Las comprobaciones detalladas están en [evaluacion_automatica.md](evaluacion_automatica.md) y su JSON.\n\n"
        "La autenticación de la consola es simulada, los tickets no notifican servicios externos y el dominio implementado es acotado. "
        "CP-08 usa última actualización como aproximación declarada, porque no existe fecha de rechazo ni historial de estados. "
        "El asistente no decide indemnizaciones ni proporciona asesoría médica, legal o de inversión.\n\n"
        "Los SHA-256 de los archivos fuente y de esta selección están en [fuentes_sha256.json](fuentes_sha256.json). "
        "Los originales permanecen locales y no se modifican al preparar esta entrega.\n")
    (destination / "VERIFICACION.md").write_text(summary, encoding="utf-8")
    provenance = {"descripcion": "SHA-256 de la ejecución local fuente; las muestras seleccionan campos de auditoría sin pensamientos internos del modelo.",
                  "fuentes": [{"archivo": source.relative_to(root).as_posix() + "/" + name,
                               "sha256": digest(content), "bytes": len(content)} for name, content in snapshots.items()],
                  "muestras": {"casos": list(SAMPLE_IDS), "ticket_ids": sorted(sample_ticket_ids)},
                  "copias": {name: digest((destination / name).read_bytes()) for name in DELIVERY_FILES if name != "fuentes_sha256.json"}}
    write_json(destination / "fuentes_sha256.json", provenance)
    for name, original in snapshots.items():
        if (source / name).read_bytes() != original:
            raise ValueError("Un archivo original cambió durante la preparación: " + name)
    return destination


def package(root):
    """Crea un ZIP con los archivos de la lista permitida y una lista de sus huellas SHA-256.
    Una huella es un valor calculado a partir del contenido: si cambia el archivo, cambia ese valor.
    Por ejemplo, permite comprobar que respuestas.json dentro del ZIP es el mismo archivo que se revisó.
    
    Después abre el ZIP y compara cada archivo con la lista para detectar cambios o archivos que falten.
    No incluye las claves de .env, los modelos descargados ni los archivos de trabajo de .runtime/."""
    entries = []
    contents = {}
    for relative in public_files(root):
        _, data = public_path(root, relative)
        contents[relative] = data
        entries.append({"path": relative, "bytes": len(data), "sha256": digest(data)})
    local = root / ".entrega"
    local.mkdir(parents=True, exist_ok=True)
    zip_path = local / "prueba_tecnica_AI_developer.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, data in contents.items():
            archive.writestr(relative, data)
    with zipfile.ZipFile(zip_path) as archive:
        if archive.namelist() != [entry["path"] for entry in entries]:
            raise ValueError("El ZIP no coincide con la allowlist.")
        for entry in entries:
            if digest(archive.read(entry["path"])) != entry["sha256"]:
                raise ValueError("El ZIP alteró un archivo.")
    write_json(local / "manifest_publicacion.json", {"files": entries})
    return zip_path, len(entries)


def main():
    """Lee --origen para saber dónde están los resultados de la ejecución que quieres preparar.
    Los revisa y deja una copia seleccionada en salidas/, lista para leer y compartir.
    Si también indicas --empaquetar, crea un único ZIP con los archivos permitidos.
    Este comando trabaja con archivos guardados: no vuelve a ejecutar las 12 preguntas ni consulta a Qwen."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origen", type=Path, default=Path("salidas_ollama_corregido"))
    parser.add_argument("--empaquetar", action="store_true", help="Incluye los documentos finales y genera ZIP y manifiesto local.")
    args = parser.parse_args()
    source = (ROOT / args.origen).resolve()
    if not source.is_relative_to(ROOT.resolve()):
        parser.error("La ejecución de origen debe estar dentro del proyecto.")
    try:
        prepare(ROOT, source)
        if args.empaquetar:
            _, count = package(ROOT)
            print(f"Entrega preparada: {count} archivos en el ZIP y el manifiesto local.")
        else:
            print("Evidencia preparada en salidas/. Revisa los tres documentos antes de usar --empaquetar.")
    except (ValueError, OSError, KeyError, IndexError, UnicodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
