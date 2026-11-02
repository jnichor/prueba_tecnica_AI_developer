# Verificación de la entrega

Revisión de contenido con asistencia de Codex contra los CSV, los artículos y las trazas de herramientas. Se verificaron las doce respuestas y las ocho reglas; no es una revisión humana independiente ni una garantía universal.

- Modelo de la ejecución real: qwen2.5:7b.
- Casos ejecutados: 12; evaluación automática: {'cumple_comprobaciones': 12}.
- Llamadas reales: 9; controles sin modelo: CP-06, CP-07, CP-09.
- Tokens: 3,549 de entrada + 517 de salida = 4,066.
- Tiempo acumulado de inferencia: 32.700 segundos.
- Suite de regresión registrada: 179 pruebas aprobadas.

## Matriz de las ocho reglas

| Regla | Control aplicado | Evidencia |
| --- | --- | --- |
| 1. Fecha de referencia | 15/10/2026 fija en sesión. Ayer/anoche se calculan como 14/10; próxima semana 19–25/10. | CP-02/04/05; test_mensaje_no_puede_redefinir_fecha_de_referencia y test_clock_override_is_not_an_event_date. |
| 2. Identidad | Rol e identificador provienen de la sesión validada. El esquema no admite rol, permisos ni identidades añadidas. | CP-09; test_plan_con_respuesta_y_rol_inyectados_no_se_renderiza y test_sesion_invalida_se_audita_sin_consultar_modelo. |
| 3. Privacidad | SQL contiene solo filas autorizadas y el resolutor comprueba titularidad; tercero y registro inexistente no se distinguen al cliente. | CP-06/11; test_cliente_no_puede_ver_siniestro_ajeno_aunque_plan_lo_pida y test_foreign_row_from_faulty_adapter_is_not_rendered. |
| 4. Solo lectura | No hay acción de aprobación o modificación. El modelo no genera SQL; la herramienta mantiene su bloqueo de escrituras. | CP-09; test_modelo_no_puede_inyectar_sql_ni_herramientas y test_sql_inyectado_en_identificador_no_se_ejecuta. |
| 5. Sin inventar | IDs y entidades deben aparecer en el mensaje. Datos o cláusulas ausentes/discrepantes provocan aclaración o ticket. | CP-03/05/11; test_identificador_inventado_por_modelo_no_dispara_sql, test_missing_clause_creates_real_ticket_without_explaining_rejection. |
| 6. Trazabilidad | Cada afirmación de expediente o contrato enlaza registros o artículos recuperados; la respuesta no es prosa libre del modelo. | CP-01–05/08/12; trazas de herramientas, fuentes inline y evaluacion_automatica.json. |
| 7. Sin asesoría indebida | No recomienda inversiones ni decisiones legales o médicas; registra derivación local, sin afirmar notificación externa. | CP-07; test_me_conviene_operarme_deriva_medica_y_no_inversion y test_asesoria_legal_y_medica_se_deriva. |
| 8. Registro | Cada interacción, incluso denegación o fallo de modelo, conserva consulta, usuario, herramientas, respuesta y métricas. | respuestas.json: 12 casos; muestra_interacciones.jsonl: cinco registros; test_error_del_modelo_se_registra_sin_fallback y test_sesion_invalida_se_audita_sin_consultar_modelo. |

## Evidencia y límites

[respuestas.json](respuestas.json) conserva exactamente las respuestas de la ejecución revisada. [muestra_interacciones.jsonl](muestra_interacciones.jsonl) conserva cinco interacciones ficticias con sus campos de auditoría; se excluyen los eventos internos del modelo. [muestra_tickets.jsonl](muestra_tickets.jsonl) contiene el ticket real local de CP-07. Las comprobaciones detalladas están en [evaluacion_automatica.md](evaluacion_automatica.md) y su JSON.

La autenticación de la consola es simulada, los tickets no notifican servicios externos y el dominio implementado es acotado. CP-08 usa última actualización como aproximación declarada, porque no existe fecha de rechazo ni historial de estados. El asistente no decide indemnizaciones ni proporciona asesoría médica, legal o de inversión.

Los SHA-256 de los archivos fuente y de esta selección están en [fuentes_sha256.json](fuentes_sha256.json). Los originales permanecen locales y no se modifican al preparar esta entrega.
