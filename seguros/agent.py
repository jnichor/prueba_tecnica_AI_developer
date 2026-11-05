"""Une los pasos para atender una pregunta. Comprueba el usuario, pide a Qwen entender
la pregunta y prepara la respuesta con los datos permitidos. Guarda lo ocurrido, los
tokens y el tiempo.
"""

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .model import ModelError, OllamaModel, load_env
from .planning import PlanError, Planner, STRATEGY
from .resolver import Resolver
from .tools import Tools


ROOT = Path(__file__).resolve().parents[1]


class Agent:
    """Atiende las consultas que llegan desde la consola o los doce casos. Coordina los
    pasos, pero no aprueba pagos ni cambia pólizas o siniestros.
    """
    def __init__(self, root=None, output_dir=None, modelo=None,
                 fecha_referencia="2026-10-15"):
        """Recibe las carpetas y la fecha del ejercicio. Prepara las
        piezas del programa; aquí no descarga ni inicia Ollama.
        """
        self.root = Path(root) if root else ROOT
        self.output_dir = Path(output_dir) if output_dir else self.root / "salidas_ollama_corregido"
        load_env(self.root / ".env")
        self.today = date.fromisoformat(fecha_referencia)
        # Los datos se usan para preparar la respuesta; no se envían a Qwen.
        self.tools = Tools(root=self.root, output_dir=self.output_dir, safe_model=False)
        self.model = OllamaModel(modelo=modelo)
        if self.model:
            self.model.telemetry_path = self.output_dir / "llm_calls.jsonl"
        self.trace = []
        self.policy_sources = []

    def _call(self, name, arguments, session):
        """Recibe el nombre de una herramienta, lo que necesita para trabajar y el
        usuario que consulta. Comprueba que la herramienta esté permitida y guarda
        tanto el pedido como el resultado. Por ejemplo, consulta_datos puede buscar
        S-5521 entre los registros que puede ver C001. Devuelve lo encontrado o un
        error; no deja que el mensaje del usuario agregue otra herramienta.
        """
        if not isinstance(name, str) or name not in {"consulta_datos", "buscar_condicionados", "escalar_humano"}:
            result = {"error": "Herramienta no permitida.", "fuentes": []}
        elif not isinstance(arguments, dict) or len(json.dumps(arguments, ensure_ascii=False)) > 12000:
            result = {"error": "Argumentos inválidos o demasiado largos.", "fuentes": []}
        else:
            result = self.tools.call(name, arguments, session)
        self.trace.append({"nombre": name, "argumentos": arguments, "resultado": result})
        return result

    def _sources(self):
        """Revisa la lista de herramientas utilizadas y recoge de sus resultados las
        fuentes que realmente devolvieron. También añade las reglas del programa que
        se usaron y quita las fuentes repetidas. Por ejemplo, puede incluir
        siniestros:S-5521 o el Artículo 5 del condicionado vehicular. No crea una
        cita solo porque Qwen o el usuario la hayan escrito.
        """
        return list(dict.fromkeys([source for item in self.trace
                                  for source in item["resultado"].get("fuentes", [])] + self.policy_sources))

    def _model_events(self):
        """Devuelve la lista de llamadas hechas a Qwen. Si no hay una lista disponible,
        devuelve una lista vacía.
        """
        events = getattr(self.model, "events", [])
        return events if isinstance(events, list) else []

    @staticmethod
    def _token_usage(events, no_calls=False):
        """Recibe los contadores de las llamadas a Ollama y suma lo que informan cuando
        todas terminaron bien. Los tokens son fragmentos del texto enviado y
        recibido. Ejemplo inventado para explicar la suma: 100 de entrada y 20 de
        salida dan 120 en total; si hubo dos intentos, suma ambos. Sin llamadas
        devuelve cero. Si falta algún contador o una llamada terminó con error, el
        total queda como desconocido y conserva por separado los números que sí
        recibió, sin inventar el resto.
        """
        if no_calls:
            return {"tokens_entrada": 0, "tokens_salida": 0, "tokens_total": 0,
                    "tokens_medicion_completa": True}

        def count(event, key):
            value = event.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

        successful = bool(events) and all(event.get("estado") == "ok" for event in events)
        inputs = [count(event, "prompt_eval_count") for event in events]
        outputs = [count(event, "eval_count") for event in events]
        total_input = sum(inputs) if successful and all(value is not None for value in inputs) else None
        total_output = sum(outputs) if successful and all(value is not None for value in outputs) else None
        complete = total_input is not None and total_output is not None
        usage = {"tokens_entrada": total_input, "tokens_salida": total_output,
                 "tokens_total": total_input + total_output if complete else None,
                 "tokens_medicion_completa": complete}
        if not complete and any(value is not None for value in inputs + outputs):
            observed_inputs = sum(value for value in inputs if value is not None)
            observed_outputs = sum(value for value in outputs if value is not None)
            usage["tokens_contabilizados"] = {"entrada": observed_inputs, "salida": observed_outputs,
                                             "total": observed_inputs + observed_outputs}
        return usage

    def _failed_interpretation(self, mensaje, session):
        """Cuando no se pudo entender la pregunta con seguridad, registra una solicitud
        de revisión. Devuelve un mensaje con el ticket local o avisa si tampoco pudo
        crearlo.
        """
        self._call("buscar_condicionados", {"consulta": "articulo 10", "ramo": "general"}, session)
        self.policy_sources.append("ENUNCIADO.pdf, regla de negocio 5 (sin inventar)")
        ticket = self._call("escalar_humano", {"motivo": "Interpretación de consulta no disponible o no validada",
                           "detalle": mensaje}, session)
        if ticket.get("error") or not ticket.get("ticket_id"):
            return ("No pude interpretar tu consulta de forma segura. No voy a inventar información. "
                    "Tampoco se pudo registrar la derivación; contacta a un asesor por un canal de atención.")
        return ("No pude interpretar tu consulta de forma segura. No voy a inventar información ni "
                "responder sin una interpretación válida. Registré la solicitud " + ticket["ticket_id"] +
                " para revisión humana. El ticket es local y no implica contacto automático.")

    def respond(self, mensaje, session):
        """Recibe la pregunta y la sesión, que contiene el rol y el código de usuario
        elegidos. Primero comprueba qué puede consultar y detiene los pedidos que no
        están permitidos. Cuando hace falta, pide a Qwen entender la pregunta;
        después busca los datos y prepara una respuesta con fuentes. Devuelve esa
        respuesta, las fuentes, las herramientas utilizadas, los tokens y el tiempo,
        y guarda lo ocurrido aunque haya un error. Ejemplo: si C001 pregunta cómo va
        S-5521, busca ese siniestro solo entre sus datos. Que el programa termine sin
        error no garantiza que todo lo dicho sea correcto.
        """
        started = time.perf_counter()
        self.trace, self.policy_sources = [], []
        llm_start = len(self._model_events())
        model_invoked = False
        state, plan, interpretation = "ok", None, "sin_interpretar"
        resolver = None
        try:
            if not isinstance(mensaje, str) or not mensaje.strip() or len(mensaje) > 8000:
                raise ValueError("La consulta debe tener entre 1 y 8000 caracteres.")
            if not self.tools.validate_session(session):
                self.policy_sources = ["ENUNCIADO.pdf, reglas de negocio 2 y 3 (identidad y privacidad)"]
                raise ValueError("La sesión no es válida o no se pudo validar. No puedo consultar información.")
            resolver = Resolver(self.today, self._call)
            guarded = resolver.guard(mensaje, session)
            if guarded is not None:
                answer, interpretation = guarded, "guardia_determinista"
            else:
                model_invoked = True
                # Se usa el modelo actual para poder probarlo con una respuesta simulada.
                plan = Planner(self.model, self.today).interpret(mensaje, session)
                interpretation = "modelo"
                answer = resolver.resolve(plan, mensaje, session)
        except (PlanError, ModelError):
            state, interpretation = "error", "error_modelo"
            answer = self._failed_interpretation(mensaje, session)
        except ValueError as exc:
            answer, state = str(exc), "error"
        if resolver is not None:
            self.policy_sources.extend(resolver.policy_sources)
        if not self._sources():
            self.policy_sources.append("ENUNCIADO.pdf, regla de negocio 5 (sin inventar)")
        sources = self._sources()
        answer += "\n\nFuentes: " + "; ".join(sources)
        result = {"respuesta": answer, "herramientas": list(self.trace), "fuentes": sources,
                  "modo": "ollama", "estado": state, "fecha_referencia": self.today.isoformat(),
                  "plan_validado": plan, "estrategia": STRATEGY, "interpretacion": interpretation}
        events = self._model_events()[llm_start:]
        model_name = getattr(self.model, "modelo", None)
        result["modelo"] = model_name if isinstance(model_name, str) else None
        result["llm_llamadas"] = len(events)
        result["llm_segundos"] = round(sum(event.get("segundos", 0) for event in events), 3)
        result.update(self._token_usage(events, no_calls=not model_invoked and not events))
        result["total_segundos"] = round(time.perf_counter() - started, 3)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "consulta": mensaje,
                 "usuario": session, **result}
        with (self.output_dir / "interactions.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return result
