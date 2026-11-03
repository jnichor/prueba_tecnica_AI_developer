# Verificación de la entrega

Revisión de contenido con asistencia de Codex contra los CSV, los artículos y las trazas de herramientas. Se verificaron las doce respuestas y las ocho reglas; no es una revisión humana independiente ni una garantía universal.

- Modelo de la ejecución real: qwen2.5:7b.
- Casos ejecutados: 12; evaluación automática: {'cumple_comprobaciones': 12}.
- Llamadas reales: 9; controles sin modelo: CP-06, CP-07, CP-09.
- Tokens: 5,349 de entrada + 513 de salida = 5,862.
- Tiempo acumulado de inferencia: 32.419 segundos.
- Suite de regresión registrada: 216 pruebas aprobadas.

## Matriz de las ocho reglas

| Regla | Control | Evidencia revisada |
| --- | --- | --- |
| 1. Fecha | Referencia fija 15/10/2026; fechas relativas calculadas en código. | CP-02/04/05 y pruebas de fecha inyectada. |
| 2. Identidad | La sesión aporta rol e identificador; el mensaje no cambia permisos. | CP-09, 12 sesiones de auditoría y pruebas de identidad inválida. |
| 3. Privacidad | Consulta y respuesta limitadas a registros autorizados. | CP-06/11 y pruebas de terceros, mezclas y clientes distintos. |
| 4. Solo lectura | No existe herramienta para aprobar ni modificar expedientes. | CP-09 y pruebas SQL/planes maliciosos. |
| 5. Sin inventar | Datos registrados y cláusulas contrastados; se aclara o deriva lo insuficiente. | CP-03/04/05/10/11/12 y pruebas de datos ausentes o contradictorios. |
| 6. Trazabilidad | Cada afirmación usa registros o artículos recuperados. | Las 12 respuestas y su evaluación automática. |
| 7. Sin asesoría indebida | No recomienda inversiones; registra una derivación local real. | CP-07, ticket verificado y pruebas médicas/legales. |
| 8. Registro | Se conservan consulta, sesión, herramientas, respuesta y métricas. | respuestas.json: 12 casos; muestra_interacciones.jsonl: cinco registros; pruebas de fallos de modelo y sesión. |

## Evidencia y límites

[respuestas.json](respuestas.json) conserva exactamente las respuestas de la ejecución revisada. [muestra_interacciones.jsonl](muestra_interacciones.jsonl) conserva cinco interacciones ficticias con sus campos de auditoría; se excluyen los eventos internos del modelo. [muestra_tickets.jsonl](muestra_tickets.jsonl) contiene el ticket real local de CP-07. Las comprobaciones detalladas están en [evaluacion_automatica.md](evaluacion_automatica.md) y su JSON.

La autenticación de la consola es simulada, los tickets no notifican servicios externos y el dominio implementado es acotado. CP-08 usa última actualización como aproximación declarada, porque no existe fecha de rechazo ni historial de estados. El asistente no decide indemnizaciones ni proporciona asesoría médica, legal o de inversión.

Los SHA-256 de los archivos fuente y de esta selección están en [fuentes_sha256.json](fuentes_sha256.json). Los originales permanecen locales y no se modifican al preparar esta entrega.
