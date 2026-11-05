"""Acceso autorizado y de solo lectura a datos y condiciones.

Comprueba SQL permitido, aislamiento entre clientes y registro de tickets en archivos temporales."""

import json
import tempfile
import unittest
from pathlib import Path

from seguros.tools import ROOT, Tools


class ToolsTests(unittest.TestCase):
    """Fronteras de permisos, lectura y búsqueda en las herramientas."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.tools = Tools(output_dir=Path(self.temporary.name))
        self.client = {"rol": "cliente", "usuario_id": "C001"}
        self.advisor = {"rol": "asesor", "usuario_id": "ASE01"}

    def query(self, sql, session=None, **arguments):
        """Consulta como una sesión concreta para comprobar sus permisos."""
        return self.tools.call("consulta_datos", {"sql": sql, **arguments}, session or self.client)

    def test_customer_scope_survives_join_and_or(self):
        result = self.query("SELECT c.cliente_id, p.cliente_id AS titular, s.siniestro_id FROM clientes c JOIN polizas p ON c.cliente_id=p.cliente_id JOIN siniestros s ON s.poliza_id=p.poliza_id WHERE 1=1 OR c.cliente_id='C002'")
        self.assertTrue(result["filas"])
        self.assertEqual({r["titular"] for r in result["filas"]}, {"C001"})
        self.assertIn("siniestros:S-5521", result["fuentes"])

    def test_unknown_claim_and_foreign_claim_both_empty(self):
        for identifier in ("S-5524", "S-9999"):
            self.assertEqual(self.query("SELECT * FROM siniestros WHERE siniestro_id=?", parametros=[identifier])["filas"], [])

    def test_no_schema_writes_pragmas_attachments_or_dangerous_functions(self):
        statements = ["DELETE FROM polizas", "UPDATE siniestros SET monto_aprobado_soles=15000", "CREATE TABLE hacked(x)", "PRAGMA table_info(clientes)", "ATTACH DATABASE ':memory:' AS other", "SELECT name FROM sqlite_master", "SELECT load_extension('anything')", "SELECT * FROM clientes; SELECT * FROM polizas", "SELECT randomblob(1000000000)"]
        for statement in statements:
            with self.subTest(sql=statement):
                self.assertIn("error", self.query(statement, self.advisor))

    def test_advisor_can_aggregate_all_clients(self):
        self.assertEqual(self.query("SELECT COUNT(*) AS total FROM clientes", self.advisor)["filas"], [{"total": 40}])
        self.assertEqual(self.query("SELECT COUNT(*) AS total FROM clientes")["filas"], [{"total": 1}])
        citations = self.query("SELECT group_concat(siniestro_id) AS registros FROM siniestros WHERE siniestro_id IN ('S-5521','S-5524')", self.advisor)["fuentes"]
        self.assertIn("siniestros:S-5521", citations)
        self.assertIn("siniestros:S-5524", citations)

    def test_nulls_and_numeric_types(self):
        row = self.query("SELECT monto_reclamado_soles,monto_aprobado_soles FROM siniestros WHERE siniestro_id='S-5521'")["filas"][0]
        self.assertEqual(row["monto_reclamado_soles"], 6800)
        self.assertIsNone(row["monto_aprobado_soles"])

    def test_no_session_override_or_invalid_identity(self):
        self.assertIn("error", self.query("SELECT * FROM clientes", usuario_id="C002"))
        for session in ({"rol": "asesor", "usuario_id": "C001"}, {"rol": "supervisor", "usuario_id": "C007"}, {"rol": "cliente", "usuario_id": "C999"}):
            self.assertIn("error", self.tools.call("buscar_condicionados", {"consulta": "salud"}, session))

    def test_keyword_search_returns_real_article_and_hierarchy(self):
        result = self.tools.call("buscar_condicionados", {"consulta": "vesícula cirugías programadas carencia", "ramo": "salud"}, self.client)
        self.assertTrue(any(f["articulo"] == "4" and f["documento"].endswith("salud.md") for f in result["fragmentos"]))
        self.assertTrue(any(f["articulo"] == "1" and f["documento"].endswith("condiciones_generales.md") for f in result["fragmentos"]))
        self.assertFalse(any(f["documento"].endswith("vehicular.md") for f in result["fragmentos"]))

    def test_no_match_does_not_invent_article(self):
        self.assertEqual(self.tools.call("buscar_condicionados", {"consulta": "xyzzyplugh"}, self.client)["fragmentos"], [])

    def test_general_article_search_has_no_irrelevant_documents(self):
        result = self.tools.call("buscar_condicionados", {"consulta": "estados siniestro articulo 5", "ramo": "general"}, self.client)
        self.assertEqual([(f["documento"], f["articulo"]) for f in result["fragmentos"]], [("condicionados/condiciones_generales.md", "5")])

    def test_prefixed_clause_filters_document_and_article(self):
        for query, expected in (("Vehicular 5.2 ebriedad", ("vehicular.md", "5")), ("Condiciones Generales 6.3 suspensión", ("condiciones_generales.md", "6")), ("Salud Art. 4.2 carencia", ("salud.md", "4"))):
            with self.subTest(query=query):
                result = self.tools.call("buscar_condicionados", {"consulta": query}, self.client)
                fragments = result["fragmentos"]
                self.assertEqual((Path(fragments[0]["documento"]).name, fragments[0]["articulo"]), expected)
                self.assertTrue(all(f is fragments[0] or (f["documento"].endswith("condiciones_generales.md") and f["articulo"] == "1") for f in fragments))

    def test_time_values_are_not_treated_as_article_numbers(self):
        result = self.tools.call("buscar_condicionados", {"consulta": "aviso vehicular 72 horas", "ramo": "vehicular"}, self.client)
        self.assertTrue(any(f["articulo"] == "3" and f["documento"].endswith("vehicular.md") for f in result["fragmentos"]))
        self.assertLessEqual(len(result["fragmentos"]), 4)

    def test_escalation_is_local_and_uses_session(self):
        result = self.tools.call("escalar_humano", {"motivo": "Consulta de inversión", "detalle": "Solicita orientación autorizada."}, self.client)
        record = json.loads((Path(self.temporary.name) / "tickets.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(record["usuario_id"], "C001")
        self.assertEqual(record["ticket_id"], result["ticket_id"])
        self.assertEqual(record["estado"], "pendiente")

    def test_original_data_unchanged(self):
        original = (ROOT / "datos" / "siniestros.csv").read_bytes()
        self.query("UPDATE siniestros SET estado='aprobado'")
        self.assertEqual((ROOT / "datos" / "siniestros.csv").read_bytes(), original)

    def test_row_limit_and_execution_budget(self):
        result = self.query("SELECT p.poliza_id,s.siniestro_id FROM polizas p CROSS JOIN siniestros s", self.advisor)
        self.assertEqual(len(result["filas"]), 200)
        self.assertTrue(result["truncado"])
        expensive = "SELECT COUNT(*) FROM siniestros a CROSS JOIN siniestros b CROSS JOIN siniestros c CROSS JOIN siniestros d"
        self.assertIn("error", self.query(expensive, self.advisor))

    def test_argument_limits(self):
        self.assertIn("error", self.query("SELECT 1", parametros=[1] * 101))
        self.assertIn("error", self.query("SELECT 1", parametros=[{}]))
        self.assertIn("error", self.query(" " * 12001))
        self.assertIn("error", self.tools.call("buscar_condicionados", {"consulta": "x" * 4001}, self.client))

    def test_string_format_allocation_is_not_allowed(self):
        for sql in ("SELECT printf('%100000s','x')", "SELECT format('%100000s','x')"):
            self.assertIn("error", self.query(sql))

    def test_model_mode_denies_free_text_by_actual_column_origin(self):
        safe = Tools(output_dir=Path(self.temporary.name), safe_model=True)
        statements = [
            "SELECT descripcion AS resumen FROM siniestros",
            "SELECT substr(descripcion,1,20) AS resumen FROM siniestros",
            "SELECT descripcion || ' adicional' AS resumen FROM siniestros",
            "WITH datos AS (SELECT * FROM siniestros) SELECT descripcion AS resumen FROM datos",
            "SELECT COUNT(*) FROM siniestros WHERE descripcion LIKE '%sistema%'",
            "SELECT motivo_rechazo AS clausula FROM siniestros",
            "SELECT * FROM siniestros",
        ]
        for sql in statements:
            with self.subTest(sql=sql):
                self.assertIn("error", safe.call("consulta_datos", {"sql": sql}, self.advisor))
        sql = "SELECT siniestro_id,estado,clausula_referencia FROM siniestros WHERE siniestro_id='S-5524'"
        self.assertTrue(safe.call("consulta_datos", {"sql": sql}, self.advisor)["filas"])

    def test_offline_mode_preserves_original_narrative_evidence(self):
        sql = "SELECT descripcion,motivo_rechazo FROM siniestros WHERE siniestro_id='S-5524'"
        row = self.query(sql, self.advisor)["filas"][0]
        self.assertTrue(row["descripcion"])
        self.assertTrue(row["motivo_rechazo"])


if __name__ == "__main__":
    unittest.main()
