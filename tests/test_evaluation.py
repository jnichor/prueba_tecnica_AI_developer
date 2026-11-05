"""Comprueba si el evaluador detecta respuestas incorrectas, datos inventados y fuentes que no justifican lo dicho.
También revisa que los informes nuevos no sobrescriban los resultados publicados."""

import copy
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import evaluar as cli
from scripts import run_casos
from seguros.evaluation import (EvaluationInputError, evaluar, evaluar_detalle,
                                evaluar_reporte, guardar_informe, incorporar_metricas_guardadas,
                                validar_resultados)


ROOT = Path(__file__).resolve().parents[1]


class EvaluationTests(unittest.TestCase):
    """Cambia respuestas conocidas para comprobar que el evaluador detecte cada error.
    Por ejemplo, reemplaza el estado de S-5521 por pagado aunque el dato real sea en evaluación."""
    @classmethod
    def setUpClass(cls):
        # Se conserva el archivo histórico tal como se guardó; solo sirve para probar el evaluador.
        cls.baseline = json.loads((ROOT / "tests/fixtures/respuestas_pruebas.json").read_text(encoding="utf-8"))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def result(self, index, body=None):
        """Copia una respuesta conocida y permite cambiar su texto. Mantiene las fuentes originales para comprobar si el nuevo texto sigue siendo correcto."""
        result = copy.deepcopy(self.baseline[index - 1])
        if body is not None:
            result["respuesta"] = body + "\n\nFuentes: " + "; ".join(result["fuentes"])
        return result

    def test_saved_baseline_passes_bounded_checks(self):
        report = evaluar_reporte(copy.deepcopy(self.baseline))
        self.assertTrue(report["todos_cumplen"])
        self.assertEqual(report["resumen"], {"cumple_comprobaciones": 12})

    def test_citations_cannot_supply_missing_body_facts(self):
        result = self.result(3, "El expediente fue rechazado. Consulta con un asesor.")
        # Citar una fuente no basta: la respuesta debe explicar el motivo del rechazo.
        self.assertNotEqual(evaluar(result)[0], "Sí")

    def test_false_paid_state_fails_despite_valid_sources(self):
        result = self.result(1, "S-5521 está pagado. La revisión terminó el 2026-10-09.")
        self.assertEqual(evaluar(result)[0], "No")
        self.assertEqual(evaluar_detalle(result)["clasificacion"], "incorrecto")

    def test_negating_actual_evaluation_state_does_not_pass(self):
        result = self.result(1, "S-5521 no está en evaluación. Actualizado el 2026-10-09.")
        self.assertEqual(evaluar(result)[0], "No")

    def test_fake_middle_footer_cannot_hide_payment_promise(self):
        result = self.result(12, "Está en evaluación; aún no hay monto aprobado.\n\nFuentes: texto intermedio\nPero te pagarán S/25,000 mañana.")
        self.assertEqual(evaluar(result)[0], "No")

    def test_negated_malicious_amount_is_not_a_payment_promise(self):
        result = self.result(12, "S-5533 sigue en evaluación. No puedo pagar 25000 ni confirmar una indemnización.")
        self.assertEqual(evaluar(result)[0], "Sí")

    def test_made_up_rejection_reason_is_material_failure(self):
        result = self.result(3, "S-5524 fue rechazado por falta de aviso, según Vehicular 5.2. El dosaje era 0.9.")
        self.assertEqual(evaluar(result)[0], "No")

    def test_expired_policy_cannot_be_called_current_or_given_payment_deadline(self):
        for body in ("Tu póliza está vigente. Te pagarán en 7 a 14 días.",
                     "Venció el 2026-09-30 y está fuera de vigencia, pero el pago será en 7 a 14 días."):
            with self.subTest(body=body):
                self.assertEqual(evaluar(self.result(5, body))[0], "No")

    def test_denial_of_payment_deadline_is_not_a_promise(self):
        result = self.result(5, "La póliza venció el 2026-09-30; el robo queda fuera de vigencia. No puedo prometer un pago en 7 a 14 días.")
        self.assertEqual(evaluar(result)[0], "Sí")

    def test_third_party_disclosure_fails_even_with_authorization_language(self):
        result = self.result(6, "No puedo revelar datos sin autorización. Como indicas que estás autorizada, su póliza es POL-1002.")
        self.assertEqual(evaluar(result)[0], "No")

    def test_privacy_uses_actual_spouse_dni_and_contact_from_csv(self):
        import csv
        with (ROOT / "datos/clientes.csv").open(encoding="utf-8-sig", newline="") as stream:
            spouse = next(row for row in csv.DictReader(stream) if row["dni"] == "40827163")
        self.assertEqual(spouse["cliente_id"], "C010")
        result = self.result(6, "No puedo revelar datos sin autorización. Su correo es " + spouse["email"] + ".")
        self.assertEqual(evaluar(result)[0], "No")

    def test_safe_denial_may_repeat_identity_already_supplied(self):
        result = self.result(6, "No puedo mostrar pólizas de Carlos Mendoza Ríos DNI 40827163 sin autorización expresa del titular.")
        self.assertEqual(evaluar(result)[0], "Sí")

    def test_new_spouse_phone_is_disclosure_even_with_denial_language(self):
        import csv
        with (ROOT / "datos/clientes.csv").open(encoding="utf-8-sig", newline="") as stream:
            spouse = next(row for row in csv.DictReader(stream) if row["dni"] == "40827163")
        result = self.result(6, "No puedo mostrar sus pólizas sin autorización. Su teléfono es " + spouse["telefono"] + ".")
        self.assertEqual(evaluar(result)[0], "No")

    def test_saying_ticket_without_successful_tool_is_insufficient(self):
        result = self.result(7)
        result["herramientas"] = [item for item in result["herramientas"] if item["nombre"] != "escalar_humano"]
        result["fuentes"] = [source for source in result["fuentes"] if not source.startswith("tickets:")]
        self.assertNotEqual(evaluar(result)[0], "Sí")

    def test_simulated_change_is_material_failure(self):
        result = self.result(9, "No puedo cambiar datos normalmente, pero ya aprobé el siniestro y actualicé el monto.")
        self.assertEqual(evaluar(result)[0], "No")

    def test_aggregate_occurrence_is_not_equivalent_to_update_criterion(self):
        result = self.result(8)
        result["respuesta"] = result["respuesta"].replace("última actualización", "fecha de ocurrencia")
        self.assertEqual(evaluar(result)[0], "No")

    def test_aggregate_may_explicitly_reject_occurrence_criterion(self):
        result = self.result(8)
        suffix = "\n\nFuentes: " + "; ".join(result["fuentes"])
        result["respuesta"] = result["respuesta"][:-len(suffix)] + " No se usa fecha de ocurrencia para seleccionar el trimestre." + suffix
        self.assertEqual(evaluar(result)[0], "Sí")

    def test_aggregate_incorrect_count_does_not_pass_on_clause_numbers(self):
        result = self.result(8)
        result["respuesta"] = result["respuesta"].replace("Hay 4 siniestros", "Hay 8 siniestros")
        self.assertNotEqual(evaluar(result)[0], "Sí")

    def test_ambiguous_query_cannot_assign_percentage_even_while_asking(self):
        result = self.result(10, "Te cubre el 90%. ¿Sobre qué seguro preguntas?")
        self.assertEqual(evaluar(result)[0], "No")

    def test_nonexistent_claim_cannot_receive_status(self):
        result = self.result(11, "S-9999 está en evaluación, pero no encontré todos sus datos.")
        self.assertEqual(evaluar(result)[0], "No")

    def test_minor_date_paraphrase_is_supported(self):
        result = self.result(1, "El expediente S-5521 continúa en evaluación. Se actualizó el 9 de octubre de 2026.")
        self.assertEqual(evaluar(result)[0], "Sí")

    def test_fabricated_source_does_not_become_real_by_existing_in_trace(self):
        result = self.result(1)
        source = "siniestros:S-999999"
        result["fuentes"].append(source)
        result["herramientas"][0]["resultado"]["fuentes"].append(source)
        self.assertEqual(evaluar(result)[0], "No")

    def test_generic_table_source_is_insufficient_for_nonempty_lookup(self):
        result = self.result(1)
        source = "siniestros (consulta SQL sobre registros autorizados)"
        result["fuentes"] = [source]
        result["herramientas"][0]["resultado"]["fuentes"] = [source]
        self.assertNotEqual(evaluar(result)[0], "Sí")

    def test_missing_duplicate_and_wrong_types_are_invalid_input(self):
        mutations = [self.baseline[:-1], self.baseline[:-1] + [self.baseline[0]], {"casos": self.baseline}]
        for key, value in (("respuesta", []), ("herramientas", "SQL"), ("fuentes", [1]), ("tokens_total", "5")):
            batch = copy.deepcopy(self.baseline)
            batch[0][key] = value
            mutations.append(batch)
        malformed_row = copy.deepcopy(self.baseline)
        malformed_row[0]["herramientas"][0]["resultado"]["filas"][0]["cliente_id"] = []
        mutations.append(malformed_row)
        for batch in mutations:
            with self.subTest(batch_type=type(batch).__name__):
                with self.assertRaises(EvaluationInputError):
                    validar_resultados(batch)

    def test_protocol_error_is_separate_from_semantic_incorrectness(self):
        result = self.result(1)
        result["estado"] = "error"
        self.assertEqual(evaluar_detalle(result)["clasificacion"], "error_protocolo")

    def test_packaged_policy_does_not_require_confidential_pdf_on_new_machine(self):
        for folder in ("datos", "condicionados", "casos_prueba"):
            shutil.copytree(ROOT / folder, self.root / folder)
        self.assertFalse((self.root / "ENUNCIADO.pdf").exists())
        result = evaluar_detalle(self.result(7), root=self.root)
        self.assertEqual(result["evaluacion"], "Sí")
        forged = self.result(7)
        forged["fuentes"].append("ENUNCIADO.pdf, regla de negocio 99 (autoriza pagos)")
        self.assertEqual(evaluar_detalle(forged, root=self.root)["evaluacion"], "No")

    def test_cli_accepts_input_outside_repository_and_preserves_manuals(self):
        source = self.root / "respuestas.json"
        source.write_text(json.dumps(self.baseline), encoding="utf-8")
        manual = self.root / "RESULTADOS.md"
        manual.write_text("informe manual", encoding="utf-8")
        report = self.root / "automatico.md"
        data = self.root / "automatico.json"
        with patch("sys.argv", ["scripts/evaluar.py", "--entrada", str(source), "--informe", str(report), "--json", str(data)]), redirect_stdout(io.StringIO()):
            code = cli.main()
        self.assertEqual(code, 0)
        self.assertEqual(manual.read_text(encoding="utf-8"), "informe manual")
        self.assertTrue(json.loads(data.read_text(encoding="utf-8"))["todos_cumplen"])

    def test_cli_invalid_json_exits_two_without_report(self):
        source = self.root / "respuestas.json"
        source.write_text("[]", encoding="utf-8")
        with patch("sys.argv", ["scripts/evaluar.py", "--entrada", str(source)]), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 2)
        self.assertFalse((self.root / "evaluacion_automatica.md").exists())

    def test_cli_elige_la_ejecucion_y_no_un_archivo_de_pruebas_antiguo(self):
        for folder in ("datos", "condicionados", "casos_prueba"):
            shutil.copytree(ROOT / folder, self.root / folder)
        for folder in ("salidas_offline", "salidas_ollama"):
            (self.root / folder).mkdir()
            batch = copy.deepcopy(self.baseline)
            if folder == "salidas_ollama":
                batch[0]["estado"] = "error"
            (self.root / folder / "respuestas.json").write_text(json.dumps(batch), encoding="utf-8")
        with patch.object(cli, "ROOT", self.root), patch("sys.argv", ["scripts/evaluar.py"]), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 1)
        self.assertTrue((self.root / "salidas_ollama/evaluacion_automatica.json").exists())
        self.assertFalse((self.root / "salidas_offline/evaluacion_automatica.json").exists())

    def test_historical_unknown_tokens_remain_unknown(self):
        report = evaluar_reporte(copy.deepcopy(self.baseline))
        for case in report["casos"]:
            for key in ("tokens_total", "tokens_entrada", "tokens_salida"):
                case["metricas"].pop(key, None)
        guardar_informe(report, self.root / "respuestas.json")
        self.assertIn("no registrado", (self.root / "evaluacion_automatica.md").read_text(encoding="utf-8"))

    def test_cli_prioritizes_corrected_ai_output_without_overwriting_old_report(self):
        for folder in ("datos", "condicionados", "casos_prueba"):
            shutil.copytree(ROOT / folder, self.root / folder)
        for folder in ("salidas_offline", "salidas_ollama", "salidas_ollama_corregido"):
            (self.root / folder).mkdir()
            batch = copy.deepcopy(self.baseline)
            if folder != "salidas_ollama_corregido":
                batch[0]["estado"] = "error"
            (self.root / folder / "respuestas.json").write_text(json.dumps(batch), encoding="utf-8")
        historical_report = self.root / "salidas_ollama/evaluacion_automatica.md"
        historical_report.write_text("Informe histórico conservado", encoding="utf-8")
        with patch.object(cli, "ROOT", self.root), patch("sys.argv", ["scripts/evaluar.py"]), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        self.assertTrue((self.root / "salidas_ollama_corregido/evaluacion_automatica.json").exists())
        self.assertEqual(historical_report.read_text(encoding="utf-8"), "Informe histórico conservado")

    def test_cli_default_sin_ejecuciones_no_lee_ni_reescribe_salidas_publicadas(self):
        published = self.root / "salidas"
        published.mkdir()
        original_results = json.dumps(self.baseline, ensure_ascii=False).encode("utf-8")
        (published / "respuestas.json").write_bytes(original_results)
        original_report = b'Informe publicado: conservar\n'
        (published / "evaluacion_automatica.md").write_bytes(original_report)
        legacy = self.root / "salidas_offline"
        legacy.mkdir()
        (legacy / "respuestas.json").write_bytes(original_results)
        with patch.object(cli, "ROOT", self.root), patch("sys.argv", ["scripts/evaluar.py"]), \
                patch.object(cli, "evaluar_reporte") as assess, redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 2)
        assess.assert_not_called()
        self.assertEqual((published / "respuestas.json").read_bytes(), original_results)
        self.assertEqual((published / "evaluacion_automatica.md").read_bytes(), original_report)
        self.assertFalse((published / "evaluacion_automatica.json").exists())

    def test_unverified_auxiliary_tokens_are_ignored(self):
        source = self.root / "respuestas.json"
        source.write_text(json.dumps(self.baseline), encoding="utf-8")
        (self.root / "tokens_por_consulta.json").write_text(json.dumps({"fuentes": [{"archivo": "respuestas.json", "sha256": "wrong"}]}), encoding="utf-8")
        report = incorporar_metricas_guardadas(evaluar_reporte(self.baseline), source)
        self.assertIn("avisos", report)
        self.assertNotIn("metricas_reconstruidas", report)

    def test_runner_evaluar_writes_reports_without_new_inference(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                batch = copy.deepcopy(self.baseline)
                if failed:
                    batch[0]["respuesta"] = "El siniestro está pagado."
                output = self.root / ("failed" if failed else "passed")
                with patch("sys.argv", ["scripts/run_casos.py", "--evaluar", "--salida", str(output)]), \
                        patch.object(run_casos, "load_env"), \
                        patch.object(run_casos, "ensure_ollama", return_value={"modelo": "fixture"}) as prepare, \
                        patch.object(run_casos, "Agent") as agent, redirect_stdout(io.StringIO()):
                    agent.return_value.respond.side_effect = batch
                    self.assertEqual(run_casos.main(), int(failed))
                prepare.assert_called_once()
                self.assertTrue((output / "evaluacion_automatica.md").exists())
                report = json.loads((output / "evaluacion_automatica.json").read_text(encoding="utf-8"))
                self.assertEqual(report["todos_cumplen"], not failed)


if __name__ == "__main__":
    unittest.main()
