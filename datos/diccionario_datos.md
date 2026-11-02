# Diccionario de datos

Todos los archivos están en formato CSV, codificación UTF-8, separador coma y fechas en formato `AAAA-MM-DD`. Los montos están en soles (S/). Todos los datos son ficticios.

Las tablas simulan las que la aseguradora tiene en su plataforma de datos (BigQuery). Se pueden consultar con SQL en local, por ejemplo con DuckDB:

```sql
SELECT * FROM read_csv_auto('datos/polizas.csv') WHERE cliente_id = 'C001';
```

## clientes.csv

| Campo | Tipo | Descripción |
| --- | --- | --- |
| cliente_id | texto | Identificador del cliente (C001, C002, ...) |
| nombres | texto | Nombres |
| apellidos | texto | Apellidos |
| dni | texto | Documento de identidad (8 dígitos) |
| fecha_nacimiento | fecha | Fecha de nacimiento |
| distrito | texto | Distrito de residencia |
| telefono | texto | Teléfono celular |
| email | texto | Correo electrónico |
| fecha_alta | fecha | Fecha en que se registró como cliente |

## polizas.csv

| Campo | Tipo | Descripción |
| --- | --- | --- |
| poliza_id | texto | Identificador de la póliza (POL-XXXX) |
| cliente_id | texto | Titular de la póliza (relación con clientes) |
| ramo | texto | vehicular, salud o vida |
| producto | texto | Nombre comercial del producto (ver condicionados) |
| fecha_inicio | fecha | Inicio de vigencia |
| fecha_fin | fecha | Fin de vigencia (inclusive) |
| prima_mensual_soles | decimal | Prima mensual |
| suma_asegurada_soles | decimal | Suma asegurada |
| deducible_soles | decimal | Deducible por siniestro |
| estado | texto | vigente, vencida o anulada |
| placa_vehiculo | texto | Placa del vehículo (solo ramo vehicular) |

## siniestros.csv

| Campo | Tipo | Descripción |
| --- | --- | --- |
| siniestro_id | texto | Identificador del siniestro (S-XXXX) |
| poliza_id | texto | Póliza afectada (relación con polizas) |
| fecha_ocurrencia | fecha | Fecha en que ocurrió el evento |
| fecha_aviso | fecha | Fecha en que el cliente avisó a la aseguradora |
| tipo_evento | texto | Tipo de evento |
| descripcion | texto | Descripción registrada al momento del aviso (texto libre ingresado por el cliente o el canal de atención) |
| monto_reclamado_soles | decimal | Monto solicitado |
| monto_aprobado_soles | decimal | Monto aprobado (vacío si aún no hay decisión) |
| estado | texto | registrado, en_evaluacion, aprobado, pagado o rechazado |
| motivo_rechazo | texto | Motivo del rechazo (solo si estado = rechazado) |
| clausula_referencia | texto | Cláusula del condicionado que sustenta el rechazo |
| fecha_ultima_actualizacion | fecha | Última actualización del expediente |

## asesores.csv

| Campo | Tipo | Descripción |
| --- | --- | --- |
| asesor_id | texto | Identificador del asesor (ASE01, ASE02) |
| nombres | texto | Nombres |
| apellidos | texto | Apellidos |
| rol | texto | Rol en la empresa |
| email | texto | Correo corporativo |

## Relaciones

```
clientes (cliente_id) 1 ── N polizas (cliente_id)
polizas  (poliza_id)  1 ── N siniestros (poliza_id)
```
