"""IA interpreta intención; código autorizado recupera y explica evidencia."""

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .model import ModelError, OllamaModel, load_env
from .planning import PlanError, Planner, STRATEGY, offline_plan
from .resolver import Resolver
from .tools import Tools


ROOT = Path(__file__).resolve().parents[1]


class Agent:
    def __init__(self, root=None, output_dir=None, modo="ollama", modelo=None,
                 fecha_referencia="2026-10-15"):
        self.root = Path(root) if root else ROOT
        self.output_dir = Path(output_dir) if output_dir else self.root / ("salidas" if modo == "offline" else "salidas_ollama_corregido")
        load_env(self.root / ".env")
        if modo not in {"offline", "ollama"}:
            raise ValueError("Modo permitido: offline u ollama.")
        self.modo = modo
        self.today = date.fromisoformat(fecha_referencia)
        # Los datos solo llegan al resolutor de código, nunca al modelo.
        self.tools = Tools(root=self.root, output_dir=self.output_dir, safe_model=False)
        self.model = OllamaModel(modelo=modelo) if modo == "ollama" else None
        if self.model:
            self.model.telemetry_path = self.output_dir / "llm_calls.jsonl"
        self.trace = []
        self.policy_sources = []

    def _call(self, name, arguments, session):
        if not isinstance(name, str) or name not in {"consulta_datos", "buscar_condicionados", "escalar_humano"}:
            result = {"error": "Herramienta no permitida.", "fuentes": []}
        elif not isinstance(arguments, dict) or len(json.dumps(arguments, ensure_ascii=False)) > 12000:
            result = {"error": "Argumentos inválidos o demasiado largos.", "fuentes": []}
        else:
            result = self.tools.call(name, arguments, session)
        self.trace.append({"nombre": name, "argumentos": arguments, "resultado": result})
        return result

    def _sources(self):
        return list(dict.fromkeys([source for item in self.trace
                                  for source in item["resultado"].get("fuentes", [])] + self.policy_sources))

    def _model_events(self):
        events = getattr(self.model, "events", [])
        return events if isinstance(events, list) else []

    @staticmethod
    def _token_usage(events, no_calls=False):
        """Suma contadores de la API; nunca estima tokens desde el texto."""
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
        self._call("buscar_condicionados", {"consulta": "articulo 10", "ramo": "general"}, session)
        self.policy_sources.append("ENUNCIADO.pdf, regla de negocio 5 (sin inventar)")
        ticket = self._call("escalar_humano", {"motivo": "Interpretación de consulta no disponible o no validada",
                           "detalle": mensaje}, session)
        if ticket.get("error") or not ticket.get("ticket_id"):
            return ("No pude interpretar tu consulta de forma segura. No voy a inventar información. "
                    "Tampoco se pudo registrar la derivación; contacta a un asesor por un canal de atención.")
        return ("No pude interpretar tu consulta de forma segura. No voy a inventar información ni "
                "sustituir la IA por una respuesta offline. Registré la solicitud " + ticket["ticket_id"] +
                " para revisión humana. El ticket es local y no implica contacto automático.")

    def respond(self, mensaje, session):
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
                if self.modo == "offline":
                    plan = offline_plan(mensaje)
                    interpretation = "offline_explicito"
                else:
                    model_invoked = True
                    # Se crea con el modelo actual para permitir inyección en pruebas.
                    plan = Planner(self.model, self.today).interpret(mensaje, session)
                    interpretation = "modelo"
                answer = resolver.resolve(plan, mensaje, session)
        except (PlanError, ModelError):
            state, interpretation = "error", "error_modelo" if self.modo == "ollama" else "error_interpretacion"
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
                  "modo": self.modo, "estado": state, "fecha_referencia": self.today.isoformat(),
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
