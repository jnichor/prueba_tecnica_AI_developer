"""Comprueba que los comandos preparen Ollama antes de responder y guarden los archivos en la carpeta correcta.
Las conexiones y respuestas se preparan dentro de las pruebas, sin usar una IA real ni sobrescribir las salidas publicadas."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import consultar
from scripts import run_casos
from seguros.bootstrap import SetupError
from seguros.model import OllamaModel


class SetupEntrypointTests(unittest.TestCase):
    """Comprueba en qué orden se preparan los servicios y se ejecutan las preguntas."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "casos_prueba").mkdir()
        (self.root / "casos_prueba/casos_prueba.json").write_text(json.dumps({
            "fecha_referencia": "2026-10-15", "casos": [{"id": "CP-FIXTURE",
                "rol": "cliente", "usuario_id": "C001", "mensaje": "Estado de mi siniestro"}]}),
            encoding="utf-8")

    def ejecutar(self, modulo, argumentos, entorno=None, error=None):
        """Ejecuta el comando con respuestas preparadas para esta prueba y recoge lo que imprime."""
        eventos = []
        creado = {}

        def preparar(*args, **kwargs):
            eventos.append("preparar")
            self.assertEqual(kwargs["root"], self.root)
            if error:
                raise error
            modelo = kwargs.get("modelo") or os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
            return {"modelo": modelo, "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                    "version": "fixture", "servidor_iniciado": False, "runtime_descargado": False,
                    "modelo_descargado": False, "preparado": True}

        def agente(*args, **kwargs):
            eventos.append("agente")
            creado.update(kwargs)
            creado["url_modelo"] = OllamaModel(modelo=kwargs.get("modelo")).base_url

            def responder(mensaje, sesion):
                eventos.append("consulta")
                return {"respuesta": "Respuesta de fixture", "estado": "ok", "herramientas": [],
                        "fuentes": [], "modo": "ollama", "modelo": kwargs.get("modelo"),
                        "llm_llamadas": 0, "llm_segundos": 0}

            instancia = Mock()
            instancia.respond.side_effect = responder
            return instancia

        salida = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, entorno or {}, clear=True))
            stack.enter_context(patch("sys.argv", [modulo.__file__, *argumentos]))
            stack.enter_context(patch.object(modulo, "ROOT", self.root))
            stack.enter_context(patch.object(modulo, "load_env"))
            preparar_mock = stack.enter_context(patch.object(modulo, "ensure_ollama", side_effect=preparar))
            agente_mock = stack.enter_context(patch.object(modulo, "Agent", side_effect=agente))
            stack.enter_context(redirect_stdout(salida))
            stack.enter_context(redirect_stderr(salida))
            codigo = modulo.main()
        return codigo, eventos, creado, preparar_mock, agente_mock, salida.getvalue()

    def test_runner_default_prepara_antes_de_crear_agente_y_consultar(self):
        codigo, eventos, creado, preparar, _, _ = self.ejecutar(run_casos, [])
        self.assertEqual(codigo, 0)
        self.assertEqual(eventos, ["preparar", "agente", "consulta"])
        preparar.assert_called_once_with(modelo=None, root=self.root)
        self.assertNotIn("modo", creado)
        self.assertEqual(creado["modelo"], "qwen2.5:7b")
        self.assertTrue((self.root / "salidas_ollama_corregido/respuestas.json").is_file())

    def test_runner_rechaza_el_selector_de_modo_retirado(self):
        for value in ("offline", "ollama"):
            with self.subTest(value=value), self.assertRaises(SystemExit) as stopped:
                self.ejecutar(run_casos, ["--modo", value], error=AssertionError("No debe preparar un comando inválido"))
            self.assertEqual(stopped.exception.code, 2)

    def test_runner_preserva_respuestas_publicadas_en_salidas(self):
        published = self.root / "salidas/respuestas.json"
        published.parent.mkdir()
        original = b'{"evidencia_publicada":true}\n'
        published.write_bytes(original)
        codigo, _, creado, preparar, _, _ = self.ejecutar(run_casos, [])
        self.assertEqual(codigo, 0)
        preparar.assert_called_once()
        self.assertEqual(creado["output_dir"], self.root / "salidas_ollama_corregido")
        self.assertTrue((self.root / "salidas_ollama_corregido/respuestas.json").is_file())
        self.assertEqual(published.read_bytes(), original)

    def test_solo_preparar_no_crea_agente_ni_ejecuta_casos(self):
        codigo, eventos, _, preparar, agente, _ = self.ejecutar(run_casos, ["--solo-preparar"])
        self.assertEqual(codigo, 0)
        self.assertEqual(eventos, ["preparar"])
        preparar.assert_called_once()
        agente.assert_not_called()
        self.assertFalse((self.root / "salidas_ollama_corregido/respuestas.json").exists())

    def test_solo_preparar_falla_sin_crear_agente_si_la_preparacion_falla(self):
        codigo, eventos, _, preparar, agente, _ = self.ejecutar(
            run_casos, ["--solo-preparar"], error=SetupError("No se pudo preparar el modelo"))
        self.assertEqual(codigo, 1)
        self.assertEqual(eventos, ["preparar"])
        preparar.assert_called_once()
        agente.assert_not_called()

    def test_error_preparacion_retorna_uno_sin_agente_ni_fallback(self):
        codigo, eventos, _, _, agente, texto = self.ejecutar(
            run_casos, [], error=SetupError("Fallo simulado de preparación"))
        self.assertEqual(codigo, 1)
        self.assertEqual(eventos, ["preparar"])
        agente.assert_not_called()
        self.assertIn("Preparación falló", texto)
        self.assertFalse((self.root / "salidas_offline/respuestas.json").exists())
        self.assertFalse((self.root / "salidas_ollama_corregido/respuestas.json").exists())

    def test_modelo_cli_prevalece_sobre_entorno_y_se_usa_el_preparado(self):
        codigo, _, creado, preparar, _, _ = self.ejecutar(
            run_casos, ["--modelo", "modelo-cli"], {"OLLAMA_MODEL": "modelo-entorno"})
        self.assertEqual(codigo, 0)
        preparar.assert_called_once_with(modelo="modelo-cli", root=self.root)
        self.assertEqual(creado["modelo"], "modelo-cli")

    def test_modelo_entorno_se_conserva_y_url_no_se_sustituye(self):
        direccion = "http://127.0.0.1:11435"
        codigo, _, creado, preparar, _, _ = self.ejecutar(
            run_casos, [], {"OLLAMA_MODEL": "modelo-entorno", "OLLAMA_BASE_URL": direccion})
        self.assertEqual(codigo, 0)
        preparar.assert_called_once_with(modelo=None, root=self.root)
        self.assertEqual(creado["modelo"], "modelo-entorno")
        self.assertEqual(creado["url_modelo"], direccion)

    def test_variable_antigua_no_desactiva_la_preparacion_de_ia(self):
        codigo, eventos, creado, preparar, _, _ = self.ejecutar(run_casos, [], {"AGENT_MODE": "offline"})
        self.assertEqual(codigo, 0)
        preparar.assert_called_once()
        self.assertEqual(eventos, ["preparar", "agente", "consulta"])
        self.assertNotIn("modo", creado)

    def test_consulta_individual_prepara_antes_del_agente(self):
        codigo, eventos, creado, preparar, _, _ = self.ejecutar(consultar, [
            "--rol", "cliente", "--usuario", "C001", "--mensaje", "Estado de mi siniestro"])
        self.assertEqual(codigo, 0)
        self.assertEqual(eventos, ["preparar", "agente", "consulta"])
        preparar.assert_called_once()
        self.assertNotIn("modo", creado)

    def test_consulta_individual_no_acepta_el_selector_de_modo_retirado(self):
        with self.assertRaises(SystemExit) as stopped:
            self.ejecutar(consultar, ["--rol", "cliente", "--usuario", "C001", "--mensaje", "Consulta",
                                      "--modo", "offline"],
                          error=AssertionError("No debe preparar un comando inválido"))
        self.assertEqual(stopped.exception.code, 2)

    def test_consulta_individual_error_preparacion_sin_agente(self):
        codigo, eventos, _, _, agente, _ = self.ejecutar(consultar, [
            "--rol", "cliente", "--usuario", "C001", "--mensaje", "Consulta"],
            error=SetupError("Fallo simulado"))
        self.assertEqual(codigo, 1)
        self.assertEqual(eventos, ["preparar"])
        agente.assert_not_called()


if __name__ == "__main__":
    unittest.main()
