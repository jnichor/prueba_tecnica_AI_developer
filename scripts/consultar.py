"""Permite hacer una pregunta o escribir varias en la consola.
El usuario elegido se mantiene, pero cada pregunta empieza sin recordar las anteriores.
Ejecuta ``python -m scripts.consultar`` desde la carpeta principal e indica el rol y el usuario."""

import argparse
from pathlib import Path

from seguros.agent import Agent, ROOT
from seguros.bootstrap import SetupError, ensure_ollama
from seguros.model import load_env


def show_result(result):
    """Muestra la respuesta del agente y las medidas que recibió: tokens de entrada, de salida y tiempo.
    Por ejemplo, 100 tokens de entrada + 20 de salida = 120 en total; si la consulta tomó 0.5 segundos, también muestra ese tiempo.
    Las cifras del ejemplo son ilustrativas: el comando muestra los valores medidos en cada consulta.
    Si falta una medida, lo indica y no la reemplaza por cero."""
    print(result["respuesta"])
    values = [result.get(key) for key in ("tokens_entrada", "tokens_salida", "tokens_total")]
    labels = [str(value) if isinstance(value, int) and not isinstance(value, bool) else "no disponible" for value in values]
    print(f"\nTokens: entrada {labels[0]} | salida {labels[1]} | total {labels[2]}")
    if not result.get("tokens_medicion_completa", False):
        print("Medición de tokens incompleta; los valores no disponibles no equivalen a cero.")
        partial = result.get("tokens_contabilizados")
        if isinstance(partial, dict):
            print(f"Tokens observados, sin total exacto: {partial.get('total', 'no disponible')}")
    latency = result.get("total_segundos")
    latency_text = f"{latency:.3f} s" if isinstance(latency, (int, float)) else "no disponible"
    model = result.get("modelo") or "sin modelo"
    print(f"Latencia total: {latency_text} | Modo: {result.get('modo', 'no disponible')} | Modelo: {model}")


def main():
    """Lee el rol y el usuario elegidos para la demostración; por ejemplo, --rol cliente --usuario C001.
    Esto no es un inicio de sesión real con contraseña: permite probar las consultas de ese usuario.
    Con --mensaje puedes preguntar por S-5521 una sola vez; sin --mensaje, puedes seguir escribiendo en la consola.
    
    El programa comprueba que el usuario exista y entrega su identidad al agente por separado del mensaje.
    Cada pregunta es independiente. Para terminar puedes escribir salir o exit, pulsar Ctrl+C o dejar de enviar líneas (fin de entrada, EOF)."""
    load_env(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rol", choices=["cliente", "asesor"], required=True)
    parser.add_argument("--usuario", required=True)
    query_mode = parser.add_mutually_exclusive_group()
    query_mode.add_argument("--mensaje", help="Consulta única; si se omite, abre la consola.")
    query_mode.add_argument("--interactivo", action="store_true", help="Consultas independientes con la misma sesión simulada.")
    parser.add_argument("--modelo", default=None)
    parser.add_argument("--salida", type=Path, default=None, help="Carpeta de logs y tickets de esta ejecución.")
    args = parser.parse_args()
    try:
        preparado = ensure_ollama(modelo=args.modelo, root=ROOT)
        modelo = preparado["modelo"]
    except SetupError as exc:
        print(f"Preparación falló: {exc}")
        return 1
    # El mensaje puede pedir algo, pero no puede cambiar esta identidad.
    session = {"rol": args.rol, "usuario_id": args.usuario}
    try:
        agent = Agent(root=ROOT, output_dir=args.salida or ROOT / "salidas_ollama_corregido",
                      modelo=modelo)
        if not agent.tools.validate_session(session):
            print("La sesión simulada no es válida. Verifica el rol y el identificador.")
            return 1
    except (ValueError, OSError) as exc:
        print(f"No se pudo iniciar la consulta: {exc}")
        return 1
    if args.mensaje is not None:
        result = agent.respond(args.mensaje, session)
        show_result(result)
        return int(result["estado"] == "error")
    print(f"Sesión simulada: {args.rol} {args.usuario}. Consultas independientes, sin memoria de conversación.")
    print("Escribe salir o exit para terminar. También puedes usar Ctrl+C.")
    while True:
        try:
            message = input("\nTú: ").strip()
            if message.lower() in {"salir", "exit"}:
                break
            if not message:
                continue
            try:
                result = agent.respond(message, session)
                show_result(result)
            except (ValueError, RuntimeError, OSError) as exc:
                print(f"No se pudo completar esta consulta: {exc}. Puedes intentarlo de nuevo.")
        except (EOFError, KeyboardInterrupt):
            print()
            break
    print("Consola finalizada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
