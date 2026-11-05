"""Permite buscar datos, leer condiciones y guardar solicitudes de atención. Antes de
buscar, limita los registros según el rol y código de usuario elegidos. Esa
comprobación de la demostración no verifica quién es realmente la persona.
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
    """Prepara el texto para buscar sin importar mayúsculas o tildes. No cambia los
    documentos originales.
    """
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


class DataStore:
    """Lee los CSV y permite consultar solo los registros que corresponden al usuario.
    Cada búsqueda usa una copia en memoria y nunca cambia los archivos originales.
    """

    def __init__(self, root: Path, safe_model: bool = False):
        """Recibe la carpeta del proyecto y lee los CSV. Una opción adicional permite
        bloquear textos como la descripción del siniestro cuando hace falta.
        """
        self.safe_model = safe_model
        self.tables = {}
        self.headers = {}
        for name in (*TABLE_KEYS, "asesores"):
            with (root / "datos" / f"{name}.csv").open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                self.headers[name] = list(reader.fieldnames or [])
                self.tables[name] = list(reader)

    def validate_session(self, session: dict) -> None:
        """Recibe el rol y el código de usuario elegidos en la sesión. Busca ese código
        en el archivo de clientes o de asesores y permite continuar solo si
        corresponde al rol indicado. Si no coincide, detiene la consulta con un
        error. Esto no pide contraseña ni demuestra que quien escribe sea realmente
        esa persona.
        """
        if not isinstance(session, dict):
            raise ValueError("La sesión autenticada es obligatoria.")
        role, user = session.get("rol"), session.get("usuario_id")
        if role not in ("cliente", "asesor"):
            raise ValueError("Rol de sesión no autorizado.")
        table, key = ("clientes", "cliente_id") if role == "cliente" else ("asesores", "asesor_id")
        if not isinstance(user, str) or not any(row[key] == user for row in self.tables[table]):
            raise ValueError("Identidad de sesión no reconocida.")

    def visible_tables(self, session: dict) -> dict:
        """Recibe el usuario que consulta y prepara tres listas: clientes, pólizas y
        siniestros permitidos. Para un cliente, primero busca sus pólizas y luego los
        siniestros que pertenecen a esas pólizas. Ejemplo con los archivos del
        proyecto: para C001 puede seleccionar POL-1001 y, por esa póliza, S-5521; los
        registros de otros clientes quedan fuera. Solo esas listas se ponen a
        disposición de la búsqueda de datos. Un asesor tiene el acceso que
        corresponde a su rol registrado. Devuelve las listas sin cambiar los CSV.
        """
        self.validate_session(session)
        if session["rol"] == "asesor":
            return {table: self.tables[table] for table in TABLE_KEYS}
        clients = [r for r in self.tables["clientes"] if r["cliente_id"] == session["usuario_id"]]
        policies = [r for r in self.tables["polizas"] if r["cliente_id"] == session["usuario_id"]]
        policy_ids = {r["poliza_id"] for r in policies}
        claims = [r for r in self.tables["siniestros"] if r["poliza_id"] in policy_ids]
        return {"clientes": clients, "polizas": policies, "siniestros": claims}

    def query(self, sql: str, parameters: list, session: dict) -> dict:
        """Recibe una búsqueda de datos escrita en SQL, sus valores y el usuario que
        consulta. Primero obtiene solo los registros permitidos para ese usuario y
        los pone en una copia en memoria para buscar allí. Por ejemplo, con C001
        puede buscar S-5521, pero no obtiene datos de otro cliente por conocer su
        código. Bloquea cambios y limita el trabajo y la cantidad de resultados para
        que la búsqueda no se prolongue sin control. Devuelve lo encontrado, de dónde
        salió y un aviso si había más resultados de los que podía mostrar; los CSV
        originales no cambian.
        """
        visible = self.visible_tables(session)
        if not isinstance(sql, str) or not sql.strip() or len(sql) > 12000:
            raise ValueError("Proporciona una consulta SQL de lectura de hasta 12000 caracteres.")
        if not isinstance(parameters, list) or len(parameters) > 100:
            raise ValueError("parametros debe ser una lista de hasta 100 valores.")
        if any(value is not None and not isinstance(value, (str, int, float)) for value in parameters):
            raise ValueError("Los parámetros SQL deben ser valores simples.")
        used_tables = set()
        with closing(sqlite3.connect(":memory:")) as connection:
            # Python 3.11 permite poner límites extra al buscador de datos.
            # En Python 3.10 se mantienen las demás protecciones de abajo.
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
                # Al contar filas, la base de datos puede no indicar su nombre.
                if action == sqlite3.SQLITE_READ and first in TABLE_KEYS and database in ("main", None):
                    # Revisa el nombre real de la columna, aunque la consulta le ponga otro.
                    # Así se impide sacar textos como la descripción con otro nombre,
                    # uniéndolos a otros textos o escondiéndolos dentro de otra consulta.
                    if self.safe_model and first == "siniestros" and second in {"descripcion", "motivo_rechazo"}:
                        return sqlite3.SQLITE_DENY
                    used_tables.add(first)
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_FUNCTION and (second or "").lower() in safe_functions:
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY

            connection.set_authorizer(authorize)
            # Mostrar pocas filas no basta si buscarlas toma demasiado trabajo.
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
    """Ofrece tres acciones: buscar datos, buscar condiciones y guardar un ticket local.
    No aprueba pagos ni envía mensajes a personas o servicios externos.
    """

    def __init__(self, root: Path | None = None, output_dir: Path | None = None, safe_model: bool = False):
        """Recibe las carpetas de trabajo y lee los datos y artículos disponibles. No
        cambia los documentos ni los envía a Qwen.
        """
        self.root = Path(root) if root is not None else ROOT
        self.output_dir = Path(output_dir) if output_dir is not None else self.root / "salidas_ollama_corregido"
        self.data = DataStore(self.root, safe_model=safe_model)
        self.fragments = []
        for path in sorted((self.root / "condicionados").glob("*.md")):
            text = path.read_text(encoding="utf-8-sig")
            for match in re.finditer(r"^## Artículo (\d+)\. ([^\n]+)\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL):
                self.fragments.append({"documento": f"condicionados/{path.name}", "articulo": match[1], "texto": f"Artículo {match[1]}. {match[2]}\n{match[3].strip()}"})

    def call(self, name: str, arguments: dict, session: dict) -> dict:
        """Recibe el nombre de la herramienta, los datos que necesita y el usuario que
        consulta. Comprueba el usuario y permite solo buscar datos, buscar
        condiciones o guardar un ticket. Por ejemplo, consulta_datos busca los
        registros permitidos y buscar_condicionados trae los artículos del seguro.
        Devuelve el resultado o un error para que el programa guarde qué ocurrió; no
        permite agregar herramientas desde la pregunta.
        """
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
        """Devuelve si el rol y el código de usuario están registrados. Esto no es una
        verificación de identidad real para atender clientes.
        """
        try:
            self.data.validate_session(session)
            return True
        except ValueError:
            return False

    def search(self, query: str, branch: str | None = None) -> dict:
        """Busca artículos del seguro pedido y devuelve su texto y de dónde salió. Da
        prioridad a las condiciones específicas del seguro sin inventar reglas.
        """
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError("La búsqueda requiere texto de hasta 4000 caracteres.")
        if branch not in (None, "general", "vehicular", "salud", "vida"):
            raise ValueError("Ramo no reconocido.")
        normalized_query = normalize(query)
        # Solo elige un artículo si se escribe 'artículo' o una cláusula.
        # Números como '6 meses' o '72 horas' no eligen un artículo.
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
        """Recibe el motivo de la consulta, una explicación y el usuario. Guarda esos
        datos en un archivo local y crea un número de ticket para poder encontrarlo
        después. Devuelve ese número y un aviso claro: todavía no se ha enviado a
        ningún asesor ni servicio externo.
        """
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
