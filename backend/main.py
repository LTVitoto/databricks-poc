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

`/api/simulate-ebitda` invoca un Model Serving endpoint real de Databricks
(`DATABRICKS_MODEL_ENDPOINT`, formato `dataframe_split`). El EBITDA base ya
no es un valor fijo: se lee la fila "EBITDA Ajustado" de
`gold_mpm_reconciliation` en cada llamada. Requiere que el endpoint exista y
este READY en el workspace; si `DATABRICKS_MODEL_ENDPOINT` no apunta a un
endpoint real, la llamada falla con HTTP 500 (ver CLAUDE.md).
"""

import os
from typing import Any

import requests
from databricks import sql
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

DATABRICKS_SERVER_HOSTNAME = os.environ.get("DATABRICKS_SERVER_HOSTNAME")
DATABRICKS_HTTP_PATH = os.environ.get("DATABRICKS_HTTP_PATH")
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN")
DATABRICKS_CATALOG = os.environ.get("DATABRICKS_CATALOG", "mi_test_catalogo")
DATABRICKS_SCHEMA = os.environ.get("DATABRICKS_SCHEMA", "default")
DATABRICKS_MODEL_ENDPOINT = os.environ.get("DATABRICKS_MODEL_ENDPOINT")

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


class SimulationPayload(BaseModel):
    volumen_delta_pct: float
    costo_wms_delta_pct: float
    tasa_fx_clp_usd: float


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


def get_current_ebitda() -> float:
    for row in run_query(SQL_MPM):
        if row["Concepto"].endswith("EBITDA Ajustado"):
            return float(row["Monto"])
    raise HTTPException(
        status_code=502,
        detail="No se encontro la fila 'EBITDA Ajustado' en gold_mpm_reconciliation",
    )


@app.post("/api/simulate-ebitda")
def simulate_ebitda(payload_in: SimulationPayload):
    current_ebitda = get_current_ebitda()

    payload = {
        "dataframe_split": {
            "columns": ["volumen_delta", "costo_wms_delta", "tasa_fx"],
            "data": [
                [
                    payload_in.volumen_delta_pct,
                    payload_in.costo_wms_delta_pct,
                    payload_in.tasa_fx_clp_usd,
                ]
            ],
        }
    }
    url = (
        f"https://{DATABRICKS_SERVER_HOSTNAME}/serving-endpoints/"
        f"{DATABRICKS_MODEL_ENDPOINT}/invocations"
    )

    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {DATABRICKS_TOKEN}"},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        predicted_ebitda = float(response.json()["predictions"][0])
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error invocando el Model Serving endpoint ({url}): {exc}",
        ) from exc

    return {
        "current_ebitda": current_ebitda,
        "predicted_ebitda": predicted_ebitda,
        "delta_usd": predicted_ebitda - current_ebitda,
    }
