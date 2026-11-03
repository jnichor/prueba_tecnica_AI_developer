# Asistente de pólizas y siniestros

Prueba técnica desarrollada por **Jesus Nicho Rosado**. La solución consulta datos y condiciones de seguros, explica sus fuentes y deriva casos a atención humana. Usa Python y un modelo local mediante Ollama.

**Última validación:** 12 casos correctos, 179 pruebas aprobadas y nueve llamadas reales a `qwen2.5:7b`. Tres casos se resolvieron con controles previos sin IA. Los datos son ficticios.

## Inicio rápido con IA

Requisitos: **Python 3.10 o superior** y Windows x64 para la preparación automática. Git es necesario si clonas el repositorio:

~~~powershell
git clone https://github.com/jnichor/prueba_tecnica_AI_developer.git
cd prueba_tecnica_AI_developer
python run_casos.py --evaluar
~~~

El comando comprueba Ollama, reutiliza un servicio y modelo disponibles, y prepara lo que falte. En Windows x64 puede descargar la distribución portátil oficial verificada y el modelo en `.runtime/`, sin instalar un servicio del sistema ni paquetes Python.

**Tiempo de inicio:** con el modelo disponible, el lote de prueba requirió 32,7 segundos de inferencia en el equipo utilizado. La primera preparación necesita Internet y aproximadamente 6.3 GB de descarga, más espacio de extracción; puede superar cinco minutos según la red y el equipo. No se presenta esa descarga como una instalación inferior a cinco minutos.

Para preparar el entorno sin ejecutar los casos:

~~~powershell
python run_casos.py --solo-preparar
~~~

En Linux o macOS se reutiliza un servicio Ollama local ya iniciado; no se instala automáticamente el runtime. La configuración opcional está en [.env.example](.env.example). `--modelo` prevalece sobre `OLLAMA_MODEL`; `AGENT_MODE` y `OLLAMA_BASE_URL` permiten configurar el modo y el servicio local.

## Consultas y consola

### Consulta individual

Para enviar una pregunta con una sesión de demostración:

~~~powershell
python consultar.py --rol cliente --usuario C001 --mensaje "¿En qué estado está mi siniestro S-5521?"
~~~

### Consola interactiva

Para escribir varias preguntas manteniendo la misma identidad:

~~~powershell
python consultar.py --rol cliente --usuario C001 --interactivo
~~~

Escribe `salir` o `exit` para terminar. La sesión conserva su identidad, pero las consultas son independientes: no hay memoria de conversación.

### Consultas en lote: los 12 casos

Para atender automáticamente todas las consultas de `casos_prueba/casos_prueba.json`, sin escribir los doce mensajes a mano:

~~~powershell
python run_casos.py --evaluar
~~~

El programa las procesa **una tras otra**. Cada caso utiliza su propio rol e identificador como sesión simulada: no se ejecutan todos con el mismo usuario.

Por ejemplo, `CP-01` usa al cliente `C001` para preguntar por el estado de S-5521; `CP-02` usa al cliente `C002` para consultar un choque. El programa atiende ambas y los otros diez casos con la identidad correspondiente.

Las doce respuestas quedan en `salidas_ollama_corregido/respuestas.json`; los informes automáticos se guardan en esa misma carpeta. Los criterios se explican en [Evaluación y consumo](#evaluación-y-consumo).

Los argumentos de rol y usuario **simulan una sesión ya autenticada**. En producción los proporcionaría el servidor; conocer un DNI o escribir otro cargo no concede permisos.

## Evaluación y consumo

Ejecuta el flujo normal completo con un comando:

~~~powershell
python run_casos.py --evaluar
~~~

El programa:

1. Prepara Ollama y lee las 12 consultas, roles e identificadores de `casos_prueba/casos_prueba.json`.
2. En nueve casos, Qwen interpreta la intención; en tres, actúan controles programados de privacidad, inversión o cambios no permitidos.
3. Consulta CSV y artículos respetando los permisos de sesión, responde con fuentes y registra herramientas, tokens y tiempos.
4. Evalúa las respuestas guardadas y genera informes Markdown y JSON.

**Qwen no califica las respuestas.** El evaluador aplica reglas programadas y contrasta hechos y evidencias con los CSV y condicionados. Detecta contradicciones, promesas indebidas y fuentes sin respaldo.

También se revisa que:

- S-5524 se explique por ebriedad y la cláusula Vehicular 5.2, no por un aviso tardío inventado.
- La póliza POL-1004, vencida el 30 de septiembre, no dé lugar a promesas de pago; la cirugía programada respete seis meses de carencia.
- No se revelen seguros del esposo ni se aprueben siniestros por afirmar ser supervisor.
- El agregado dé cuatro rechazos y declare última actualización como aproximación, porque no existe fecha de rechazo.

### Ejemplo: cómo se evalúa una respuesta

Este ejemplo se centra sólo en el **estado de S-5521**: se compara el dato real con un fragmento de la respuesta y se explica si coinciden.

| Qué se compara | Resultado |
| --- | --- |
| Dato real de S-5521 | En evaluación |
| Respuesta del agente (fragmento abreviado) | «El siniestro S-5521 figura en evaluación» |
| Evaluación del estado | El estado coincide con el registro |

Para dar el caso por correcto, también se revisan la fecha, las fuentes y los demás criterios del caso.

**Ejemplo hipotético incorrecto — no es la respuesta actual:** si dijera «Ya fue pagado», se marcaría como incorrecto porque contradice el expediente.

Lo importante es ver **qué debía responder, qué respondió y por qué está bien o mal**.

### Consumo de tokens

Los tokens provienen de la API por consulta y reintento. Los controles sin llamadas registran cero; contadores ausentes se marcan desconocidos o incompletos. No se calcula costo monetario. El lote validado usó **3549 tokens de entrada + 517 de salida = 4066 en total**.

Las **179 pruebas** verifican funciones y controles del código. Aquí se evalúan las **12 respuestas finales**, revisadas también con asistencia de Codex. El último lote cumplió las 12 comprobaciones, con nueve llamadas a Qwen y tres controles previos.

### Archivos de referencia

Dentro de `salidas_ollama_corregido/`:

- `respuestas.json`: las respuestas reales, sus fuentes y métricas.
- `evaluacion_automatica.md`: comparación por caso y detalle de criterios.
- `evaluacion_automatica.json`: los resultados para automatizar su lectura.
- `interactions.jsonl` y `llm_calls.jsonl`: registros de consultas y llamadas al modelo.

## Entrega verificable

| Archivo | Contenido |
| --- | --- |
| [DISENO.md](DISENO.md) | Arquitectura, decisiones, alternativas y límites |
| [RESULTADOS.md](RESULTADOS.md) | Las 12 respuestas exactas, herramientas, fuentes y evaluación |
| [entrega/respuestas.json](entrega/respuestas.json) | Salida íntegra del último lote con IA |
| [entrega/muestra_interacciones.jsonl](entrega/muestra_interacciones.jsonl) | Muestra de auditoría de consultas, sesiones, herramientas y respuestas |
| [entrega/muestra_tickets.jsonl](entrega/muestra_tickets.jsonl) | Ticket local de derivación |
| [entrega/evaluacion_automatica.md](entrega/evaluacion_automatica.md) | Comprobaciones automáticas por criterio |
| [entrega/evaluacion_automatica.json](entrega/evaluacion_automatica.json) | Evaluación en formato estructurado |
| [entrega/VERIFICACION.md](entrega/VERIFICACION.md) | Evidencia del lote y matriz de las ocho reglas |
| [entrega/fuentes_sha256.json](entrega/fuentes_sha256.json) | Huellas para comprobar los archivos de evidencia |

Las nuevas ejecuciones escriben en `salidas_ollama_corregido/`. Esas carpetas de trabajo no forman parte de la entrega publicada. Los artefactos seleccionados están en `entrega/`.

La revisión de contenido se realizó **con asistencia de Codex**, contrastando los CSV y artículos del paquete. No fue una evaluación humana ciega. Coincidió con las comprobaciones automáticas existentes: 12 casos correctos. Esto acredita los casos y controles verificados, no seguridad universal.

## Cómo funciona

Por ejemplo, C001 pregunta: **«¿En qué estado está mi siniestro S-5521?»**

1. Qwen reconoce que se pide el estado y que el código es S-5521. La identidad C001 viene de la sesión, no del texto de la pregunta.
2. El programa comprueba el código y busca el registro entre los datos que ese cliente puede consultar. En este caso, encuentra que está **en evaluación**.
3. Construye la respuesta con la fuente `siniestros:S-5521` y guarda la consulta, el usuario, las herramientas utilizadas y la respuesta.

Qwen interpreta la pregunta; el programa comprueba los datos y redacta la respuesta. Cuando la consulta lo requiere, también revisa los artículos de los condicionados. Los controles de privacidad, cambios no permitidos y asesoría pueden responder antes de consultar a Qwen.

## Pruebas y límites

### Qué comprueban las pruebas

~~~powershell
python -m unittest discover -s tests
~~~

Estas pruebas comprueban los permisos, el bloqueo de cambios, las reglas y las fuentes, entre otros comportamientos del programa. No equivalen a hacer todas esas consultas a Qwen ni garantizan que se entienda cualquier frase.

La preparación de una instalación nueva se probó con archivos y servicios simulados. La prueba real usó el modelo disponible en la misma computadora; no se validó otra computadora física.

### Hasta dónde llega esta demostración

- **Fecha fija:** las consultas usan el 15 de octubre de 2026 como fecha del ejercicio.
- **Rechazos por trimestre:** se usa la última actualización del registro porque los datos no incluyen la fecha de rechazo. Es una aproximación y puede no coincidir con el día de la decisión.
- **Datos incompletos:** no hay historial de pagos de primas ni fecha de anulación. Si falta información, se pide una aclaración o revisión humana; no se inventa.
- **Atención pendiente:** un ticket se guarda como archivo local; no envía un aviso a un asesor.
- **Acceso de prueba:** la consola permite elegir un usuario. Antes de atender clientes reales, hacen falta una verificación de identidad, protección de los registros guardados y atención de varios usuarios.
- **Enunciado excluido:** el PDF confidencial no se incluye ni se necesita para ejecutar. Las referencias a `ENUNCIADO.pdf` señalan las reglas implementadas en el programa.

## Uso de asistentes de IA

Se utilizó **OpenAI Codex** para analizar el material, diseñar la arquitectura, implementar código y documentación, preparar pruebas y apoyar la verificación de resultados contra los datos y condiciones.

Esto se distingue del modelo de ejecución: **Ollama 0.40.13 con `qwen2.5:7b`**, que interpreta consultas durante el uso del agente. La revisión asistida no sustituye comprender y poder explicar o modificar la solución.
