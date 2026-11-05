"""Busca los datos y condiciones que hacen falta y escribe la respuesta con sus fuentes.
Recibe lo que se quiere consultar después de revisar la interpretación de Qwen. No
manda expedientes ni artículos al modelo.
"""

import calendar
import re
from collections import Counter
from datetime import date, timedelta

from .tools import normalize
from .planning import (literal_ids, literal_quarters, literal_years, general_help_request,
                       general_coverage_request, own_policy_request,
                       requests_third_party_data, self_claim_history_request,
                       supported_branches, supported_events)


PRIVACY = "ENUNCIADO.pdf, reglas de negocio 2 y 3 (identidad y privacidad)"
NO_INVENT = "ENUNCIADO.pdf, regla de negocio 5 (sin inventar)"
NO_ADVICE = "ENUNCIADO.pdf, regla de negocio 7 (sin asesoría indebida)"


def add_months(value, months):
    year, month = divmod(value.year * 12 + value.month - 1 + months, 12)
    return date(year, month + 1, min(value.day, calendar.monthrange(year, month + 1)[1]))


def clean(text):
    return str(text).replace("**", "").strip()


class Resolver:
    """Es la parte que construye la respuesta con datos comprobados. Usa la fecha del
    ejercicio y las herramientas de búsqueda, sin decidir indemnizaciones.
    """
    def __init__(self, today, call):
        self.today = today
        self.call = call
        self.policy_sources = []

    def _sql(self, sql, session, parameters=None):
        """Pide datos a la herramienta de búsqueda usando el usuario de la consulta.
        Devuelve lo encontrado y sus fuentes; la herramienta controla qué registros
        puede ver.
        """
        return self.call("consulta_datos", {"sql": sql, "parametros": parameters or []}, session)

    def _article(self, branch, number, session):
        """Busca un artículo del seguro y comprueba que sea el documento pedido.
        Devuelve su texto y su fuente, o indica que no lo encontró.
        """
        result = self.call("buscar_condicionados", {"consulta": f"articulo {number}", "ramo": branch}, session)
        document = "condiciones_generales" if branch == "general" else branch
        expected = f"condicionados/{document}.md"
        for fragment in result.get("fragmentos", []):
            if fragment.get("documento") == expected and str(fragment.get("articulo")) == str(number):
                source = f"{expected}, Artículo {number}"
                if source in result.get("fuentes", []) and isinstance(fragment.get("texto"), str):
                    return fragment["texto"], source
        return None, None

    @staticmethod
    def _clause(text, number):
        """Busca una cláusula por su número y quita marcas de formato. Si el texto
        parece dar órdenes al programa, no lo usa como condición del seguro.
        """
        match = re.search(rf"(?m)^{re.escape(str(number))}\.\s+(.+)$", text or "")
        if not match or re.search(r"\b(ignora|instrucciones|system|assistant|prompt|promete|aprueba)\b", normalize(match[1])):
            return None
        return clean(match[1])

    def _escalate(self, message, session, reason="Información insuficiente o inconsistente"):
        """Guarda una solicitud de atención en un ticket local. Devuelve el número o
        avisa que falló; no envía un aviso automático a un asesor.
        """
        self.policy_sources = list(dict.fromkeys([*self.policy_sources, NO_INVENT]))
        ticket = self.call("escalar_humano", {"motivo": reason, "detalle": message[:4000]}, session)
        if ticket.get("error") or not ticket.get("ticket_id"):
            return message + " No se pudo registrar el ticket; contacta por un canal de atención."
        return message + f" Registré el ticket local {ticket['ticket_id']}, pendiente de atención; no implica contacto automático."

    def _advice(self, message, session):
        """Identifica si se está pidiendo consejo financiero, médico o legal. Explica el
        límite y registra una solicitud para que la revise un profesional.
        """
        text = normalize(message)
        medical = any(word in text for word in ("operarme", "medicamento", "tratamiento", "diagnostic", "asesoria medica"))
        legal = any(word in text for word in ("legal", "juridic", "demandar", "demando", "abogado"))
        kind = "médica" if medical else "legal" if legal else "financiera o de inversión" if any(word in text for word in ("inver", "ahorro", "fondo mutuo", "financier")) else "profesional"
        self.policy_sources = [NO_ADVICE]
        self._article("general", "10", session)
        if kind == "financiera o de inversión":
            self._article("vida", "2", session)
        return self._escalate(f"No puedo brindarte asesoría {kind}. Debe atenderte un profesional autorizado para ese tema.", session, "Asesoría " + kind)

    def guard(self, message, session):
        """Revisa pedidos de cambios, consejos y datos ajenos antes de llamar a Qwen. Si
        debe detener alguno, devuelve la respuesta correspondiente; si no, permite
        continuar.
        """
        self.policy_sources = []
        text = normalize(message)
        if re.search(r"\b(aprueba|aprobar|rechaza|actualiza|modifica|elimina|borra)\b", text):
            self._article("general", "5", session)
            self.policy_sources = [PRIVACY]
            return ("No puedo aprobar, rechazar ni modificar pólizas, siniestros o montos. "
                    "El rol de tu sesión autenticada no cambia por declarar otro cargo. "
                    "Este canal solo consulta información; la decisión corresponde a Evaluación de Siniestros.")
        medical = any(word in text for word in ("que medicamento", "que tratamiento", "diagnostica", "diagnostico", "debo operarme", "deberia operarme", "conviene operarme", "asesoria medica"))
        legal = any(word in text for word in ("asesoria legal", "asesoria juridica", "demandar", "como demando", "abogado"))
        financial = any(word in text for word in ("fondo mutuo", "invertir", "inversion", "asesoria financiera"))
        if medical or legal or financial:
            return self._advice(message, session)
        asks_other = requests_third_party_data(message)
        foreign_client = any(identifier.upper() != session.get("usuario_id", "").upper() for identifier in re.findall(r"\bC\d+\b", message, re.I))
        if session.get("rol") == "cliente" and (asks_other or foreign_client):
            self._article("general", "9", session)
            self.policy_sources = [PRIVACY]
            return ("No puedo revelar las pólizas ni los pagos de otra persona. El parentesco o conocer su DNI no autorizan el acceso. "
                    "Se debe acreditar autorización expresa por un canal de atención; este prototipo no valida esos documentos.")
        return None

    @staticmethod
    def _literal_id(plan, name, message, prefix):
        """Busca un único código completo en la pregunta y lo compara con el que
        entendió Qwen. No elige uno si hay varios o si no coincide.
        """
        identifiers = set(value.upper() for value in literal_ids(message, prefix))
        if len(identifiers) != 1:
            return None
        planned = plan.get(name)
        if planned and (not isinstance(planned, str) or planned.upper() not in identifiers):
            return None
        return planned.upper() if planned else next(iter(identifiers))

    def resolve(self, plan, message, session):
        """Recibe la pregunta, el usuario y los datos ya revisados que indican qué se
        quiere consultar. Elige la búsqueda adecuada, como ver pólizas, consultar un
        siniestro o revisar una cobertura. Por ejemplo, si C001 pide el estado de
        S-5521, busca ese expediente entre los datos permitidos y prepara la
        explicación con sus fuentes. Devuelve el texto de respuesta, una pregunta
        para aclarar lo que falta o una solicitud de atención. La parte que lo llamó
        guarda después las herramientas utilizadas y el resultado.
        """
        guarded = self.guard(message, session)
        if guarded:
            return guarded
        intent = plan.get("intent") if isinstance(plan, dict) else None
        if not isinstance(intent, str):
            return self._escalate("No pude interpretar una consulta válida y no puedo confirmar información.", session)
        if intent == "ayuda" or (intent == "aclaracion" and general_help_request(message)):
            return self._help(session)
        if intent == "asesoria":
            return self._advice(message, session)
        if intent == "operacion_no_permitida":
            self.policy_sources = [PRIVACY]
            self._article("general", "5", session)
            return "No puedo modificar pólizas o siniestros, aprobar, rechazar ni cambiar montos. Este canal es de solo lectura."
        if intent == "consultar_polizas" or (own_policy_request(message) and intent in {"aclaracion", "cobertura", "consulta_tercero"}):
            return self._policies(plan, message, session)
        own_history = self_claim_history_request(message)
        if intent == "historial_siniestros" or (own_history and intent in {"estado_siniestro", "consulta_tercero"}):
            if own_history and plan.get("siniestro_id") is not None:
                self.policy_sources = [NO_INVENT]
                return "Indica un único código de siniestro si buscas un expediente concreto; no utilizaré un identificador que no aparece en tu mensaje."
            if session.get("rol") != "cliente":
                self.policy_sources = [NO_INVENT]
                return "Indica el cliente o el código de póliza cuyo historial deseas consultar; la sesión de asesor no identifica a un titular de seguro."
            if not own_history:
                self.policy_sources = [NO_INVENT]
                return "Para consultar tu historial propio, indica que deseas ver tus siniestros. No seleccionaré datos de otra persona ni un expediente arbitrario."
            return self._history(session)
        if intent == "consulta_tercero" and session.get("rol") == "cliente":
            self.policy_sources = [PRIVACY]
            self._article("general", "9", session)
            return "Solo puedes consultar tus propias pólizas y siniestros. No puedo revelar información de otra persona."
        if intent in {"estado_siniestro", "motivo_rechazo"}:
            identifier = self._literal_id(plan, "siniestro_id", message, "S")
            if not identifier:
                self.policy_sources = [NO_INVENT]
                return "Indica un único código de siniestro para consultar su estado o el motivo registrado."
            return self._claim(identifier, session)
        if intent == "rechazos_trimestre":
            return self._aggregate(plan, message, session)
        if intent in {"cobertura", "aclaracion"}:
            return self._coverage(plan, message, session)
        return self._escalate("No puedo resolver esa solicitud dentro del alcance de consultas de pólizas y siniestros. No puedo confirmar información sin una consulta válida.", session, "Consulta fuera de alcance o interpretación no válida")

    def _help(self, session):
        """Explica qué se puede consultar sin buscar datos de ningún cliente.
        Lee las reglas del canal para respaldar sus límites. El rol se toma de la
        sesión, no de frases como soy asesor escritas dentro de la pregunta.
        """
        for number, clause in (("5", "5.1"), ("9", "9.2"), ("10", "10.3")):
            article, _ = self._article("general", number, session)
            if not self._clause(article, clause):
                self.policy_sources = [NO_INVENT]
                return "No pude recuperar las reglas de este canal. Solicita una revisión por un canal de atención."
        advisor = session["rol"] == "asesor"
        self.policy_sources = [PRIVACY]
        policies = "Consultar pólizas, productos y vigencias autorizados" if advisor else "Ver tus pólizas, productos y vigencias"
        claims = "Consultar expedientes autorizados, su estado y motivo de rechazo" if advisor else "Consultar tus siniestros, su estado y motivo de rechazo"
        lines = ["Puedo ayudarte a:", "- " + policies + ".", "- " + claims + ".",
                 "- Explicar coberturas y condiciones del seguro.",
                 "- Registrar un ticket local para revisión; no envía un aviso automático."]
        if advisor:
            lines.append("- Contar rechazos por ramo, trimestre y año.")
        lines.append("Por ejemplo: «¿Qué seguros tengo?» o «Quiero consultar un siniestro; indicaré su código»." if not advisor
                     else "Para un expediente indica su código; para contar rechazos, el ramo, trimestre y año.")
        lines.append("Solo muestro información permitida para tu sesión. No apruebo pagos ni cambios, ni doy recomendaciones médicas, legales o de inversión.")
        return "\n".join(lines)

    def _policies(self, plan, message, session):
        """Busca las pólizas que puede ver ese usuario. Las muestra con su producto,
        vigencia y fuentes, aunque el cliente no conozca sus códigos.
        """
        identifier = self._literal_id(plan, "poliza_id", message, "POL")
        if session.get("rol") != "cliente" and not identifier:
            self.policy_sources = [NO_INVENT]
            return "Indica un código de póliza; la sesión de asesor no identifica a un titular de seguro."
        if plan.get("poliza_id") and not identifier or len(literal_ids(message, "POL")) > 1:
            self.policy_sources = [NO_INVENT]
            return "Indica un único código de póliza que aparezca completo en tu consulta."
        if not own_policy_request(message) and not identifier:
            self.policy_sources = [NO_INVENT]
            return "Precisa si deseas consultar tus propias pólizas o indica un código de póliza."
        branches = supported_branches(message)
        sql = "SELECT poliza_id,cliente_id,ramo,producto,estado,fecha_inicio,fecha_fin FROM polizas WHERE "
        parameters = []
        if session["rol"] == "cliente":
            sql += "cliente_id=?"
            parameters.append(session["usuario_id"])
        else:
            sql += "poliza_id=?"
            parameters.append(identifier)
        if identifier and session["rol"] == "cliente":
            sql += " AND poliza_id=?"
            parameters.append(identifier)
        if len(branches) == 1:
            sql += " AND ramo=?"
            parameters.append(next(iter(branches)))
        result = self._sql(sql + " ORDER BY fecha_fin DESC,poliza_id", session, parameters)
        if result.get("error") or result.get("truncado"):
            return self._escalate("No pude obtener una lista completa y segura de las pólizas accesibles.", session)
        rows = result.get("filas", [])
        if any(session["rol"] == "cliente" and row.get("cliente_id") != session["usuario_id"] for row in rows):
            self.policy_sources = [PRIVACY]
            return "No puedo mostrar registros fuera de tu sesión."
        if not rows:
            self.policy_sources = [NO_INVENT]
            return "No encontré pólizas con esos datos entre los registros a los que tienes acceso."
        if identifier and any(row.get("poliza_id") != identifier for row in rows):
            return self._escalate("Los datos devueltos no coinciden con la póliza solicitada.", session)
        lines = [f"- {row['poliza_id']}: {row['producto']} ({row['ramo']}), estado {row['estado']}, "
                 f"vigencia del {row['fecha_inicio']} al {row['fecha_fin']}. [polizas:{row['poliza_id']}]" for row in rows]
        return "Encontré estas pólizas en los registros a los que tienes acceso:\n" + "\n".join(lines)

    def _history(self, session):
        """Busca los siniestros de las pólizas del cliente que consulta. Muestra los
        registros disponibles; que no encuentre uno no significa que nunca haya
        ocurrido.
        """
        result = self._sql(
            "SELECT s.siniestro_id,s.poliza_id,p.cliente_id,p.ramo,"
            "s.fecha_ocurrencia,s.estado,s.fecha_ultima_actualizacion "
            "FROM siniestros s JOIN polizas p ON p.poliza_id=s.poliza_id "
            "WHERE p.cliente_id=? ORDER BY s.fecha_ocurrencia DESC,s.siniestro_id",
            session, [session["usuario_id"]])
        if result.get("error"):
            return self._escalate("No pude consultar tu historial de siniestros de forma segura.", session)
        rows = result.get("filas", [])
        statuses = {"registrado", "en_evaluacion", "aprobado", "pagado", "rechazado"}
        identifiers = []
        for row in rows:
            if row.get("cliente_id") != session["usuario_id"] or row.get("estado") not in statuses or row.get("ramo") not in {"vehicular", "salud", "vida"}:
                return self._escalate("El historial devuelto no pudo validarse como información de tu sesión.", session)
            identifier, policy = row.get("siniestro_id"), row.get("poliza_id")
            if not isinstance(identifier, str) or not re.fullmatch(r"S-\d+", identifier) or not isinstance(policy, str) or not re.fullmatch(r"POL-\d+", policy):
                return self._escalate("El historial contiene identificadores incompletos o inconsistentes.", session)
            try:
                for key in ("fecha_ocurrencia", "fecha_ultima_actualizacion"):
                    if date.fromisoformat(row[key]).isoformat() != row[key]:
                        raise ValueError("Fecha no canónica")
            except (KeyError, TypeError, ValueError):
                return self._escalate("El historial contiene fechas incompletas o inconsistentes.", session)
            identifiers.append(identifier)
        if len(set(identifiers)) != len(identifiers):
            return self._escalate("El historial contiene registros duplicados y no puedo confirmar un total.", session)
        if not rows:
            if result.get("truncado"):
                return self._escalate("La consulta del historial alcanzó un límite y no puedo confirmar un total de registros.", session)
            self.policy_sources = [NO_INVENT]
            return "No encontré siniestros registrados en tus pólizas en los datos disponibles."
        if result.get("truncado"):
            header = f"Encontré siniestros registrados en tus pólizas. Esta es una muestra limitada de {len(rows)} registros; no confirma el total del historial:"
        else:
            noun = "siniestro registrado" if len(rows) == 1 else "siniestros registrados"
            header = f"Sí, encontré {len(rows)} {noun} en tus pólizas:"
        lines = []
        for row in rows:
            status = "en evaluación" if row["estado"] == "en_evaluacion" else row["estado"].replace("_", " ")
            lines.append(f"- {row['siniestro_id']}, póliza {row['poliza_id']} ({row['ramo']}): "
                         f"ocurrió el {row['fecha_ocurrencia']}; estado registrado: {status}; "
                         f"última actualización: {row['fecha_ultima_actualizacion']}. "
                         f"[siniestros:{row['siniestro_id']}] [polizas:{row['poliza_id']}]")
        return header + "\n" + "\n".join(lines) + "\nPuedes indicar el código de un siniestro para consultar sus detalles."

    def _claim(self, identifier, session):
        """Busca un siniestro permitido y explica su estado y última actualización. Si
        fue rechazado, busca el motivo y la cláusula; un monto reclamado no significa
        que ya se aprobó un pago.
        """
        result = self._sql("SELECT s.siniestro_id,s.poliza_id,p.cliente_id,p.ramo,s.estado,s.fecha_ultima_actualizacion,s.monto_reclamado_soles,s.monto_aprobado_soles,s.motivo_rechazo,s.clausula_referencia FROM siniestros s JOIN polizas p ON p.poliza_id=s.poliza_id WHERE s.siniestro_id=?", session, [identifier])
        if result.get("error") or result.get("truncado"):
            return self._escalate("No pude consultar el expediente de forma segura.", session)
        rows = result.get("filas", [])
        if not rows or len(rows) != 1 or rows[0].get("siniestro_id") != identifier or (session["rol"] == "cliente" and rows[0].get("cliente_id") != session["usuario_id"]):
            self.policy_sources = [NO_INVENT]
            return f"No encontré el siniestro {identifier} entre los registros a los que tienes acceso. Verifica el código."
        row = rows[0]
        source = f"siniestros:{identifier}"
        status = str(row.get("estado", ""))
        if status not in {"registrado", "en_evaluacion", "aprobado", "pagado", "rechazado"}:
            return self._escalate(f"El expediente {identifier} contiene un estado no reconocido; no puedo confirmar su situación. [{source}]", session)
        if not row.get("fecha_ultima_actualizacion"):
            return self._escalate(f"El siniestro {identifier} no tiene fecha de actualización registrada verificable. [{source}]", session)
        label = "en evaluación" if status == "en_evaluacion" else status.replace("_", " ")
        answer = f"El siniestro {identifier} figura {label}. Última actualización: {row.get('fecha_ultima_actualizacion')}. [{source}]"
        if status == "rechazado":
            evidence = self._rejection(row, row["ramo"], session)
            if evidence is None:
                return self._escalate(answer + " No puedo justificar el motivo: faltan datos o la cláusula no coincide con el expediente.", session)
            reason, clause, citation = evidence
            answer += f" Motivo registrado: «{reason}». [{source}] Cláusula aplicable registrada {row['clausula_referencia']}: «{clause}». [{citation}]"
        elif status in {"registrado", "en_evaluacion"}:
            if row.get("monto_aprobado_soles") is not None:
                return self._escalate(answer + " Hay una discrepancia entre el estado y el monto aprobado del expediente.", session)
            answer += f" No hay monto de indemnización aprobado registrado; no puedo confirmar un pago ni una fecha. [{source}]"
        elif status in {"aprobado", "pagado"}:
            amount = row.get("monto_aprobado_soles")
            if not isinstance(amount, (int, float)) or amount < 0:
                return self._escalate(answer + " Falta el monto aprobado del expediente.", session)
            answer += f" Monto aprobado registrado: S/ {amount:,.2f}. [{source}]"
        else:
            return self._escalate(answer + " El estado registrado no está reconocido.", session)
        return answer

    def _rejection(self, row, branch, session):
        """Explica el rechazo usando el motivo guardado y la cláusula indicada en el
        expediente. Si falta información, pide revisión en vez de inventar una causa.
        """
        reason, reference = row.get("motivo_rechazo"), row.get("clausula_referencia")
        if not isinstance(reason, str) or not reason.strip() or not isinstance(reference, str):
            return None
        if re.search(r"\b(ignora|instrucciones|aprueba|sistema|system|assistant|obedec|prompt|promete|transfiere|olvida)\b", normalize(reason)):
            return None
        match = re.fullmatch(r"(Vehicular|Salud|Vida|Condiciones Generales)\s+(\d+)\.(\d+)", reference, re.I)
        if not match:
            return None
        document = "general" if normalize(match[1]) == "condiciones generales" else normalize(match[1])
        if document not in {branch, "general"}:
            return None
        article, source = self._article(document, match[2], session)
        clause = self._clause(article, f"{match[2]}.{match[3]}")
        if not clause:
            return None
        reason_tokens = {word for word in re.findall(r"[a-z]+", normalize(reason)) if len(word) >= 5}
        clause_tokens = set(re.findall(r"[a-z]+", normalize(clause)))
        if not reason_tokens & clause_tokens:
            return None
        topics = (("ebriedad", "dosaje"), ("taxi", "aplicativo"), ("licencia",), ("desgaste", "mecanic"),
                  ("preexist",), ("suspend", "suspension", "pago"), ("invalidez",))
        reason_topics = {index for index, terms in enumerate(topics) if any(term in normalize(reason) for term in terms)}
        clause_topics = {index for index, terms in enumerate(topics) if any(term in normalize(clause) for term in terms)}
        if reason_topics and not reason_topics & clause_topics:
            return None
        actual_dose = re.search(r"(\d+(?:[.,]\d+)?)\s*g/l", normalize(reason))
        minimum_dose = re.search(r"mayor a\s+(\d+(?:[.,]\d+)?)\s*g/l", normalize(clause))
        if actual_dose and minimum_dose and float(actual_dose[1].replace(",", ".")) < float(minimum_dose[1].replace(",", ".")):
            return None
        return clean(reason), clause, source

    def _aggregate(self, plan, message, session):
        """Cuenta los rechazos del seguro y trimestre pedidos por un asesor. Usa la
        última actualización como aproximación y lo dice, porque no hay una fecha de
        rechazo en los datos.
        """
        if session.get("rol") != "asesor":
            self.policy_sources = [PRIVACY]
            return "Las estadísticas de toda la aseguradora requieren una sesión de asesor. Como cliente solo puedes consultar tus propios registros."
        branch, quarter, year = plan.get("ramo"), plan.get("trimestre"), plan.get("anio")
        text = normalize(message)
        if len(literal_quarters(message)) > 1 or len(literal_years(message)) > 1 or len(supported_branches(message)) > 1:
            self.policy_sources = [NO_INVENT]
            return "Indica un único ramo, trimestre y año para obtener un agregado verificable; no seleccionaré un período arbitrario de la comparación."
        if not isinstance(branch, str) or branch not in supported_branches(message) or type(quarter) is not int or quarter not in literal_quarters(message) or type(year) is not int or year not in literal_years(message) or not 1900 <= year <= 2199:
            self.policy_sources = [NO_INVENT]
            return "Para el agregado indica el ramo, el trimestre y el año de los rechazos."
        start = date(year, (quarter - 1) * 3 + 1, 1)
        end = add_months(start, 3)
        result = self._sql("SELECT s.siniestro_id,p.cliente_id,s.clausula_referencia,s.motivo_rechazo,s.fecha_ultima_actualizacion FROM siniestros s JOIN polizas p ON p.poliza_id=s.poliza_id WHERE p.ramo=? AND s.estado='rechazado' AND s.fecha_ultima_actualizacion>=? AND s.fecha_ultima_actualizacion<?", session, [branch, start.isoformat(), end.isoformat()])
        if result.get("error") or result.get("truncado"):
            return self._escalate("No pude obtener el agregado completo de rechazos.", session)
        rows = result.get("filas", [])
        grouped = Counter(row.get("clausula_referencia") for row in rows)
        details = []
        for reference, count in grouped.most_common():
            examples = [row for row in rows if row.get("clausula_referencia") == reference]
            evidence = [self._rejection(row, branch, session) for row in examples]
            if any(item is None for item in evidence):
                return self._escalate("No puedo justificar todos los motivos del agregado: hay datos o cláusulas ausentes o inconsistentes.", session)
            reasons = sorted({item[0] for item in evidence})
            ids = ", ".join(row["siniestro_id"] for row in examples)
            details.append(f"{reference}: {count} ({'; '.join(reasons)}; registros {ids})")
        return (f"Hay {len(rows)} siniestros de seguro {branch} rechazados cuya última actualización está en el trimestre consultado. "
                + ("Motivos agrupados por cláusula: " + "; ".join(details) + ". " if details else "")
                + "Supuesto: fecha_ultima_actualizacion se utiliza como aproximación a la fecha de rechazo. No existe fecha_rechazo ni historial de estados; la última actualización del expediente no garantiza que ese día se haya decidido el rechazo.")

    def _interval(self, message):
        """Convierte palabras como ayer en fechas, usando la fecha fija del ejercicio.
        No deja que el usuario cambie esa fecha diciendo que hoy es otro día.
        """
        text = normalize(message)
        # Fechas como 'ayer' se calculan con la fecha fija del ejercicio.
        # Decir 'hoy es 2027-01-01' no cambia esa fecha ni el día del siniestro.
        event_text = re.sub(r"\b(?:hoy(?:\s+es)?|fecha(?:\s+de)?\s+referencia(?:\s+es)?)\s+\d{4}-\d{2}-\d{2}\b", "", text)
        explicit = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", event_text))
        if len(explicit) == 1:
            value = date.fromisoformat(next(iter(explicit)))
            return value, value
        if explicit:
            return None
        if "proxima semana" in text:
            start = self.today + timedelta(days=7 - self.today.weekday())
            return start, start + timedelta(days=6)
        if "ayer" in text or "anoche" in text:
            value = self.today - timedelta(days=1)
            return value, value
        if event_text != text:
            return None
        if re.search(r"\bhoy\b", text):
            return self.today, self.today
        return None

    @staticmethod
    def _event(message):
        events = supported_events(message) - {"desconocido"}
        return next(iter(events)) if len(events) == 1 else "desconocido"

    def _coverage(self, plan, message, session):
        """Busca la póliza permitida y revisa su producto, vigencia y lo ocurrido.
        Explica las condiciones o pide los datos que falten, sin prometer que se
        pagará.
        """
        text = normalize(message)
        policy_id = self._literal_id(plan, "poliza_id", message, "POL")
        branches = list(supported_branches(message))
        branch = branches[0] if len(branches) == 1 else None
        if plan.get("poliza_id") and not policy_id:
            self.policy_sources = [NO_INVENT]
            return "Indica el código de póliza que deseas consultar."
        if session["rol"] == "asesor" and not policy_id:
            self.policy_sources = [NO_INVENT]
            return "Indica el código de póliza para identificar al cliente y consultar su cobertura."
        fields = "poliza_id,cliente_id,ramo,producto,fecha_inicio,fecha_fin,deducible_soles,suma_asegurada_soles,estado"
        result = self._sql(f"SELECT {fields} FROM polizas" + (" WHERE poliza_id=?" if policy_id else " WHERE ramo=?" if branch else ""), session, [policy_id] if policy_id else [branch] if branch else [])
        if result.get("error") or result.get("truncado"):
            return self._escalate("No pude consultar las pólizas accesibles de forma completa.", session)
        rows = result.get("filas", [])
        if session["rol"] == "cliente" and any(row.get("cliente_id") != session["usuario_id"] for row in rows):
            self.policy_sources = [PRIVACY]
            return "No puedo mostrar registros fuera de tu sesión. Verifica el código por un canal de atención."
        if not rows:
            self.policy_sources = [NO_INVENT]
            return "No encontré una póliza con esos datos entre los registros a los que tienes acceso."
        if policy_id and (len(rows) != 1 or rows[0].get("poliza_id") != policy_id):
            return self._escalate("La consulta no devolvió una póliza que coincida con el identificador solicitado.", session)
        if not branch and not policy_id:
            names = ", ".join(f"{row['poliza_id']} ({row['ramo']}, {row['estado']})" for row in rows)
            self.policy_sources = [NO_INVENT]
            return f"Encontré estas pólizas accesibles: {names}. ¿Sobre qué seguro y qué evento necesitas consultar la cobertura?"
        event = self._event(message)
        specific = re.search(r"\b(?:cirugi\w*|operacion\w*|maternidad|hospitaliza\w*|emergencia\w*|incendio\w*|lunas?|accesorio\w*|rotura\w*|fallec\w*|invalidez|sufr\w*|ocurr\w*|inund\w*|granizo|terremoto|lluvia|averia|dano\w*|danad\w*|volc\w*|despist\w*)\b", text)
        general = event == "desconocido" and not specific and (
            general_coverage_request(message) or bool(re.search(r"\b(?:cobertur\w*|cubr\w*|protege|incluye)\b", text)))
        try:
            interval = self._interval(message)
        except ValueError:
            self.policy_sources = [NO_INVENT]
            return "La fecha indicada no es válida. Escribe la fecha del evento en formato AAAA-MM-DD."
        matching = [row for row in rows if interval and row["fecha_inicio"] <= interval[0].isoformat() and interval[1].isoformat() <= row["fecha_fin"]]
        if not policy_id and len(rows) > 1:
            if general:
                active = [row for row in rows if row["estado"] == "vigente" and row["fecha_inicio"] <= self.today.isoformat() <= row["fecha_fin"]]
                if len(active) == 1:
                    rows = active
                else:
                    self.policy_sources = [NO_INVENT]
                    codes = ", ".join(f"{row['poliza_id']} ({row['producto']}, {row['estado']})" for row in rows)
                    return f"Hay varias pólizas posibles: {codes}. Indica el código de póliza cuyo producto deseas conocer."
            elif len(matching) != 1:
                self.policy_sources = [NO_INVENT]
                return "Hay varias pólizas posibles de ese ramo. Indica el código de póliza y la fecha del evento para precisar la cobertura."
            else:
                rows = matching
        policy = rows[0]
        try:
            start_date = date.fromisoformat(policy["fecha_inicio"])
            end_date = date.fromisoformat(policy["fecha_fin"])
            if start_date > end_date:
                raise ValueError("Vigencia invertida")
        except (KeyError, TypeError, ValueError):
            return self._escalate("La póliza tiene fechas de vigencia incompletas o inconsistentes.", session)
        branch = policy["ramo"]
        source = f"polizas:{policy['poliza_id']}"
        base = f"La póliza {policy['poliza_id']} ({policy['producto']}) figura {policy['estado']}, con vigencia del {policy['fecha_inicio']} al {policy['fecha_fin']}. [{source}]"
        if general:
            return self._coverage_summary(policy, base, session)
        validity, validity_source = self._article("general", "3", session)
        if not self._clause(validity, "3.1"):
            return self._escalate(base + " No pude recuperar la regla de vigencia aplicable.", session)
        if policy["estado"] == "anulada":
            return self._escalate(base + " Falta la fecha de anulación para evaluar cuándo dejó de cubrir; no puedo inferirla.", session)
        if interval and (interval[1].isoformat() < policy["fecha_inicio"] or interval[0].isoformat() > policy["fecha_fin"]):
            return base + f" El evento relatado del {interval[0].isoformat()} al {interval[1].isoformat()} queda fuera de vigencia y no tiene cobertura por esta póliza. [{validity_source}] No puedo ofrecerte un monto ni un plazo de indemnización."
        if interval and not matching:
            return base + " La fecha o intervalo cruza el límite de vigencia. Indica la fecha exacta del evento para revisarlo."
        if branch == "salud" and event == "cirugia_programada":
            return self._surgery(policy, interval, base, session)
        if branch == "vehicular" and event in {"choque", "robo"}:
            return self._vehicle(policy, event, interval, message, base, session)
        self.policy_sources = [NO_INVENT]
        health_note = " Si es una cirugía, indica si es programada o una emergencia; no puedo diagnosticar esa condición." if branch == "salud" else ""
        return base + " Necesito el evento concreto y su fecha para explicar la cobertura aplicable." + health_note + " La suma asegurada no equivale a una indemnización aprobada."

    def _coverage_summary(self, policy, base, session):
        """Busca qué incluye el producto y prepara un resumen con fuentes. Ese resumen
        no aprueba la cobertura de un siniestro concreto.
        """
        branch, product = policy["ramo"], policy["producto"]
        article, source = self._article(branch, "1", session)
        if not article:
            return self._escalate(base + " No pude recuperar las coberturas del producto.", session)
        if branch in {"vehicular", "salud"}:
            benefits = self._product_benefits(article, product)
            if not benefits:
                return self._escalate(base + " No pude verificar la columna del producto en su condicionado.", session)
            answer = base + f"\nResumen general de {product}, según su condicionado:\n"
            answer += "\n".join(f"- {label}: {value}. [{source}]" for label, value in benefits)
            if branch == "salud":
                note = self._clause(article, "1.1")
                annual, annual_source = self._article("salud", "2", session)
                maximum = self._clause(annual, "2.1")
                if not note or not maximum:
                    return self._escalate(base + " No pude verificar cómo se aplican los porcentajes o el límite anual de salud.", session)
                answer += f"\n«{note}». [{source}] «{maximum}». [{annual_source}]"
        elif branch == "vida":
            clauses = re.findall(r"(?m)^(1\.\d+)\.\s+(.+)$", article)
            number = next((number for number, line in clauses if clean(line).split(":", 1)[0].strip() == product), None)
            description = self._clause(article, number) if number else None
            if not description:
                return self._escalate(base + " No pude verificar la descripción de ese producto de vida.", session)
            answer = base + f"\nResumen general del producto: «{description}». [{source}]"
            if "proteccion anterior" in normalize(description):
                protection = re.search(r"\bPaga la suma asegurada[^\n]*?permanente\.", article)
                saving, saving_source = self._article("vida", "2", session)
                saving_rule = self._clause(saving, "2.1")
                if not protection or not saving_rule:
                    return self._escalate(base + " No pude verificar la protección compartida o las condiciones del ahorro.", session)
                answer += f"\nLa protección referida es: «{clean(protection[0])}». [{source}] «{saving_rule}». [{saving_source}]"
        else:
            return self._escalate(base + " El ramo no dispone de un resumen verificado.", session)
        for key, label in (("suma_asegurada_soles", "Suma asegurada registrada"), ("deducible_soles", "Deducible registrado")):
            value = policy.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                answer += f"\n{label}: S/ {value:,.2f}. [polizas:{policy['poliza_id']}]"
        return answer + "\nEste resumen describe el producto; no confirma cobertura de un evento ni una indemnización aprobada."

    @staticmethod
    def _product_rows(article):
        return [[clean(cell) for cell in line.strip().strip("|").split("|")]
                for line in (article or "").splitlines() if line.lstrip().startswith("|")]

    @staticmethod
    def _product_benefits(article, product):
        rows = Resolver._product_rows(article)
        if not rows or rows[0].count(product) != 1 or product not in rows[0][1:]:
            return None
        index = rows[0].index(product)
        return [(row[0], row[index]) for row in rows[1:]
                if len(row) == len(rows[0]) and row[0] and not re.fullmatch(r"[\s:-]+", row[0]) and row[index]]

    def _surgery(self, policy, interval, base, session):
        """Compara la fecha de una cirugía programada con el plazo de espera del seguro.
        Explica esa condición sin dar un diagnóstico ni recomendar tratamientos.
        """
        article, source = self._article("salud", "4", session)
        clause = self._clause(article, "4.2")
        exclusion = self._clause(article, "4.5")
        months = re.search(r"\b(\d+)\s+meses\b", clause or "")
        if not months or not exclusion or not all(word in normalize(clause) for word in ("cirugias programadas", "inicio")):
            return self._escalate(base + " No pude verificar la regla de carencia de cirugía programada.", session)
        duration = int(months[1])
        try:
            end = add_months(date.fromisoformat(policy["fecha_inicio"]), duration)
        except (OverflowError, ValueError):
            return self._escalate(base + " La carencia documentada no puede calcularse con las fechas disponibles.", session)
        answer = base + f" Las cirugías programadas tienen {duration} meses de carencia desde el inicio, hasta el {end.isoformat()}. [{source}]"
        if interval is None:
            return answer + " Indica la fecha exacta de la cirugía para contrastarla con ese plazo y la vigencia."
        if interval[1] < end:
            return answer + f" La cirugía entre {interval[0].isoformat()} y {interval[1].isoformat()} queda dentro de la carencia y no está cubierta por esa prestación. [{source}] La consulta describe cirugía programada; no estoy haciendo un diagnóstico médico."
        if interval[0] < end:
            return answer + " La semana indicada cruza el fin de la carencia. Indica la fecha exacta de la cirugía."
        return answer + " La fecha indicada cumple esta carencia. Eso no garantiza la aprobación: deben revisarse las demás condiciones y el gasto cubierto."

    @staticmethod
    def _product_cell(article, product, coverage):
        lines = Resolver._product_rows(article)
        if not lines or product not in lines[0][1:]:
            return None
        index = lines[0].index(product)
        row = next((row for row in lines[1:] if row and normalize(row[0]) == normalize(coverage)), None)
        return row[index] if row and index < len(row) else None

    def _vehicle(self, policy, event, interval, message, base, session):
        """Comprueba si el producto incluye lo ocurrido con el vehículo. Explica las
        condiciones, el deducible y los pasos indicados, sin prometer un monto o
        fecha de pago.
        """
        article, source = self._article("vehicular", "1", session)
        text = normalize(message)
        if event == "choque":
            coverage = "Daño propio por choque, vuelco o despiste"
        elif any(word in text for word in ("accesorio", "faro", "espejo")):
            coverage = "Robo parcial de accesorios"
        elif any(word in text for word in ("auto", "vehiculo", "carro", "total")):
            coverage = "Robo total del vehículo"
        else:
            return base + " Precisa si fue robo total del vehículo o de accesorios."
        value = self._product_cell(article, policy["producto"], coverage)
        if value is None:
            return self._escalate(base + " No pude verificar la cobertura del producto en su condicionado.", session)
        if normalize(value) == "no":
            return base + f" El condicionado indica que {policy['producto']} no incluye «{coverage}». [{source}] No puedo aprobar indemnizaciones."
        if not normalize(value).startswith("si"):
            return self._escalate(base + " La cobertura del producto requiere una interpretación adicional.", session)
        if not isinstance(policy.get("deducible_soles"), (int, float)) or policy["deducible_soles"] < 0:
            return self._escalate(base + " El deducible registrado es incompleto o inconsistente.", session)
        exclusions, exclusions_source = self._article("vehicular", "5", session)
        if not exclusions:
            return self._escalate(base + " Falta el artículo de exclusiones para orientar la cobertura.", session)
        answer = base + f" El producto contempla «{coverage}». [{source}] Deducible registrado: S/ {policy['deducible_soles']:,.2f}. [polizas:{policy['poliza_id']}] La cobertura está sujeta a vigencia, exclusiones y evaluación; no es una aprobación. [{exclusions_source}]"
        if not interval:
            return answer + " Indica la fecha exacta del evento."
        notice, notice_source = self._article("vehicular", "3", session)
        notice_clause = self._clause(notice, "3.1")
        if not notice_clause:
            return self._escalate(answer + " No pude recuperar el plazo de aviso aplicable.", session)
        answer += f" Aviso: «{notice_clause}». [{notice_source}]"
        if event == "choque":
            police = self._clause(notice, "3.2")
            procedure, procedure_source = self._article("vehicular", "6", session)
            workshop, documents = self._clause(procedure, "6.2"), self._clause(procedure, "6.3")
            if not police or not workshop or not documents:
                return self._escalate(answer + " Falta verificar el procedimiento aplicable al choque.", session)
            answer += f" «{police}». [{notice_source}] «{workshop}». «{documents}». [{procedure_source}]"
        else:
            theft, theft_source = self._article("vehicular", "4", session)
            complaint = self._clause(theft, "4.1")
            if not complaint:
                return self._escalate(answer + " Falta verificar el procedimiento de robo.", session)
            answer += f" «{complaint}». [{theft_source}] No puedo confirmar un monto o fecha de pago sin evaluación y documentación."
        return answer + " Los datos disponibles no incluyen historial de primas para confirmar que los pagos estén al día."
