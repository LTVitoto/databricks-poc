# poc-cdc-databricks — CLAUDE.md

PoC de integración CDC en tiempo real: PostgreSQL (simulador SAP S/4HANA) → Debezium → MinIO (Parquet) → script puente → Databricks Volume → Auto Loader/PySpark → Delta (capa Silver).

Rol operativo: Programador Principal (Senior SWE), bajo directrices del Arquitecto Líder de Datos. Restricción de comunicación: explicar arquitecturas/flujos SIEMPRE con diagramas `mermaid` (sequenceDiagram / graph TD), nunca con párrafos largos.

## REGLAS DE COMUNICACIÓN Y QA

A partir de ahora, por cada iteración, refactorización o tarea completada, tienes ESTRICTAMENTE PROHIBIDO responder únicamente con confirmaciones cortas o robóticas. Tu respuesta de salida debe estructurarse SIEMPRE con estos 3 puntos exactos:

- **Qué se hizo:** Breve resumen técnico de los archivos modificados y la arquitectura o lógica implementada.
- **Resultado Esperado:** Qué impacto tiene esto en el sistema (ej. nueva UI renderizada, payload de backend modificado).
- **Cómo Validarlo (QA):** Instrucciones exactas, precisas y paso a paso para que el usuario valide el cambio localmente (ej. clics exactos en la UI, URLs a visitar, comandos curl para probar el backend, o qué métricas observar).

## Build & Run Commands

```bash
# 1. Levantar infraestructura (desde la raíz del proyecto)
docker compose up -d
docker compose ps   # zookeeper y kafka deben llegar a "healthy" antes de debezium-connect

# Reinicio de recuperación si algún contenedor quedó "Exited"
docker compose up -d zookeeper   # esperar healthy antes de seguir
docker compose up -d kafka       # esperar healthy antes de seguir
docker compose up -d debezium-connect
docker compose logs -f debezium-connect   # auditar en caso de fallo

# 2. Probar que la API de Kafka Connect responde
curl -s http://localhost:8083/ | jq .
curl -s http://localhost:8083/connector-plugins | jq '.[].class'   # confirmar S3SinkConnector cargado

# 3. Registrar el conector de ORIGEN (Postgres -> Kafka) — idempotente, 409 si ya existe
curl -s -X POST -H "Content-Type: application/json" \
  --data @connectors/postgres-source.json \
  http://localhost:8083/connectors | jq .

# 4. Registrar el conector de DESTINO (Kafka -> MinIO S3, Parquet)
curl -s -X POST -H "Content-Type: application/json" \
  --data @connectors/s3-sink-parquet.json \
  http://localhost:8083/connectors | jq .

# Verificar estado de ambos conectores
curl -s http://localhost:8083/connectors/PostgresConnector/status | jq .
curl -s http://localhost:8083/connectors/S3SinkConnector/status | jq .

# 5. Entorno Python (venv local, no usar --break-system-packages)
python3 -m venv .venv && source .venv/bin/activate
pip install boto3 black flake8

# 6. Script puente MinIO -> Databricks Volume
# Opción A (contenedor, recomendado): levantado por docker compose up -d (ver abajo).
# Opción B (local, debug puntual):
source .venv/bin/activate
python3 sync_minio_databricks.py           # loop continuo (poll cada 5s)
python3 sync_minio_databricks.py --once    # un solo ciclo (usado en pruebas E2E)

# 7. Workflow Silver -> Gold (notebook_task encadenados) en Databricks
databricks jobs run-now 204650251307272
databricks jobs get-run <run_id>   # life_cycle_state debe llegar a TERMINATED/SUCCESS

# Consulta ad-hoc del resultado (Serverless Starter Warehouse)
databricks api post /api/2.0/sql/statements --json '{
  "warehouse_id": "9d616c43551f0723",
  "statement": "SELECT * FROM mi_test_catalogo.default.silver_sap_clientes_kna1 ORDER BY kunnr",
  "wait_timeout": "30s"
}'
```

Credenciales/entorno ya definidos (no crear nuevos):
- Postgres: `sapadmin` / `sappassword` @ `localhost:5432` / db `sapdb`.
- MinIO: `minioadmin` / `minioadmin` @ `localhost:9000` (consola `9001`), bucket `landing-zone` (ya existe).
- Databricks CLI: ya autenticado localmente (perfil `DEFAULT`, workspace AWS, Unity Catalog activo). **No pedir ni regenerar tokens.**
- Notebooks: `.../poc-cdc-databricks/silver_merge` y `.../poc-cdc-databricks/gold_ifrs18_pl`.
- Workflow único persistido: `job_id = 204650251307272` (`poc-cdc-ifrs18-workflow`, Task 1 `silver_merge` → Task 2 `gold_ifrs18_pl`). Los jobs standalone anteriores (`1051132190882166`, `1048150931946076`) fueron **borrados** — no reutilizar esos IDs.
- SQL Warehouse para consultas ad-hoc: `warehouse_id = 9d616c43551f0723` (Serverless Starter Warehouse).

### Incidentes conocidos y su fix (no reintroducir)

- **Zookeeper/Kafka mueren al arrancar con `NullPointerException` en `CgroupV2Subsystem`.** Causa: el host corre cgroup v2 (WSL2) y el JRE Zulu 11 embebido en las imágenes Confluent 7.3.0 tiene un bug al leer métricas de contenedor para el agente JMX local. Fix ya aplicado en `docker-compose.yml`: `KAFKA_OPTS=-XX:-UseContainerSupport` en `zookeeper`, `kafka` y `debezium-connect`. Si se reconstruye el compose desde cero, no quitar esta variable.
- **El healthcheck de zookeeper no puede usar `ruok`**: la whitelist de comandos de 4 letras de esta imagen solo permite `srvr`. El healthcheck usa `echo srvr | nc -w 2 localhost 2181 | grep -qi Mode`.
- **El plugin `S3SinkConnector` NO viene preinstalado** en `quay.io/debezium/connect:2.4`. Se descargó una vez desde Confluent Hub (`confluentinc-kafka-connect-s3-12.1.14.zip`) y sus jars viven en `./connect-plugins/` (gitignorable si el repo crece, ~75MB), montado como volumen de solo lectura en `/kafka/connect/kafka-connect-s3` dentro del servicio `debezium-connect`. Si se borra esa carpeta, re-descargar desde `https://hub-downloads.confluent.io/api/plugins/confluentinc/kafka-connect-s3/versions/12.1.14/confluentinc-kafka-connect-s3-12.1.14.zip` y copiar `lib/*.jar`.
- **`databricks fs mkdir` sobre un Volume crea directorios anidados en una sola llamada** (equivalente a `mkdir -p`) y es idempotente (no falla si ya existe) — por eso el script puente llama `mkdir` antes de cada `cp` sin chequear existencia previa.

## Linter / Formatting (Python)

- Formateador: `black` (line-length 88).
- Linter: `flake8`, configurado en `.flake8` con `max-line-length = 88` (igualado a black; sin este archivo, flake8 por defecto usa 79 y choca con black).
- Ambos instalados en `.venv` (ver Build & Run Commands). Ejecutar antes de cada commit de código Python:
  ```bash
  source .venv/bin/activate
  black sync_minio_databricks.py databricks/silver_merge.py
  flake8 sync_minio_databricks.py databricks/silver_merge.py
  ```
- Type hints obligatorios en funciones públicas de `sync_minio_databricks.py` y `databricks/silver_merge.py` (claridad sobre el contrato MinIO↔Databricks y sobre el DataFrame transform).

## Architecture Guidelines

Estructura de directorios objetivo:

```
poc-cdc-databricks/
├── docker-compose.yml
├── init.sql
├── CLAUDE.md
├── .flake8
├── .venv/                        # entorno Python local (no commitear)
├── connect-plugins/               # jars del S3SinkConnector (Confluent Hub, no commitear)
├── connectors/
│   ├── postgres-source.json      # PostgresConnector (Debezium)
│   └── s3-sink-parquet.json      # S3SinkConnector (formato Parquet)
├── sync_minio_databricks.py      # script puente (Opción A)
├── .sync_state.json              # estado de idempotencia del script puente (no commitear)
└── databricks/
    └── silver_merge.py           # Auto Loader + MERGE INTO (capa Silver; subido como notebook)
```

Directrices del Arquitecto (vinculantes):

- **Ordenamiento CDC estrictamente por `ts_ms`.** Nunca confiar en el orden de llegada de archivos/mensajes; toda deduplicación intra-microbatch usa `Window.partitionBy(kunnr).orderBy(col("ts_ms").desc())` + `row_number() == 1`.
- **Borrado lógico vía `op = 'd'`.** El `MERGE INTO` debe interpretar el payload de Debezium (`op`: `c`/`u`/`r`=upsert, `d`=delete) y ejecutar `WHEN MATCHED AND source.op = 'd' THEN DELETE`.
- **Checkpoints de Spark:** un path de checkpoint dedicado y persistente por stream, bajo el mismo Volume de Unity Catalog (nunca en `/tmp` ni en DBFS raíz):
  `/Volumes/mi_test_catalogo/default/paquet_demo/_checkpoints/silver_kna1/`
- **Landing/Volume de destino:** usar el Volume ya existente `mi_test_catalogo.default.paquet_demo` como punto de llegada de los Parquet subidos por el script puente (evitar crear volúmenes duplicados).
- **Compute:** este workspace es AWS + Unity Catalog con una **Serverless Starter Warehouse** disponible (no es Community Edition). Usar serverless (warehouse o jobs serverless) por defecto para el job de Silver; si en algún punto el entorno cambia a Community Edition, está prohibido depender de Serverless y se debe usar un cluster clásico explícito.
- **Idempotencia del script puente:** debe poder re-ejecutarse sin duplicar archivos ya subidos (comparar por nombre/hash antes de `databricks fs cp`).
- **Tabla Delta destino:** `mi_test_catalogo.default.silver_sap_clientes_kna1`, clave de negocio `kunnr`. Incluye columna `event_ts_ms` (el `ts_ms` de nivel raíz del envelope de Debezium) como guard: el `MERGE INTO` solo actualiza si `source.event_ts_ms >= target.event_ts_ms`, protegiendo contra micro-batches fuera de orden entre ejecuciones del job.
- **`ts_ms` de negocio vs. `ts_ms` de Debezium:** el campo `ts_ms` dentro de `after`/`before` es la columna de la tabla origen (`DEFAULT CURRENT_TIMESTAMP`, no se actualiza sola en `UPDATE`). El `ts_ms` de nivel raíz del envelope es el tiempo de captura de Debezium y es el único campo válido para ordenar/deduplicar CDC.
- **Ejecución del job Silver:** notebook subido a `/Workspace` (no un `spark_python_task` con `.py` plano) porque los jobs de tipo `notebook_task` usan compute **serverless** sin configuración adicional en este workspace; confirmado funcionando end-to-end.

### Estado de validación E2E (última corrida)

Prueba de negocio Australia→Brasil ejecutada y verificada en `mi_test_catalogo.default.silver_sap_clientes_kna1`:
- v1 `MERGE`: INSERT snapshot AU (`1000000001`).
- v2 `MERGE`: UPDATE AU (`ort01`→Sydney, `name1`→"...(HQ)").
- v3 `MERGE`: INSERT BR (`1000000002`) + DELETE AU en el mismo batch.
- Estado final: 1 fila, solo `1000000002` (Brasil). Confirmado con `DESCRIBE HISTORY` y `SELECT *`.

## Fase 2: Consolidación Financiera IFRS

Objetivo: inyectar datos financieros simulados en `sapdb` para, sobre el mismo pipeline CDC ya validado, calcular MPMs (ej. EBITDA ajustado IFRS 18), eliminaciones intercompany (IFRS 10) y reporte por segmentos (IFRS 8).

### Tablas nuevas en Postgres

- **`vbrk`** (cabecera facturación): PK `VBELN`. FK `KUNNR` → `sap_clientes_kna1.kunnr`. Campos: `BUKRS` (AU/BR), `FKDAT`, `NETWR`, `WAERK`.
- **`vbrp`** (posiciones facturación): PK compuesta (`VBELN`, `POSNR`). FK `VBELN` → `vbrk`. Campos: `MATNR`, `MATKL` (grupo material/segmento), `PRCTR`, `NETWR`.
- **`acdoca`** (Universal Journal simplificado): PK compuesta (`RCLNT`, `RLDNR`, `RBUKRS`, `GJAHR`, `BELNR`, `DOCLN`). Campos: `RACCT`, `SEGMENT` (IFRS 8), `PRCTR`, `FKBER`, `HSL` (moneda local), `KSL` (moneda grupo), `RASSC` (sociedad asociada intercompany, IFRS 10). `BELNR = VBELN` cuando el asiento se origina en una venta (FK lógica a `vbrk`); líneas sin venta (intereses, inversión, FX, impuestos) no tienen contraparte en `vbrk`.
- **`ifrs18_fsv_map`** (maestro de mapeo semántico): PK `RACCT`. Campos: `ACCOUNT_DESC`, `IFRS18_CATEGORY` (`Operating`/`Investing`/`Financing`/`Taxes`), `IS_FX_ACCOUNT`, `MPM_TAG` (ej. `EBITDA_ADJUSTED`, nullable). Debe poblarse **antes** de generar `acdoca` (las cuentas deben preexistir en el maestro).

### Reglas de generación (`generate_financial_data.py`)

- 5000 líneas en `acdoca`: 2500 con `RBUKRS='AU'`, 2500 con `RBUKRS='BR'`, `GJAHR=2026`, `RLDNR='0L'`, `RCLNT='100'`.
- Intercompany IFRS 10: subconjunto de ventas AU→BR con `RASSC` apuntando a la sociedad contraparte, para pruebas futuras de eliminación de consolidación.
- Variabilidad de montos por segmento (IFRS 8): distribuciones de `HSL`/`KSL` claramente distintas entre AU (minería) y BR (industrial) — no usar el mismo rango aleatorio para ambas.
- Líneas sin `VBELN` (no derivadas de venta): gastos de intereses (`Financing`), resultado de inversiones (`Investing`), diferencias de cambio (cuentas FX explícitas en `ifrs18_fsv_map`, mapeadas a `Operating`/`Investing`/`Financing` según la cuenta de origen, nunca todas a la misma categoría), impuestos (`Taxes`).
- Script idempotente: `CREATE TABLE IF NOT EXISTS` + `TRUNCATE` antes de poblar (evita duplicar si se re-ejecuta).

### Ejecución (`generate_financial_data.py`)

- `vbrk.kunnr` **no** tiene FK real a `sap_clientes_kna1` (solo conceptual en el ER): el cliente AU de la Fase 1 fue borrado en la prueba E2E previa, así que una FK real habría roto la generación. `kunnr` es un código informativo.
- El script corre dentro de un contenedor efímero en la red `poc-cdc-databricks_default` (`docker run --network ... python:3.12-slim ...`), **no** desde el host: el port-forward `5432:5432` de WSL2 devuelve un error de autenticación espurio (mensaje en español/Latin-1, `UnicodeDecodeError` en psycopg2) aunque el password es correcto — confirmado probando con `docker exec` + IP del contenedor. No perder tiempo re-depurando esa ruta; usar siempre un contenedor en la misma red para scripts Python que hablen con `postgres-sap`.

### Reconfiguración de Debezium para las tablas nuevas

- **No usar un PUT de `table.include.list` sobre el conector existente.** Postgres solo decodifica cambios de tablas que ya estaban en la `PUBLICATION` en el momento del INSERT; agregar la tabla después no recupera lo ya escrito. Se eliminaron `PostgresConnector`/`S3SinkConnector`, se borró el slot (`debezium_kna1_slot`) y la publicación (`dbz_publication`), y se recrearon como **`PostgresConnectorFull`** (slot `debezium_full_slot`, `table.include.list` con las 5 tablas) y **`S3SinkConnectorFull`** (`topics` con los 5 topics) para forzar un snapshot inicial completo.
- `S3SinkConnectorFull` usa `flush.size=200` (no `1`: con 5000+ filas generaría miles de archivos) + `rotate.schedule.interval.ms=10000` + `timezone=UTC` (sin esto, topics de bajo volumen como `ifrs18_fsv_map`, 10 filas, nunca alcanzan `flush.size` y no se escriben nunca a MinIO) + `consumer.override.auto.offset.reset=earliest` (para no saltarse el snapshot de los topics nuevos).

### Capa Gold (`databricks/gold_ifrs18_pl.py`)

- Lee `acdoca` e `ifrs18_fsv_map` en batch (no Auto Loader; es un cálculo puntual, no un stream continuo), dedup por `ts_ms` de envelope igual que Silver, `JOIN` por `RACCT`, filtra `RASSC IS NOT NULL` (eliminación IFRS 10), agrega `-SUM(KSL)` por `IFRS18_CATEGORY` (signo invertido para presentar utilidad en positivo) y por `RBUKRS` dentro de `Operating`, con reconciliación a EBITDA ajustado sumando de vuelta las cuentas con `MPM_TAG='EBITDA_ADJUSTED'`.
- Notebook subido a `/Workspace/Users/victor.figueroa.pinto@gmail.com/poc-cdc-databricks/gold_ifrs18_pl`. Resultado se imprime y se retorna vía `dbutils.notebook.exit` (recuperable con `databricks jobs get-run-output <task_run_id>`). **Superseded:** el job standalone original (`poc-cdc-gold-ifrs18-pl`) fue borrado; ver "Despliegue y Orquestación" para el Workflow actual.

### Estado: ejecutado y validado (5000/5000 ACDOCA, 2500 AU/2500 BR)

P&L por categoría IFRS 18 (consolidado, IC eliminado): Operating +4,278,678.98 · Investing +391,251.70 · Financing −630,679.19 · Taxes −308,102.37.
Operating Profit / EBITDA ajustado por sociedad (IFRS 8): AU 4,284,419.89 / 4,585,582.08 · BR −5,740.91 / 83,235.02.
Intercompany eliminado (IFRS 10): AU→BR, 242 líneas, −856,758.14 KSL.

## Contexto de CLI

- Databricks CLI v1.22.1 ya instalado, autenticado y configurado (`~/.databrickscfg`, perfil `DEFAULT`). No ejecutar `databricks auth login` ni solicitar tokens nuevos.
- Catálogo activo: `mi_test_catalogo` (Unity Catalog, metastore AWS us-east-2).
- Antes de cada sesión larga de automatización Databricks, considerar `databricks aitools install` (sugerido por el propio CLI, no bloqueante para este PoC).

## Despliegue y Orquestación

### Levantar el proyecto desde cero

```bash
docker compose up -d
```

Un solo comando levanta: `postgres-sap` → `zookeeper`/`kafka` (healthchecks con el fix `KAFKA_OPTS=-XX:-UseContainerSupport`) → `debezium-connect` (plugin S3 montado desde `./connect-plugins`) → `minio-landing` → **`bridge`** (contenedor del script puente, build desde `Dockerfile.bridge`, loop continuo cada `SYNC_POLL_INTERVAL=10`s). Requiere `~/.databrickscfg` existente en el host (se monta read-only, perfil `DEFAULT`) — no crea credenciales nuevas.

Pasos que **no** están automatizados en `docker compose up` (quedan como comandos CLI documentados arriba, a propósito, para mantener la infraestructura separada de la configuración de negocio): registrar los conectores de Debezium, crear el bucket de MinIO, generar los datos financieros, y desplegar/ejecutar el Workflow de Databricks.

### Contenedor del script puente (`bridge`)

- `Dockerfile.bridge`: `python:3.12-slim` + Databricks CLI standalone (instalado vía `setup-cli` oficial, no el paquete `databricks-cli` de pip, que está deprecado) + `boto3`.
- Autenticación: monta `${HOME}/.databrickscfg:/root/.databrickscfg:ro` — reusa el perfil `DEFAULT` ya configurado en el host.
- Estado de idempotencia persistido fuera del contenedor: `./bridge-state:/app/state` (`SYNC_STATE_FILE=/app/state/.sync_state.json`), sobrevive a recreaciones del contenedor.
- `restart: unless-stopped` para resiliencia ante caídas del daemon Docker.
- Comandos útiles: `docker compose logs -f bridge`, `docker compose restart bridge`.

### Workflow de Databricks (`databricks_job.json`)

- Desplegado con `databricks jobs create --json @databricks_job.json` → `job_id = 204650251307272` (`poc-cdc-ifrs18-workflow`).
- Dos tareas `notebook_task` encadenadas: `silver_merge` → (`depends_on`) → `gold_ifrs18_pl`. Compute serverless, sin cluster explícito (igual que los jobs individuales de la Fase 2).
- Ejecutado exitosamente end-to-end: ambas tasks `TERMINATED`/`SUCCESS` (run `40636719998051`).
- Reemplaza a los dos jobs standalone de la Fase 2 (`poc-cdc-silver-merge`, `poc-cdc-gold-ifrs18-pl`), que fueron **borrados** — no volver a ejecutarlos ni recrearlos por separado; todo recálculo Silver/Gold pasa por este Workflow único.

### Data Quality en Unity Catalog (tabla Gold)

- `databricks/gold_ifrs18_pl.py` ahora persiste una tabla Delta gobernada `mi_test_catalogo.default.gold_acdoca_ifrs18` (ACDOCA enriquecido con `ifrs18_fsv_map`, **sin** filtrar intercompany — la eliminación IFRS 10 se aplica solo al agregar el P&L, no al escribir la tabla, para no perder trazabilidad de las líneas IC).
- Restricciones `CHECK` aplicadas vía `ALTER TABLE ... ADD CONSTRAINT` (idempotente: atrapa el error si la constraint ya existe):
  - `chk_ifrs18_category`: `ifrs18_category IN ('Operating', 'Investing', 'Financing', 'Taxes')`.
  - `chk_ksl_not_null`: `ksl IS NOT NULL`.
- Verificación: `SHOW TBLPROPERTIES mi_test_catalogo.default.gold_acdoca_ifrs18` debe listar ambas `delta.constraints.*`.

## Estado del proyecto: Entregado a Negocio

El PoC técnico (CDC + Fase 2 IFRS + orquestación) está cerrado. Esta fase es la capa de BI sobre la tabla Gold ya gobernada, para consumo del CFO.

### Dashboard del CFO (`cfo_dashboard_queries.sql`)

3 consultas contra `mi_test_catalogo.default.gold_acdoca_ifrs18`, validadas contra el Warehouse (`9d616c43551f0723`):
1. **Waterfall P&L IFRS 18** — Operating → Investing → Financing → Taxes → Resultado Neto (columna `orden` para fijar la secuencia en el chart).
2. **KPI EBITDA Ajustado (MPM) por sociedad** — IFRS 8, AU vs BR, con addback de depreciación (`MPM_TAG='EBITDA_ADJUSTED'`).
3. **Detalle Intercompany eliminado** — IFRS 10, por cuenta y sociedad contraparte.

Cómo crear el Dashboard:
```text
1. Abrir el SQL Editor (enlace 3 de get_ui_links.py).
2. Pegar cada consulta de cfo_dashboard_queries.sql por separado, ejecutar, "Add visualization".
   - Consulta 1 -> tipo Waterfall (x=categoria ordenado por `orden`, y=resultado_ksl).
   - Consulta 2 -> tipo Bar/Tabla agrupada por `sociedad`.
   - Consulta 3 -> tipo Tabla (detalle).
3. "Add to Dashboard" en cada visualización -> nuevo Dashboard "CFO - IFRS 18 P&L".
```

### Enlaces de validación (`get_ui_links.py`)

Script que construye vía Databricks CLI (`auth env`, `jobs list-runs`) las URLs directas:
1. Data Explorer (Unity Catalog) → esquema y Data Quality de la tabla Gold.
2. Job Run exitoso más reciente del Workflow (`job_id=204650251307272`).
3. SQL Editor.

Ejecutar con `python3 get_ui_links.py` (requiere `.venv` activo) cada vez que se necesiten enlaces frescos — el run-link cambia con cada ejecución del Workflow.

## Control de Versiones

Repositorio Git local inicializado (rama `main`), commit fundacional: `feat: MVP fundacional CDC a Databricks con consolidación IFRS 18`.

**Se sube:**
- Código: `sync_minio_databricks.py`, `generate_financial_data.py`, `get_ui_links.py`, `create_cfo_dashboard.py`.
- Infra: `docker-compose.yml`, `Dockerfile.bridge`, `init.sql`.
- Configuración Debezium: `connectors/*.json`.
- Notebooks Databricks: `databricks/silver_merge.py`, `databricks/gold_ifrs18_pl.py`.
- Orquestación: `databricks_job.json`.
- BI: `cfo_dashboard_queries.sql`.
- Docs/tooling: `CLAUDE.md`, `.flake8`, `.gitignore`.

**Se excluye (`.gitignore`):**
- `.venv/` — entorno Python local, reconstruible con `pip install`.
- `bridge-state/`, `.sync_state.json` — estado de idempotencia local del script puente.
- `connect-plugins/` — jars del S3SinkConnector (~75MB, re-descargables desde Confluent Hub, ver sección de incidentes).
- `*.parquet`, `*.csv` — datos, nunca código.
- `.env`, `*.env`, `.databrickscfg` — credenciales. Ningún script de este repo escribe tokens a disco: el Databricks PAT se lee en runtime vía `databricks auth env` (CLI ya autenticado localmente) y nunca se persiste en un archivo del proyecto.

Nota: las credenciales de Postgres/MinIO en `docker-compose.yml` (`sapadmin/sappassword`, `minioadmin/minioadmin`) son defaults de desarrollo local intencionales, no secretos reales — se suben a propósito como parte de la infraestructura reproducible del PoC.

**Push a GitHub:** pendiente de credenciales del usuario (PAT + nombre de repositorio) — por política de seguridad, el PAT no se genera ni se solicita de forma autónoma; se pide explícitamente por chat antes de configurar el remoto.

## Fase 4: Motor de Rentabilidad ABC (Costeo Basado en Actividades)

Nueva rama de negocio (Chile, CLP) independiente de Farma/IFRS: calcula EBITDA Operacional y EBITDA Ajustado deduciendo costos logísticos (WMS) y corporativos estratégicos del Resultado Operacional SAP.

- **Maestro de drivers** (`CL_Drivers_ABC_Full.xlsx`, subido manualmente a `s3://landing-zone/bronze/abc_drivers/`): 4 pestañas (`CL_CD0100/0200/0300` logísticas + `CL_CORP` estratégica), consolidadas por `databricks/ingest_abc_drivers.py` en `silver_maestro_drivers_abc` (28 filas). Nombres de columna del Excel saneados (`CAPACIDAD_MENSUAL (Input)` → `CAPACIDAD_MENSUAL_Input`, Delta no permite espacios/paréntesis). Requiere `%pip install openpyxl` (no viene en el runtime base).
- **Telemetría WMS simulada** (`generate_wms_telemetry.py` → Postgres `wms_telemetry`, 2997 filas/30 días): cada evento referencia el `ID_RECURSO_POOL` exacto del maestro (no solo la unidad de medida) — "Segundos_Efectivos" tiene **dos** pools (`DRV_MOD_CUADRILLA`, `DRV_MOD_TRIAJE`); sin este detalle el JOIN del motor ABC haría fan-out y duplicaría costo. Capturado vía el mismo patrón de siempre: conector fuente recreado (`PostgresConnectorFull3`, slot nuevo) + sink actualizado. `databricks/silver_wms_telemetry.py` materializa `silver_wms_telemetry`.
- **Motor ABC** (`databricks/abc_costing_engine.py`): `JOIN` 1:1 por (`centro_costo_origen`, `id_recurso_pool`) entre `silver_wms_telemetry` y `silver_maestro_drivers_abc` (excluye `CL_CORP`, que no tiene contraparte WMS). `costo_asignado_linea = cantidad_consumida * TASA_UNITARIA_CALCULADA`. Resultado en `gold_abc_operational_costs` (2997 filas, costo total 4,658,872.62).
- **Puente MPM** (`databricks/mpm_reconciliation.py` → `gold_mpm_reconciliation`): Resultado Operacional (`gold_acdoca_ifrs18`, Operating + IC eliminado) → EBITDA Operacional (− costos WMS) → EBITDA Ajustado (− `SUM(COSTO_TOTAL_CLP_Input)` de `CL_CORP`). **Nota de escala:** `ksl` está en moneda grupo (fx aplicado en Fase 2) y los costos ABC/CL_CORP están en CLP nominal del Excel — este PoC no convierte FX entre ambos; el objetivo es validar la mecánica del puente (verificada aritméticamente), no la cifra final en una sola moneda real.
- Todas las tablas/scripts de esta fase pendientes de commit a GitHub.
