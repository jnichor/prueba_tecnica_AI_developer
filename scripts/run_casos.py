"""Lee las 12 preguntas de casos_prueba/casos_prueba.json y guarda las respuestas del agente.
Cada pregunta incluye el rol y el usuario que se usarán en esa prueba.

Desde la carpeta principal del proyecto:
- ``python -m scripts.run_casos`` genera y guarda las respuestas.
- ``python -m scripts.run_casos --evaluar`` hace lo anterior y después comprueba si las respuestas coinciden con los datos y las condiciones."""

import argparse
import json
import os
from pathlib import Path

from seguros.agent import Agent, ROOT
from seguros.bootstrap import SetupError, ensure_ollama
from seguros.model import load_env


def main():
    """Lee las opciones del comando y prepara Ollama si se va a usar IA.
    Luego el agente interpreta cada pregunta, consulta los datos permitidos y responde con sus fuentes.
    Por ejemplo, CP-01 pregunta por S-5521 usando al cliente C001; la identidad viene del archivo de casos.
    
    Guarda todas las respuestas en respuestas.json, dentro de la carpeta de trabajo elegida.
    Sin --evaluar termina ahí; con --evaluar también guarda los informes que explican qué comprobó y qué casos pasaron."""
    load_env(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modo", choices=["offline", "ollama"], default=os.getenv("AGENT_MODE", "ollama"))
    parser.add_argument("--modelo", default=None)
    parser.add_argument("--salida", type=Path, default=None)
    parser.add_argument("--solo-preparar", action="store_true", help="Prepara IA local sin ejecutar los casos.")
    parser.add_argument("--evaluar", action="store_true", help="Evalúa el lote con las comprobaciones del programa.")
    args = parser.parse_args()
    modelo = args.modelo
    if args.modo == "ollama":
        try:
            preparado = ensure_ollama(modelo=args.modelo, root=ROOT)
            modelo = preparado["modelo"]
        except SetupError as exc:
            print(f"Preparación falló: {exc}")
            return 1
    if args.solo_preparar:
        if args.modo == "offline":
            print("El modo offline no necesita preparación ni usa red.")
        return 0
    args.salida = args.salida or ROOT / ("salidas_ollama_corregido" if args.modo == "ollama" else "salidas_offline")
    cases = json.loads((ROOT / "casos_prueba" / "casos_prueba.json").read_text(encoding="utf-8-sig"))
    agent = Agent(root=ROOT, output_dir=args.salida, modo=args.modo, modelo=modelo,
                  fecha_referencia=cases["fecha_referencia"])
    outputs = []
    # Cada caso trae su usuario; no lo sacamos de lo que dice la pregunta.
    for case in cases["casos"]:
        result = agent.respond(case["mensaje"], {"rol": case["rol"], "usuario_id": case["usuario_id"]})
        outputs.append({"id": case["id"], "consulta": case["mensaje"], **result})
        print(f"{case['id']}: {result['estado']} ({len(result['herramientas'])} herramientas)")
    args.salida.mkdir(parents=True, exist_ok=True)
    (args.salida / "respuestas.json").write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Modo: {args.modo}. Respuestas guardadas en {args.salida / 'respuestas.json'}")
    if args.modo == "offline":
        print("Baseline determinista sin modelo de IA. Esta ejecución no evalúa la calidad de un LLM.")
    if args.evaluar:
        # Esta comprobación usa código; no pide a Qwen que califique su respuesta.
        from seguros.evaluation import evaluar_reporte, guardar_informe
        report = evaluar_reporte(outputs, root=ROOT)
        guardar_informe(report, args.salida / "respuestas.json")
        print("Comprobaciones del programa:", json.dumps(report["resumen"], ensure_ascii=False))
        return int(not report["todos_cumplen"])
    return int(any(output["estado"] == "error" for output in outputs))


if __name__ == "__main__":
    raise SystemExit(main())
