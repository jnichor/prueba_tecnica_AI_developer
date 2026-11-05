"""Comprueba respuestas ya guardadas comparándolas con los datos y las condiciones, sin llamar a Qwen ni generar otras respuestas.
Por ejemplo, si S-5521 está en evaluación pero la respuesta dice que ya fue pagado, el informe señala la contradicción.

Guarda un informe para leer y otro para procesar con un programa.
El código de salida indica: 0, todos los casos pasaron; 1, hay casos incorrectos o pendientes de revisar; 2, no pudo leer o comprobar la entrada.
Ejecuta ``python -m scripts.evaluar`` desde la carpeta principal del proyecto."""

import argparse
import json
from pathlib import Path

from seguros.evaluation import (EvaluationInputError, evaluar, evaluar_detalle,
                                evaluar_reporte, guardar_informe, normalizar,
                                validar_resultados, incorporar_metricas_guardadas)


ROOT = Path(__file__).resolve().parents[1]


def main():
    """Lee el archivo indicado con --entrada y comprueba sus respuestas.
    Si no eliges un archivo, busca las ejecuciones locales; no toma por defecto los resultados publicados en salidas/.
    
    Por ejemplo, compara el estado que una respuesta atribuye a S-5521 con el estado guardado en los datos.
    Guarda el detalle de lo que pasó o falló y conserva el archivo de respuestas original."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", type=Path, default=None)
    parser.add_argument("--informe", type=Path, default=None)
    parser.add_argument("--salida-json", "--json", dest="salida_json", type=Path, default=None)
    args = parser.parse_args()
    source = args.entrada
    if source is None:
        # Buscamos pruebas locales; salidas/ contiene la copia de resultados para compartir.
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
