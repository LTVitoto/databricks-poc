"""FastAPI backend para la Data App del CFO (Rentabilidad ABC & IFRS 18).

Expone `/api/mpm` y `/api/abc-costs`. La conexion a Databricks SQL Warehouse
queda configurada via variables de entorno (ver `.env.example`), pero por
ahora los endpoints devuelven datos de prueba con la misma forma que las
tablas Gold (`gold_mpm_reconciliation` / `gold_abc_operational_costs`) --
el wiring a datos reales via `get_connection()` queda para una fase
posterior.
"""

import os

from databricks import sql
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

DATABRICKS_SERVER_HOSTNAME = os.environ.get("DATABRICKS_SERVER_HOSTNAME")
DATABRICKS_HTTP_PATH = os.environ.get("DATABRICKS_HTTP_PATH")
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN")

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
    )


MOCK_MPM_BRIDGE = [
    {"orden": 1, "concepto": "1_Resultado Operacional", "monto": 4278678.98},
    {"orden": 2, "concepto": "2_(-) Costos WMS", "monto": -4701.32},
    {"orden": 3, "concepto": "3_(=) EBITDA Operacional", "monto": 4273977.66},
    {"orden": 4, "concepto": "4_(-) Costos Corporativos", "monto": -169530.84},
    {"orden": 5, "concepto": "5_(=) EBITDA Ajustado", "monto": 4104446.81},
]

MOCK_ABC_COSTS = [
    {
        "wms_telemetry_id": 1,
        "sku": "SKU-ABC-001",
        "pedido": "PED-000001",
        "centro_costo_origen": "CL_CD0100",
        "id_recurso_pool": "DRV_EQP_GRUA",
        "dimension_driver": "Movimientos_Pallet",
        "cantidad_consumida": 12.5,
        "descripcion_recurso": "Depreciacion y Mantenimiento Montacargas",
        "tasa_unitaria_calculada": 111.76,
        "costo_asignado_linea": 1397.0,
        "fecha": "2026-04-01",
    },
    {
        "wms_telemetry_id": 2,
        "sku": "SKU-ABC-002",
        "pedido": "PED-000002",
        "centro_costo_origen": "CL_CD0200",
        "id_recurso_pool": "DRV_MAT_EMBALAJE",
        "dimension_driver": "Cajas_Despachadas",
        "cantidad_consumida": 45.0,
        "descripcion_recurso": "Insumos Cajas Carton y Cinta",
        "tasa_unitaria_calculada": 50.0,
        "costo_asignado_linea": 2250.0,
        "fecha": "2026-04-02",
    },
    {
        "wms_telemetry_id": 3,
        "sku": "SKU-ABC-003",
        "pedido": "PED-000003",
        "centro_costo_origen": "CL_CD0300",
        "id_recurso_pool": "DRV_MOD_CUADRILLA",
        "dimension_driver": "Segundos_Efectivos",
        "cantidad_consumida": 180.0,
        "descripcion_recurso": "Operario_Descarga_Cuadrilla",
        "tasa_unitaria_calculada": 3.09,
        "costo_asignado_linea": 556.2,
        "fecha": "2026-04-03",
    },
]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/mpm")
def get_mpm_bridge():
    return MOCK_MPM_BRIDGE


@app.get("/api/abc-costs")
def get_abc_costs():
    return MOCK_ABC_COSTS
