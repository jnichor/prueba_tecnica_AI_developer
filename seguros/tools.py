"""Herramientas con identidad externa y acceso de solo lectura a datos originales.

DataStore concentra SQL, carga y autorización de datos. Es el punto de sustitución
por un adaptador BigQuery; el agente solamente utiliza Tools.call.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TABLE_KEYS = {"clientes": "cliente_id", "polizas": "poliza_id", "siniestros": "siniestro_id"}
_APPEND_LOCK = threading.Lock()


def normalize(text: str) -> str:
    """Normalización de búsqueda; conserva intactos los documentos originales."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


class DataStore:
    """Una conexión efímera solo contiene las filas visibles para su sesión."""

    def __init__(self, root: Path, safe_model: bool = False):
        self.safe_model = safe_model
        self.tables = {}
        self.headers = {}
        for name in (*TABLE_KEYS, "asesores"):
            with (root / "datos" / f"{name}.csv").open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                self.headers[name] = list(reader.fieldnames or [])
                self.tables[name] = list(reader)

    def validate_session(self, session: dict) -> None:
        if not isinstance(session, dict):
            raise ValueError("La sesión autenticada es obligatoria.")
        role, user = session.get("rol"), session.get("usuario_id")
        if role not in ("cliente", "asesor"):
            raise ValueError("Rol de sesión no autorizado.")
        table, key = ("clientes", "cliente_id") if role == "cliente" else ("asesores", "asesor_id")
        if not isinstance(user, str) or not any(row[key] == user for row in self.tables[table]):
            raise ValueError("Identidad de sesión no reconocida.")

    def visible_tables(self, session: dict) -> dict:
        self.validate_session(session)
        if session["rol"] == "asesor":
            return {table: self.tables[table] for table in TABLE_KEYS}
        clients = [r for r in self.tables["clientes"] if r["cliente_id"] == session["usuario_id"]]
        policies = [r for r in self.tables["polizas"] if r["cliente_id"] == session["usuario_id"]]
        policy_ids = {r["poliza_id"] for r in policies}
        claims = [r for r in self.tables["siniestros"] if r["poliza_id"] in policy_ids]
        return {"clientes": clients, "polizas": policies, "siniestros": claims}

    def query(self, sql: str, parameters: list, session: dict) -> dict:
        visible = self.visible_tables(session)
        if not isinstance(sql, str) or not sql.strip() or len(sql) > 12000:
            raise ValueError("Proporciona una consulta SQL de lectura de hasta 12000 caracteres.")
        if not isinstance(parameters, list) or len(parameters) > 100:
            raise ValueError("parametros debe ser una lista de hasta 100 valores.")
        if any(value is not None and not isinstance(value, (str, int, float)) for value in parameters):
            raise ValueError("Los parámetros SQL deben ser valores simples.")
        used_tables = set()
        with closing(sqlite3.connect(":memory:")) as connection:
            # Python 3.11+ exposes SQLite's native allocation limits. Python 3.10
            # still has the SQL length, function allowlist and VM budget below.
            if hasattr(connection, "setlimit"):
                connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
                connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 12_000)
                connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 100)
            connection.row_factory = sqlite3.Row
            connection.enable_load_extension(False)
            for table in TABLE_KEYS:
                headers = self.headers[table]
                declarations = ", ".join(f'"{key}" {"REAL" if key.endswith("_soles") else "TEXT"}' for key in headers)
                connection.execute(f'CREATE TABLE "{table}" ({declarations})')
                values = []
                for row in visible[table]:
                    values.append(tuple(None if row[key] == "" else float(row[key]) if key.endswith("_soles") else row[key] for key in headers))
                connection.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in headers)})', values)
            connection.commit()
            connection.execute("PRAGMA query_only = ON")

            safe_functions = {
                "count", "sum", "avg", "min", "max", "coalesce", "ifnull", "nullif", "round", "abs",
                "lower", "upper", "length", "substr", "substring", "trim", "ltrim", "rtrim", "replace",
                "date", "datetime", "strftime", "julianday", "unixepoch", "like", "glob", "instr",
                "total", "group_concat", "typeof", "iif",
            }

            def authorize(action, first, second, database, trigger):
                if action == sqlite3.SQLITE_SELECT:
                    return sqlite3.SQLITE_OK
                # SQLite reports database=None for COUNT(*)'s empty-column read.
                if action == sqlite3.SQLITE_READ and first in TABLE_KEYS and database in ("main", None):
                    # Check original column provenance, not the SQL alias. This
                    # also blocks CTEs, concatenation, predicates and functions
                    # which try to launder untrusted narrative text to the LLM.
                    if self.safe_model and first == "siniestros" and second in {"descripcion", "motivo_rechazo"}:
                        return sqlite3.SQLITE_DENY
                    used_tables.add(first)
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_FUNCTION and (second or "").lower() in safe_functions:
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY

            connection.set_authorizer(authorize)
            # A row limit alone does not bound expensive joins or recursive queries.
            budget = [0]

            def progress():
                budget[0] += 1
                return int(budget[0] > 2000)

            connection.set_progress_handler(progress, 1000)
            cursor = connection.execute(sql, parameters)
            rows = cursor.fetchmany(201)
            truncated = len(rows) > 200
            rows = [dict(row) for row in rows[:200]]

        sources = []
        identifiers = {
            identifier
            for row in rows
            for value in row.values()
            if isinstance(value, str)
            for identifier in re.findall(r"\b(?:C\d{3}|POL-\d+|S-\d+)\b", value)
        }
        for table in sorted(used_tables):
            matched = [row[TABLE_KEYS[table]] for row in visible[table] if row[TABLE_KEYS[table]] in identifiers]
            sources.extend(f"{table}:{identifier}" for identifier in matched)
            if not matched:
                sources.append(f"{table} (consulta SQL sobre registros autorizados)")
        return {"filas": rows, "fuentes": sources, "truncado": truncated, "datos_no_confiables": True}


class Tools:
    """Las herramientas no aceptan cambios de rol o identidad desde argumentos."""

    def __init__(self, root: Path | None = None, output_dir: Path | None = None, safe_model: bool = False):
        self.root = Path(root) if root is not None else ROOT
        self.output_dir = Path(output_dir) if output_dir is not None else self.root / "salidas"
        self.data = DataStore(self.root, safe_model=safe_model)
        self.fragments = []
        for path in sorted((self.root / "condicionados").glob("*.md")):
            text = path.read_text(encoding="utf-8-sig")
            for match in re.finditer(r"^## Artículo (\d+)\. ([^\n]+)\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL):
                self.fragments.append({"documento": f"condicionados/{path.name}", "articulo": match[1], "texto": f"Artículo {match[1]}. {match[2]}\n{match[3].strip()}"})

    def call(self, name: str, arguments: dict, session: dict) -> dict:
        try:
            self.data.validate_session(session)
            if not isinstance(arguments, dict):
                raise ValueError("Los argumentos deben ser un objeto.")
            allowed = {"consulta_datos": {"sql", "parametros"}, "buscar_condicionados": {"consulta", "ramo"}, "escalar_humano": {"motivo", "detalle"}}
            if name not in allowed:
                raise ValueError("Herramienta no disponible.")
            if set(arguments) - allowed[name]:
                raise ValueError("La herramienta recibió argumentos no permitidos.")
            if name == "consulta_datos":
                return self.data.query(arguments.get("sql"), arguments.get("parametros", []), session)
            if name == "buscar_condicionados":
                return self.search(arguments.get("consulta"), arguments.get("ramo"))
            return self.escalate(arguments.get("motivo"), arguments.get("detalle", ""), session)
        except ValueError as error:
            return {"error": str(error), "fuentes": []}
        except sqlite3.Error:
            return {"error": "Consulta no permitida o SQL inválido. Usa SELECT sobre clientes, polizas o siniestros y solo funciones de lectura autorizadas. En modo modelo, descripcion y motivo_rechazo no están disponibles: selecciona columnas estructuradas explícitas y usa clausula_referencia con el condicionado.", "fuentes": []}
        except OSError:
            return {"error": "No se pudo registrar el ticket local. No se confirma el escalamiento.", "fuentes": []}

    def validate_session(self, session: dict) -> bool:
        """Valida contexto externo sin inferir identidad desde el mensaje."""
        try:
            self.data.validate_session(session)
            return True
        except ValueError:
            return False

    def search(self, query: str, branch: str | None = None) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError("La búsqueda requiere texto de hasta 4000 caracteres.")
        if branch not in (None, "general", "vehicular", "salud", "vida"):
            raise ValueError("Ramo no reconocido.")
        normalized_query = normalize(query)
        # Only explicit article markers or prefixed clause references count as
        # article selectors. Ordinary '6 meses' / '72 horas' remain keywords.
        article_numbers = set(re.findall(r"\b(?:articulo|art\.?)\s+(\d+)\b", normalized_query))
        references = set()
        for match in re.finditer(r"\b(vehicular|salud|vida|condiciones\s+generales)[\s,:-]*(?:(?:articulo|art\.?|clausula)\s*)?(\d+)\.\d+\b", normalized_query):
            document = "condiciones_generales" if match[1].startswith("condiciones") else match[1]
            references.add((document, match[2]))
        stopwords = {"de", "la", "el", "los", "las", "un", "una", "y", "o", "en", "por", "para", "que", "mi", "me", "se", "del", "al", "con", "es", "a", "su", "si", "seguro", "articulo", "condiciones"}
        words = set(re.findall(r"[a-z]+", normalized_query)) - stopwords
        candidates = []
        for fragment in self.fragments:
            file_branch = Path(fragment["documento"]).stem
            if references:
                if (file_branch, fragment["articulo"]) not in references:
                    continue
            elif article_numbers:
                if fragment["articulo"] not in article_numbers:
                    continue
                selected_document = "condiciones_generales" if branch == "general" else branch
                if selected_document and file_branch != selected_document:
                    continue
            elif branch == "general" and file_branch != "condiciones_generales":
                continue
            elif branch and branch != "general" and file_branch not in (branch, "condiciones_generales"):
                continue
            text = normalize(fragment["texto"])
            tokens = set(re.findall(r"[a-z]+", text))
            score = len(words & tokens)
            if references or article_numbers:
                score += 10
            if score:
                candidates.append((score, file_branch != "condiciones_generales", fragment))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        fragments = [dict(item[2]) for item in candidates[:4]]
        if any(not fragment["documento"].endswith("condiciones_generales.md") for fragment in fragments):
            hierarchy = next(f for f in self.fragments if f["documento"].endswith("condiciones_generales.md") and f["articulo"] == "1")
            if hierarchy not in fragments:
                fragments = fragments[:3]
                fragments.append(dict(hierarchy))
        return {"fragmentos": fragments, "fuentes": [f'{f["documento"]}, Artículo {f["articulo"]}' for f in fragments], "datos_no_confiables": True}

    def escalate(self, reason: str, detail: str, session: dict) -> dict:
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ValueError("El motivo debe contener entre 1 y 1000 caracteres.")
        if not isinstance(detail, str) or len(detail) > 4000:
            raise ValueError("El detalle debe ser texto de hasta 4000 caracteres.")
        ticket_id = "T-" + uuid.uuid4().hex[:12].upper()
        record = {"ticket_id": ticket_id, "creado_en": datetime.now(timezone.utc).isoformat(), "rol": session["rol"], "usuario_id": session["usuario_id"], "motivo": reason, "detalle": detail, "estado": "pendiente"}
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with _APPEND_LOCK, (self.output_dir / "tickets.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"ticket_id": ticket_id, "estado": "pendiente", "aviso": "Ticket registrado localmente; no se ha enviado a un servicio externo.", "fuentes": [f"tickets:{ticket_id}"]}
