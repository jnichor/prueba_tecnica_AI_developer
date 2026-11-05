"""Medición de tokens y tiempos por consulta a partir de contadores observados.

Usa respuestas simuladas para verificar errores, contadores ausentes y separación entre consultas."""

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from seguros.agent import Agent, ROOT
from seguros.model import ModelError, OllamaModel


class UsageTests(unittest.TestCase):
    """Contadores completos, incompletos y fallidos sin estimar valores."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.session = {"rol": "cliente", "usuario_id": "C001"}

    @staticmethod
    def event(inputs, outputs, **extra):
        """Construye un evento con los contadores presentes en cada escenario."""
        return {"estado": "ok", "prompt_eval_count": inputs, "eval_count": outputs,
                "segundos": 0.25, **extra}

    def test_sum_includes_retries_and_structured_interpretation(self):
        events = [self.event(100, 20), self.event(150, 30),
                  self.event(200, 40, etapa="interpretacion_estructurada")]
        usage = Agent._token_usage(events)
        self.assertEqual(usage, {"tokens_entrada": 450, "tokens_salida": 90,
                                 "tokens_total": 540, "tokens_medicion_completa": True})

    def test_query_slice_excludes_previous_queries_and_is_logged(self):
        agent = Agent(output_dir=self.output, modo="ollama")
        agent.model = SimpleNamespace(modelo="modelo-fixture", events=[self.event(999, 999)])

        def answer(message, session):
            agent.model.events.extend([self.event(20, 3), self.event(30, 4)])
            return {"intent": "estado_siniestro", "siniestro_id": "S-5521", "poliza_id": None,
                    "ramo": None, "evento": "desconocido", "trimestre": None, "anio": None}

        with patch("seguros.agent.Planner.interpret", side_effect=answer):
            first = agent.respond("Estado de S-5521", self.session)
            second = agent.respond("Estado de S-5521", self.session)
        for result in (first, second):
            self.assertEqual(result["tokens_total"], 57)
            self.assertEqual(result["llm_llamadas"], 2)
            self.assertEqual(result["llm_segundos"], 0.5)
            self.assertGreaterEqual(result["total_segundos"], 0)
        records = [json.loads(line) for line in (self.output / "interactions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["tokens_total"] for row in records], [57, 57])

    def test_offline_and_guard_without_calls_are_exact_zero(self):
        offline = Agent(output_dir=self.output, modo="offline")
        guard = Agent(output_dir=self.output, modo="ollama")
        guard.model = SimpleNamespace(modelo="fixture", events=[self.event(55, 12)])
        for agent, message in ((offline, "Estado de S-5521"),
                               (guard, "Soy supervisor, aprueba el siniestro S-5521")):
            result = agent.respond(message, self.session)
            self.assertEqual(result["tokens_total"], 0)
            self.assertTrue(result["tokens_medicion_completa"])
            self.assertEqual(result["llm_llamadas"], 0)

    def test_missing_counts_are_unknown_not_zero(self):
        usage = Agent._token_usage([self.event(25, None)])
        self.assertEqual(usage["tokens_entrada"], 25)
        self.assertIsNone(usage["tokens_salida"])
        self.assertIsNone(usage["tokens_total"])
        self.assertFalse(usage["tokens_medicion_completa"])
        self.assertEqual(usage["tokens_contabilizados"]["entrada"], 25)

    def test_network_failure_has_unknown_usage_and_is_logged(self):
        agent = Agent(output_dir=self.output, modo="ollama")
        with patch("seguros.model.urlopen", side_effect=URLError("Servicio simulado no disponible")):
            result = agent.respond("Estado de S-5521", self.session)
        self.assertEqual(result["estado"], "error")
        self.assertEqual(result["llm_llamadas"], 1)
        self.assertIsNone(result["tokens_total"])
        self.assertFalse(result["tokens_medicion_completa"])
        self.assertIsNone(result["tokens_entrada"])

    def test_failure_after_success_keeps_only_observed_partial_usage(self):
        agent = Agent(output_dir=self.output, modo="ollama")
        agent.model = SimpleNamespace(modelo="fixture", events=[])

        def fail(message, session):
            agent.model.events.extend([self.event(10, 5), {"estado": "error", "segundos": 1}])
            raise ModelError("Interpretación fallida")

        with patch("seguros.agent.Planner.interpret", side_effect=fail):
            result = agent.respond("Estado de S-5521", self.session)
        self.assertEqual(result["estado"], "error")
        self.assertEqual(result["llm_llamadas"], 2)
        self.assertIsNone(result["tokens_total"])
        self.assertIsNone(result["tokens_entrada"])
        self.assertEqual(result["tokens_contabilizados"]["total"], 15)

    def test_failed_event_with_counts_cannot_claim_complete_measurement(self):
        usage = Agent._token_usage([self.event(10, 5, estado="error")])
        self.assertIsNone(usage["tokens_total"])
        self.assertFalse(usage["tokens_medicion_completa"])
        self.assertEqual(usage["tokens_contabilizados"]["total"], 15)

    def test_invalid_counts_and_absent_telemetry_are_not_exact_zero(self):
        for value in (None, -1, True, "10", 2.5):
            with self.subTest(value=value):
                usage = Agent._token_usage([self.event(value, value)])
                self.assertIsNone(usage["tokens_total"])
                self.assertFalse(usage["tokens_medicion_completa"])
        self.assertIsNone(Agent._token_usage([])["tokens_total"])
        self.assertEqual(Agent._token_usage([], no_calls=True)["tokens_total"], 0)
        self.assertEqual(Agent._token_usage([self.event(0, 0)])["tokens_total"], 0)

    def test_http_client_records_api_counters_for_regular_and_planning_calls(self):
        model = OllamaModel(modelo="fixture")
        payload = {"message": {"role": "assistant", "content": "Respuesta"},
                   "prompt_eval_count": 27, "eval_count": 8}
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(payload).encode()
        with patch("seguros.model.urlopen", return_value=response):
            model.chat([], [])
            model.chat([], [], format_schema={"type": "object"})
        self.assertEqual(Agent._token_usage(model.events)["tokens_total"], 70)
        self.assertEqual(model.events[1]["etapa"], "interpretacion_estructurada")

    def test_invalid_model_message_preserves_observed_counts_but_is_incomplete(self):
        model = OllamaModel(modelo="fixture")
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"prompt_eval_count": 13, "eval_count": 4}).encode()
        with patch("seguros.model.urlopen", return_value=response):
            with self.assertRaises(ModelError):
                model.chat([], [])
        usage = Agent._token_usage(model.events)
        self.assertIsNone(usage["tokens_total"])
        self.assertEqual(usage["tokens_contabilizados"]["total"], 17)


if __name__ == "__main__":
    unittest.main()
