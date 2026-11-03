# Consultas reales de historial, póliza y cobertura

**Validación:** 03/11/2026. Modelo local qwen2.5:7b. Sesión simulada cliente C001, mantenida durante cuatro consultas en la misma consola. Fecha del ejercicio: 15/10/2026. Las preguntas son independientes; se conserva la identidad, no una memoria de conversación.

Se comprobó que puede listar el historial y las pólizas propias sin exigir un código, y resumir el producto vehicular sin inventar un evento ni mencionar una cirugía. Las solicitudes de terceros y cambios no permitidos siguen cubiertas por los doce casos y las pruebas de aislamiento.

## Preguntas y respuestas exactas

### 1. ¿he tenido algun siniestro?

Sí, encontré 1 siniestro registrado en tus pólizas:
- S-5521, póliza POL-1001 (vehicular): ocurrió el 2026-10-02; estado registrado: en evaluación; última actualización: 2026-10-09. [siniestros:S-5521] [polizas:POL-1001]
Puedes indicar el código de un siniestro para consultar sus detalles.

Fuentes: polizas:POL-1001; siniestros:S-5521

**Medición de esta consulta:** 1 llamada real; 579 tokens de entrada + 55 de salida = 634; 3.402 segundos del modelo.

### 2. Yo he tenido algun siniestro?

Sí, encontré 1 siniestro registrado en tus pólizas:
- S-5521, póliza POL-1001 (vehicular): ocurrió el 2026-10-02; estado registrado: en evaluación; última actualización: 2026-10-09. [siniestros:S-5521] [polizas:POL-1001]
Puedes indicar el código de un siniestro para consultar sus detalles.

Fuentes: polizas:POL-1001; siniestros:S-5521

**Medición de esta consulta:** 1 llamada real; 579 tokens de entrada + 55 de salida = 634; 3.175 segundos del modelo.

### 3. dime cual es mi poliza

Encontré estas pólizas en los registros a los que tienes acceso:
- POL-1001: Auto Total (vehicular), estado vigente, vigencia del 2026-01-15 al 2027-01-14. [polizas:POL-1001]

Fuentes: polizas:POL-1001

**Medición de esta consulta:** 1 llamada real; 577 tokens de entrada + 54 de salida = 631; 3.342 segundos del modelo.

### 4. deseo consultar sobre mi seguro vehicular, cual es su cobertura

La póliza POL-1001 (Auto Total) figura vigente, con vigencia del 2026-01-15 al 2027-01-14. [polizas:POL-1001]
Resumen general de Auto Total, según su condicionado:
- Daño propio por choque, vuelco o despiste: Sí. [condicionados/vehicular.md, Artículo 1]
- Robo total del vehículo: Sí. [condicionados/vehicular.md, Artículo 1]
- Robo parcial de accesorios: Sí. [condicionados/vehicular.md, Artículo 1]
- Rotura de lunas: Sí (sin deducible). [condicionados/vehicular.md, Artículo 1]
- Incendio: Sí. [condicionados/vehicular.md, Artículo 1]
- Responsabilidad civil frente a terceros: Hasta S/ 100,000. [condicionados/vehicular.md, Artículo 1]
- Auto de reemplazo: Hasta 10 días. [condicionados/vehicular.md, Artículo 1]
Suma asegurada registrada: S/ 52,000.00. [polizas:POL-1001]
Deducible registrado: S/ 600.00. [polizas:POL-1001]
Este resumen describe el producto; no confirma cobertura de un evento ni una indemnización aprobada.

Fuentes: polizas:POL-1001; condicionados/vehicular.md, Artículo 1; condicionados/condiciones_generales.md, Artículo 1

**Medición de esta consulta:** 1 llamada real; 585 tokens de entrada + 53 de salida = 638; 3.446 segundos del modelo.

## Contraste y alcance

Los CSV relacionan a C001 con POL-1001 Auto Total, vigente del 15/01/2026 al 14/01/2027, suma asegurada S/52,000 y deducible S/600. Su siniestro registrado S-5521 ocurrió el 02/10/2026 y está en evaluación, con actualización del 09/10/2026. El artículo 1 vehicular respalda las siete filas del resumen Auto Total; la respuesta distingue ese resumen de una aprobación de indemnización.

Las cuatro consultas tuvieron una llamada cada una y sumaron 2537 tokens. Se verificaron las identidades, fuentes, orden de eventos y contadores de API. Esta consola se contabiliza aparte del lote de 12; sus registros originales permanecen locales. La revisión fue asistida por Codex, no una evaluación humana ciega.

La suite actual tiene 216 pruebas aprobadas. La autenticación de consola sigue siendo una demostración; una consulta lista solo los registros disponibles y no garantiza conocer toda la historia del cliente fuera de estos datos.
