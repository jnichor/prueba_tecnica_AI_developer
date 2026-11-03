# Asistente de pólizas y siniestros

Prueba técnica desarrollada por **Jesus Nicho Rosado**. La solución consulta datos y condiciones de seguros, explica sus fuentes y deriva casos a atención humana. Usa Python y un modelo local mediante Ollama.

La validación del 3 de noviembre de 2026 documenta 12 casos correctos con `qwen2.5:7b` y 216 pruebas aprobadas. Tres casos se resolvieron con controles previos sin IA. Además se verificaron consultas naturales de historial, póliza y cobertura en la consola. Los datos son ficticios.

## Inicio rápido con IA

Requisitos: **Python 3.10 o superior**, **Git** y **Windows x64** para la preparación automática.

~~~powershell
git clone https://github.com/jnichor/prueba_tecnica_AI_developer.git
cd prueba_tecnica_AI_developer
python run_casos.py --evaluar
~~~

El último comando prepara Ollama y el modelo, ejecuta los **12 casos** y crea en tu computadora la carpeta `salidas_ollama_corregido/`, donde guarda las respuestas y la evaluación. Los resultados incluidos en este repositorio están en [entrega/](entrega/). No necesitas instalar paquetes Python ni configurar una clave API. La IA se ejecuta en tu computadora.

**Primera vez:** necesita Internet y descarga varios GB; puede superar cinco minutos según la conexión y el equipo. **Después:** reutiliza lo instalado. Desde la carpeta del proyecto, solo ejecuta `python run_casos.py --evaluar`.

<details>
<summary>Preparación y configuración opcional</summary>

Para preparar el entorno sin ejecutar los casos:

~~~powershell
python run_casos.py --solo-preparar
~~~

En Windows x64 se usa una distribución portátil oficial verificada y se guarda con el modelo en `.runtime/`, sin instalar un servicio del sistema. La primera descarga es de aproximadamente 6.3 GB y requiere espacio adicional para extraerla.

En Linux o macOS debes iniciar un servicio Ollama local; el programa lo reutiliza, pero no instala el runtime automáticamente.

La configuración opcional está en [.env.example](.env.example). `--modelo` prevalece sobre `OLLAMA_MODEL`; `AGENT_MODE` y `OLLAMA_BASE_URL` permiten configurar el modo y el servicio local.

</details>

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

También puedes preguntar **«¿he tenido algun siniestro?»** o **«Yo he tenido algun siniestro?»**, sin conocer un código. El agente lista los registros de la sesión autenticada; el código queda como opción para pedir detalles. [Evidencia de esas consultas reales](entrega/CONSULTAS_HISTORIAL.md).

### Consultas en lote: los 12 casos

Para atender automáticamente todas las consultas de `casos_prueba/casos_prueba.json`, sin escribir los doce mensajes a mano:

~~~powershell
python run_casos.py --evaluar
~~~

El programa las procesa **una tras otra**. Cada caso utiliza su propio rol e identificador como sesión simulada: no se ejecutan todos con el mismo usuario.

Por ejemplo, `CP-01` usa al cliente `C001` para preguntar por el estado de S-5521; `CP-02` usa al cliente `C002` para consultar un choque. El programa atiende ambas y los otros diez casos con la identidad correspondiente.

Las doce respuestas quedan en `salidas_ollama_corregido/respuestas.json`; los informes automáticos se guardan en esa misma carpeta. Los criterios se explican en [Evaluación y consumo](#evaluación-y-consumo).

Los argumentos de rol y usuario **simulan una sesión ya autenticada**. En producción los proporcionaría el servidor; conocer un DNI o escribir otro cargo no concede permisos.

## Cómo funciona

Por ejemplo, C001 pregunta: **«¿En qué estado está mi siniestro S-5521?»**

1. Qwen reconoce que se pide el estado y que el código es S-5521. La identidad C001 viene de la sesión, no del texto de la pregunta.
2. El programa comprueba el código y busca el registro entre los datos que ese cliente puede consultar. En este caso, encuentra que está **en evaluación**.
3. Construye la respuesta con la fuente `siniestros:S-5521` y guarda la consulta, el usuario, las herramientas utilizadas y la respuesta.

Qwen interpreta la pregunta; el programa comprueba los datos y redacta la respuesta. Cuando la consulta lo requiere, también revisa los artículos de los condicionados. Los controles de privacidad, cambios no permitidos y asesoría pueden responder antes de consultar a Qwen.

## Evaluación y consumo

Se opta por una evaluación por código porque comprueba hechos concretos contra los CSV y las condiciones, con criterios más fáciles de explicar y verificar. Qwen también podría evaluar las respuestas, pero no se eligió como evaluador principal: en las pruebas cuestionó respuestas respaldadas, necesita más calibración y añade tiempo y consumo de tokens.

Ejecuta el flujo normal completo con un comando:

~~~powershell
python run_casos.py --evaluar
~~~

El programa:

1. Prepara Ollama y lee las 12 consultas, roles e identificadores de `casos_prueba/casos_prueba.json`.
2. En nueve casos, Qwen interpreta la intención; en tres, actúan controles programados de privacidad, inversión o cambios no permitidos.
3. Consulta CSV y artículos respetando los permisos de sesión, responde con fuentes y registra herramientas, tokens y tiempos.
4. Comprueba las respuestas con reglas programadas y guarda su informe en Markdown y JSON.

Las comprobaciones buscan contradicciones, promesas indebidas y fuentes sin respaldo.

Para revisar respuestas guardadas sin volver a ejecutar el agente:

~~~powershell
python evaluar.py --entrada salidas_ollama_corregido/respuestas.json
~~~

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

Los **tokens** son fragmentos de texto que cuenta Ollama. Los de entrada incluyen tu pregunta y las instrucciones del programa; los de salida corresponden a la interpretación de Qwen, no a la respuesta final que construye el programa.

La **API** es la conexión local entre el programa y Ollama en tu computadora. Consultar no envía los datos a un servicio externo ni requiere una clave de pago.

Si preguntas por **S-5521** y Qwen interpreta **S-5522**, el programa detecta que el código no coincide y le pide corregirlo **una sola vez**. Tú no tienes que repetir la pregunta. Si hay dos intentos, se suman los tokens de ambos.


No se calcula un costo monetario: Ollama local no cobra una tarifa por token.

El lote actual conservado en la entrega usó **5349 tokens de entrada + 513 de salida = 5862 en total** para el agente. Las cuatro consultas adicionales de consola usaron 2537 tokens y se contabilizan por separado.

Las pruebas del programa verifican sus funciones y controles. La evaluación de la entrega revisa las **12 respuestas finales**, también con asistencia de Codex: las doce cumplieron sus comprobaciones. Nueve consultas llamaron a Qwen; tres se resolvieron antes mediante controles de privacidad, recomendaciones de inversión y cambios no permitidos.

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
| [entrega/CONSULTAS_HISTORIAL.md](entrega/CONSULTAS_HISTORIAL.md) | Las cuatro consultas reales de historial, póliza y cobertura |
| [entrega/fuentes_sha256.json](entrega/fuentes_sha256.json) | Huellas para comprobar los archivos de evidencia |

Las nuevas ejecuciones escriben en `salidas_ollama_corregido/`. Esas carpetas de trabajo no forman parte de la entrega publicada. Los artefactos seleccionados están en `entrega/`.

La revisión de contenido se realizó **con asistencia de Codex**, contrastando los CSV y artículos del paquete. No fue una evaluación humana ciega. Coincidió con las comprobaciones automáticas existentes: 12 casos correctos. Esto acredita los casos y controles verificados, no seguridad universal.

## Pruebas del código

- **Evaluación de los 12 casos:** comprueba si las respuestas del agente coinciden con los datos y las condiciones del seguro.
- **Pruebas del código Python:** ejecutan partes del programa para comprobar que funcionen correctamente; por ejemplo, que se bloquee el acceso a siniestros de otro cliente.

~~~powershell
python -m unittest discover -s tests
~~~

## Uso de asistentes de IA

Se utilizó **OpenAI Codex** para analizar el material, diseñar la arquitectura, implementar código y documentación, preparar pruebas y apoyar la verificación de resultados contra los datos y condiciones.

Esto se distingue del modelo de ejecución: **Ollama 0.40.13 con `qwen2.5:7b`**, que interpreta consultas durante el uso del agente. La revisión asistida no sustituye comprender y poder explicar o modificar la solución.
