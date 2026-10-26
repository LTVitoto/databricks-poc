"""FastAPI backend para la Data App del CFO (Rentabilidad ABC & IFRS 18).

Expone `/api/mpm`, `/api/abc-costs` y `/api/corporate-costs` consultando en
vivo las tablas Gold/Silver del Lakehouse via `databricks.sql.connect` (sin
datos de prueba).

`/api/abc-costs` hace JOIN con `silver_maestro_drivers_abc` para traer el
codigo real de `DIMENSION_DRIVER` (1_TIEMPO_OPERATIVO/3_MOVIMIENTO_TRANS/
4_VOLUMEN_UNIDADES): `gold_abc_operational_costs.dimension_driver` guarda el
nombre WMS (Segundos_Efectivos/...), no el codigo del maestro que el
frontend agrupa/filtra en el drill-down de Nivel 2+. `fecha`/`periodo_mes`
se reconstruyen con `DATE_ADD`/`DATE_FORMAT` porque `fecha` esta persistida
como INT (dias desde epoch, el mismo patron de codificacion de Debezium) en
`silver_wms_telemetry`.

`/api/corporate-costs` lee directo `silver_maestro_drivers_abc` filtrado a
`CL_CORP`: esas filas no tienen contraparte en `gold_abc_operational_costs`
(gasto estrategico de presupuesto, no transaccional WMS), por eso el
drill-down de Costos Corporativos usa una fuente separada de Costos WMS.
"""

import os
from typing import Any

from databricks import sql
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

DATABRICKS_SERVER_HOSTNAME = os.environ.get("DATABRICKS_SERVER_HOSTNAME")
DATABRICKS_HTTP_PATH = os.environ.get("DATABRICKS_HTTP_PATH")
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN")
DATABRICKS_CATALOG = os.environ.get("DATABRICKS_CATALOG", "mi_test_catalogo")
DATABRICKS_SCHEMA = os.environ.get("DATABRICKS_SCHEMA", "default")

SQL_MPM = """SELECT Concepto, Monto
FROM default.gold_mpm_reconciliation
ORDER BY Concepto ASC"""

SQL_ABC_COSTS = """SELECT d.DIMENSION_DRIVER AS DIMENSION_DRIVER,
    a.descripcion_recurso AS DESCRIPCION_RECURSO,
    a.costo_asignado_linea AS COSTO_ASIGNADO_AL_OBJETO,
    a.centro_costo_origen AS centro_costo_origen,
    a.cantidad_consumida AS cantidad_consumida,
    a.sku AS sku,
    a.pedido AS pedido,
    DATE_ADD(DATE('1970-01-01'), a.fecha) AS fecha,
    DATE_FORMAT(DATE_ADD(DATE('1970-01-01'), a.fecha), 'yyyy-MM') AS periodo_mes
FROM default.gold_abc_operational_costs a
JOIN default.silver_maestro_drivers_abc d
  ON a.centro_costo_origen = d.CENTRO_COSTO_ORIGEN
 AND a.id_recurso_pool = d.ID_RECURSO_POOL"""

SQL_CORP_COSTS = """SELECT PERIODO_MES AS periodo_mes,
    DIMENSION_DRIVER AS DIMENSION_DRIVER,
    DESCRIPCION_RECURSO AS DESCRIPCION_RECURSO,
    CENTRO_COSTO_ORIGEN AS centro_costo_origen,
    COSTO_ASIGNADO_AL_OBJETO AS COSTO_ASIGNADO_AL_OBJETO
FROM default.silver_maestro_drivers_abc
WHERE CENTRO_COSTO_ORIGEN = 'CL_CORP'"""

app = FastAPI(title="CFO Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_connection():
    return sql.connect(
        server_hostname=DATABRICKS_SERVER_HOSTNAME,
        http_path=DATABRICKS_HTTP_PATH,
        access_token=DATABRICKS_TOKEN,
        catalog=DATABRICKS_CATALOG,
        schema=DATABRICKS_SCHEMA,
    )


def run_query(query: str) -> list[dict[str, Any]]:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/mpm")
def get_mpm_bridge():
    return run_query(SQL_MPM)


@app.get("/api/abc-costs")
def get_abc_costs():
    return run_query(SQL_ABC_COSTS)


@app.get("/api/corporate-costs")
def get_corporate_costs():
    return run_query(SQL_CORP_COSTS)
