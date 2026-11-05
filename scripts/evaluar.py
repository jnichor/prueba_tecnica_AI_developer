"""Revisa respuestas guardadas mediante reglas y genera informes explicables.

Salida: 0 si todos cumplen comprobaciones, 1 si hay parciales/fallos,
2 si la entrada o configuración es inválida. No reemplaza revisión humana.
Se ejecuta desde la raíz con ``python -m scripts.evaluar`` y no llama al modelo.
"""

import argparse
import json
from pathlib import Path

from seguros.evaluation import (EvaluationInputError, evaluar, evaluar_detalle,
                                evaluar_reporte, guardar_informe, normalizar,
                                validar_resultados, incorporar_metricas_guardadas)


ROOT = Path(__file__).resolve().parents[1]


def main():
    """Lee una ejecución y conserva por separado la entrada y los informes de revisión."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", type=Path, default=None)
    parser.add_argument("--informe", type=Path, default=None)
    parser.add_argument("--salida-json", "--json", dest="salida_json", type=Path, default=None)
    args = parser.parse_args()
    source = args.entrada
    if source is None:
        # Se priorizan ejecuciones locales; salidas/ contiene evidencia publicada.
        candidates = [ROOT / "salidas_ollama_corregido/respuestas.json",
                      ROOT / "salidas_ollama/respuestas.json", ROOT / "salidas_offline/respuestas.json"]
        source = next((candidate for candidate in candidates if candidate.is_file()), candidates[-1])
    try:
        results = json.loads(source.read_text(encoding="utf-8-sig"))
        report = evaluar_reporte(results, root=ROOT)
        incorporar_metricas_guardadas(report, source)
        report["entrada"] = str(source.resolve())
        markdown, data = guardar_informe(report, source, args.informe, args.salida_json)
    except (EvaluationInputError, OSError, ValueError, KeyError) as exc:
        print("Evaluación no ejecutada: " + str(exc))
        return 2
    print(json.dumps(report["resumen"], ensure_ascii=False))
    print("Comprobaciones acotadas; no equivalen a certificación semántica universal.")
    print("Informe:", markdown)
    print("JSON:", data)
    return int(not report["todos_cumplen"])


if __name__ == "__main__":
    raise SystemExit(main())
