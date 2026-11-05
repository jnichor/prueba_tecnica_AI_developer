"""Ayudas exclusivas de las pruebas. No se importan desde seguros ni scripts.
Permiten probar permisos y respuestas con interpretaciones simuladas, sin presentar
esas respuestas como una ejecución real de Qwen.
"""
import json
import re
from seguros.planning import (normalize, supported_branches, supported_events,
    literal_ids, requests_third_party_data, general_help_request, literal_quarters,
    literal_years, self_claim_history_request, own_policy_request, validate_plan)


def simulated_plan(message):
    """Prepara una interpretación simulada sólo para probar el resto del programa.
    No es una opción del agente ni sustituye a Ollama durante el uso normal.
    """
    text = normalize(message)
    plan = {"intent": "aclaracion", "siniestro_id": None, "poliza_id": None,
            "ramo": None, "evento": "desconocido", "trimestre": None, "anio": None}
    branches, events = supported_branches(message), supported_events(message) - {"desconocido"}
    if len(branches) == 1:
        plan["ramo"] = next(iter(branches))
    if len(events) == 1:
        plan["evento"] = next(iter(events))
    for key, prefix in (("siniestro_id", "S"), ("poliza_id", "POL")):
        identifiers = {value.upper() for value in literal_ids(message, prefix)}
        if len(identifiers) == 1:
            plan[key] = identifiers.pop()
    if re.search(r"\b(?:aprobar|aprueba|actualiza|modifica|elimina|borra)\b", text):
        plan["intent"] = "operacion_no_permitida"
    elif requests_third_party_data(message):
        plan["intent"] = "consulta_tercero"
    elif (any(word in text for word in ("fondo mutuo", "invertir", "inversion", "me conviene", "demandar", "medicamento", "diagnostico"))
          or re.search(r"\b(?:recomiend\w*|recomendacion\w*|aconsej\w*)\b", text)):
        plan["intent"] = "asesoria"
    elif general_help_request(message):
        plan["intent"] = "ayuda"
    elif "rechaz" in text and ("cuantos" in text or "trimestre" in text):
        plan["intent"] = "rechazos_trimestre"
        quarters, years = literal_quarters(message), literal_years(message)
        plan["trimestre"] = next(iter(quarters)) if len(quarters) == 1 else None
        plan["anio"] = next(iter(years)) if len(years) == 1 else None
    elif self_claim_history_request(message):
        plan["intent"] = "historial_siniestros"
    elif own_policy_request(message):
        plan["intent"] = "consultar_polizas"
    elif plan["siniestro_id"]:
        plan["intent"] = "motivo_rechazo" if "rechaz" in text else "estado_siniestro"
    elif plan["ramo"] or plan["poliza_id"]:
        plan["intent"] = "cobertura"
    return validate_plan(plan, message)


class SimulatedModel:
    """Contesta como una conexión de prueba a Qwen; no usa red ni cuenta tokens reales."""
    modelo = "modelo-simulado-pruebas"

    def __init__(self):
        self.events = []

    def chat(self, messages, tools, format_schema=None):
        message = next(item["content"] for item in reversed(messages) if item["role"] == "user")
        return {"role": "assistant", "content": json.dumps(simulated_plan(message))}
