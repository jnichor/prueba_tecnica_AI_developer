# Documento de diseño

**Candidato:** Jesus Nicho Rosado  
**Fecha:** 4 de noviembre de 2026

## 1. Resumen de la solución

Asistente local en Python que recibe una consulta y una sesión confiable. Un modelo interpreta intención y entidades; el código consulta datos y condiciones y construye respuestas con fuentes. Incluye preparación automática de Ollama, consola, evaluación y consumo. El último lote resolvió 12 casos con nueve llamadas reales y tres controles previos.

**En nueve casos**, Qwen interpretó qué pedía el usuario; después, el código consultó los datos y las condiciones y construyó la respuesta con sus fuentes.

**En tres casos**, reglas escritas en el programa respondieron antes de consultar a Qwen:

- Pedir los seguros del esposo: proteger sus datos y no revelar información ajena.
- Pedir una recomendación de inversión: registrar un ticket local para que lo atienda un asesor.
- Ordenar aprobar un siniestro alegando ser supervisor: negar el cambio porque el canal es de solo lectura.

Estos tres casos también recibieron una respuesta, con cero llamadas al modelo.

## 2. Arquitectura

Los comandos están en `scripts/`, el motor del agente en `seguros/` y las pruebas en `tests/`. Los datos, condiciones y resultados conservan sus carpetas en la raíz.

Por ejemplo, el cliente C001 pregunta: **«¿En qué estado está mi siniestro S-5521?»**

1. El programa recibe la pregunta y la identidad C001 desde la sesión. No toma la identidad de lo que diga el mensaje.
2. Qwen identifica que se quiere consultar un estado y reconoce el código S-5521.
3. El programa comprueba que ese código aparece en la pregunta y limita la búsqueda a los datos autorizados para la sesión.
4. Consulta los registros de siniestros y pólizas. En este ejemplo, S-5521 pertenece a C001 y figura **en evaluación**.
5. Construye la respuesta con ese estado y la fuente `siniestros:S-5521`. Guarda la consulta, el usuario, las herramientas utilizadas y la respuesta para poder revisar lo ocurrido.

La IA entiende qué se pregunta; el programa comprueba los datos y redacta la respuesta con fuentes. Los controles de privacidad, cambios no permitidos y asesoría pueden responder antes de consultar a Qwen.

## 3. Herramientas del agente

| Herramienta | Entradas y salidas | Controles |
| --- | --- | --- |
| Consulta de datos | SQL y parámetros; filas y fuentes | Identidad validada, filas autorizadas, solo lectura |
| Búsqueda en condicionados | Texto, ramo y artículo; fragmentos y referencias | Documentos locales y prioridad del particular |
| Escalamiento | Motivo y contexto; ticket local | Identidad de sesión, sin aprobación ni envío externo |

## 4. Decisiones principales

**Modelo:** Ollama 0.40.13 con qwen2.5:7b es la única ruta para interpretar consultas. Se descartó la generación libre tras observar una causa de rechazo y un plazo inventados. La IA interpreta campos limitados y el código verifica los hechos. Un único reintento corrige formato; si falla, se registra y se pide revisión sin inventar una respuesta.

**Herramientas de Python.** Usé las herramientas que ya trae Python para leer los archivos, consultar los datos y guardar los tickets. Así hay menos componentes que instalar y es más fácil seguir cada paso de una consulta. Ollama ejecuta el modelo. Un framework podría ayudar si el agente tuviera que coordinar muchos pasos o herramientas. Para las consultas de este proyecto, el flujo actual es suficiente.

**Datos:** SQLite en memoria evita instalar paquetes y permite cargar únicamente registros autorizados. DuckDB, sugerido para los CSV, también sería válido; se priorizó una instalación sencilla. La interfaz de datos encapsula la implementación.

**Búsqueda:** artículos Markdown y palabras clave, con selección precisa por documento y ramo. Embeddings ampliarían sinónimos, a cambio de dependencias y evaluación adicional.

**Preparación:** distribución portátil oficial fijada, verificación SHA-256 y reutilización de servicio y modelo. Windows x64 permite instalación automática; otros sistemas necesitan un servicio local existente. El primer uso requiere Internet y varios GB, y puede superar cinco minutos.

**Evaluación:** se opta por una evaluación por código porque comprueba hechos concretos contra los CSV y las condiciones, con criterios más fáciles de explicar y verificar. Qwen también podría evaluar las respuestas, pero no se eligió como evaluador principal: en las pruebas cuestionó respuestas respaldadas, necesita más calibración y añade tiempo y consumo de tokens.

## 5. Supuestos

La fecha del ejercicio es 15/10/2026. Rol e identificador representan una sesión previamente autenticada; la CLI la simula. Para rechazos trimestrales, última actualización aproxima la fecha de rechazo: el campo no garantiza un cambio de estado. Las condiciones particulares prevalecen sobre las generales. Un expediente registrado es evidencia de su estado, no permiso para modificarlo.

Los datos disponibles no incluyen historial de primas ni fecha de anulación. Si falta información para responder, se pide una aclaración o se deriva la consulta para revisión humana.

## 6. Limitaciones conocidas

- **Cada pregunta empieza de cero.** El sistema sabe qué usuario estás usando, pero no recuerda lo que preguntaste antes. Para consultar nuevamente un siniestro, debes repetir su código.
- **Pedir atención no envía un aviso.** La solicitud se guarda en tu computadora, pero ningún asesor la recibe automáticamente.
- **El acceso es de prueba.** Puedes elegir con qué usuario entrar. Antes de usarlo con clientes reales, hay que añadir una verificación de identidad y proteger las consultas y respuestas guardadas.

## 7. Cómo la llevaría a producción

Antes de usar el sistema con clientes reales haría lo siguiente:

1. Verificar quién entra y permitirle consultar únicamente los datos que le corresponden.
2. Usar BigQuery para consultar los datos de la empresa y Vertex AI para ejecutar el modelo en la nube. Estas conexiones aún no están implementadas.
3. Ejecutarlo en un servidor, para que no dependa de una computadora personal.
4. Guardar las consultas y respuestas de forma segura, y enviar las solicitudes a un equipo de atención real.
5. Medir el tiempo y el consumo, y probar regularmente que las respuestas coincidan con los datos y las condiciones.

Las respuestas seguirían mostrando sus fuentes. Una persona decidiría si corresponde pagar una indemnización.
