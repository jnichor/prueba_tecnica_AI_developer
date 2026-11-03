# Documento de diseño

**Candidato:** Jesus Nicho Rosado  
**Fecha:** 2 de noviembre de 2026

## 1. Resumen de la solución

Asistente local en Python que recibe una consulta y una sesión confiable. Un modelo interpreta intención y entidades; el código consulta datos y condiciones y construye respuestas con fuentes. Incluye preparación automática de Ollama, consola, evaluación y consumo. El último lote resolvió 12 casos con nueve llamadas reales y tres controles previos.

**En nueve casos**, Qwen interpretó qué pedía el usuario; después, el código consultó los datos y las condiciones y construyó la respuesta con sus fuentes.

**En tres casos**, reglas escritas en el programa respondieron antes de consultar a Qwen:

- Pedir los seguros del esposo: proteger sus datos y no revelar información ajena.
- Pedir una recomendación de inversión: registrar un ticket local para que lo atienda un asesor.
- Ordenar aprobar un siniestro alegando ser supervisor: negar el cambio porque el canal es de solo lectura.

Estos tres casos también recibieron una respuesta, con cero llamadas al modelo.

## 2. Arquitectura

~~~text
Consulta + sesión → Planner → plan validado → Resolver
                                              ↓
                              Tools → SQL / artículos / tickets
                                              ↓
                              respuesta + fuentes + auditoría
~~~

El plan contiene siete campos: intención, siniestro, póliza, ramo, evento, trimestre y año. Las entidades deben estar respaldadas por el mensaje. El modelo no recibe expedientes ni artículos, no genera SQL ni redacta respuestas. El resolutor aplica reglas y consultas parametrizadas. La sesión permanece independiente del texto.

## 3. Herramientas del agente

| Herramienta | Entradas y salidas | Controles |
| --- | --- | --- |
| Consulta de datos | SQL y parámetros; filas y fuentes | Identidad validada, filas autorizadas, solo lectura |
| Búsqueda en condicionados | Texto, ramo y artículo; fragmentos y referencias | Documentos locales y prioridad del particular |
| Escalamiento | Motivo y contexto; ticket local | Identidad de sesión, sin aprobación ni envío externo |

## 4. Decisiones principales

**Modelo:** Ollama 0.40.13 con qwen2.5:7b. Se descartó la generación libre tras observar una causa de rechazo y un plazo inventados. La IA ahora interpreta campos limitados y el código verifica los hechos. Un único reintento corrige formato; si falla, se audita y deriva sin ocultar un reemplazo offline.

**Framework:** biblioteca estándar para reducir dependencias y explicar el circuito. Un framework ofrecería abstracciones, pero añadiría configuración innecesaria para este alcance.

**Datos:** SQLite en memoria evita instalar paquetes y permite cargar únicamente registros autorizados. DuckDB, sugerido para los CSV, también sería válido; se priorizó una instalación sencilla. La interfaz de datos encapsula la implementación.

**Búsqueda:** artículos Markdown y palabras clave, con selección precisa por documento y ramo. Embeddings ampliarían sinónimos, a cambio de dependencias y evaluación adicional.

**Preparación:** distribución portátil oficial fijada, verificación SHA-256 y reutilización de servicio y modelo. Windows x64 permite instalación automática; otros sistemas necesitan un servicio local existente. El primer uso requiere Internet y varios GB, y puede superar cinco minutos.

**Evaluación:** reglas acotadas y revisión de contenido asistida por Codex contra fuentes. Los tokens provienen de la API por consulta; contadores ausentes permanecen desconocidos.

## 5. Supuestos

La fecha del ejercicio es 15/10/2026. Rol e identificador representan una sesión previamente autenticada; la CLI la simula. Para rechazos trimestrales, última actualización aproxima la fecha de rechazo: el campo no garantiza un cambio de estado. Las condiciones particulares prevalecen sobre las generales. Un expediente registrado es evidencia de su estado, no permiso para modificarlo.

## 6. Limitaciones conocidas

No hay historial de primas ni fecha de anulación para reconstruir todos los eventos. Discrepancias o datos insuficientes requieren aclaración o revisión humana. Los tickets son archivos locales y no notifican. La consola mantiene identidad, sin memoria conversacional. Logs sin cifrado y sesiones simuladas no son un sistema de producción. El lenguaje y las reglas cubiertos son acotados; 12 casos correctos y 179 pruebas no garantizan seguridad universal. Una instalación limpia se probó con simulaciones, no en otra computadora física.

## 7. Cómo la llevaría a producción

Integraría autenticación del servidor y autorización equivalente en la base. Sustituiría el adaptador de datos por BigQuery; esa integración aún no está implementada. Añadiría un adaptador de modelo administrado, protección y retención de logs, tickets en un sistema real, métricas y evaluaciones continuas. Mantendría la verificación de entidades y fuentes y la decisión humana sobre indemnizaciones.
