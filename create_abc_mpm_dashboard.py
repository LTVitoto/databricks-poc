"""BI-as-Code: ensambla el Dashboard Lakeview "CFO: Rentabilidad ABC &
IFRS 18" con drill-down interactivo de 3 niveles (parametros Databricks
AI/BI: `:p_mpm_line` -> `:p_abc_dimension`), via API REST, mismo patron que
``create_cfo_dashboard.py`` / ``create_farma_dashboard.py``.

Nivel 2 agrupa por `silver_maestro_drivers_abc.DIMENSION_DRIVER` (el codigo
1_TIEMPO_OPERATIVO/3_MOVIMIENTO_TRANS/4_VOLUMEN_UNIDADES del maestro, no el
`dimension_driver` propio de `gold_abc_operational_costs` que usa nombres
WMS) -- se hace JOIN con el maestro dentro del dataset del dashboard para
no tocar el pipeline de `abc_costing_engine.py`.

`CANAL` no existe como columna real en ningun lado del modelo de datos
(unico canal operativo modelado es WMS); se expone como literal constante
en la tabla de Nivel 3 para cumplir el esquema de columnas pedido.

Validado empiricamente via round-trip (GET tras PATCH): los `parameters` a
nivel dataset y `query.parameters` a nivel widget SI persisten -- Nivel 2 y
Nivel 3 escuchan correctamente `:p_mpm_line`/`:p_abc_dimension`. Una clave
`widget.interactions` para el "clic en una marca setea el parametro" fue
probada y el backend la descarta silenciosamente (no es parte del schema
real de `serialized_dashboard`) -- se removio. El punto-y-clic nativo entre
widgets requiere, por ahora, un paso manual una sola vez en la UI del
dashboard (editar la visualizacion -> usarla como fuente de un filtro), no
expuesto en este endpoint.
"""

import json
import subprocess
import sys
from typing import Any

import requests

CATALOG = "mi_test_catalogo"
SCHEMA = "default"
MPM_TABLE = f"{CATALOG}.{SCHEMA}.gold_mpm_reconciliation"
ABC_TABLE = f"{CATALOG}.{SCHEMA}.gold_abc_operational_costs"
DRIVERS_TABLE = f"{CATALOG}.{SCHEMA}.silver_maestro_drivers_abc"
WAREHOUSE_ID = "9d616c43551f0723"
DASHBOARD_NAME = "CFO: Rentabilidad ABC & IFRS 18"

SQL_EBITDA_AJUSTADO = f"""SELECT monto AS ebitda_ajustado_usd
FROM {MPM_TABLE}
WHERE orden = 5"""

SQL_PUENTE_MPM = f"""SELECT orden, concepto, monto
FROM {MPM_TABLE}
ORDER BY orden"""

SQL_WMS_DISTRIBUTION = f"""SELECT d.DIMENSION_DRIVER AS dimension_driver,
    SUM(a.costo_asignado_linea) AS costo_total
FROM {ABC_TABLE} a
JOIN {DRIVERS_TABLE} d
  ON a.centro_costo_origen = d.CENTRO_COSTO_ORIGEN
 AND a.id_recurso_pool = d.ID_RECURSO_POOL
WHERE :p_mpm_line IS NOT NULL
GROUP BY d.DIMENSION_DRIVER
ORDER BY d.DIMENSION_DRIVER"""

SQL_ROOT_CAUSE = f"""SELECT d.PERIODO_MES AS PERIODO,
    a.centro_costo_origen AS CEDI,
    'WMS' AS CANAL,
    a.descripcion_recurso AS DESCRIPCION_RECURSO,
    a.cantidad_consumida AS VOLUMEN_CONSUMIDO,
    a.fecha
FROM {ABC_TABLE} a
JOIN {DRIVERS_TABLE} d
  ON a.centro_costo_origen = d.CENTRO_COSTO_ORIGEN
 AND a.id_recurso_pool = d.ID_RECURSO_POOL
WHERE d.DIMENSION_DRIVER = :p_abc_dimension
ORDER BY a.fecha DESC"""

PARAM_MPM_LINE = {
    "displayName": "p_mpm_line",
    "keyword": "p_mpm_line",
    "dataType": "STRING",
    "defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": ""}]}},
}

PARAM_ABC_DIMENSION = {
    "displayName": "p_abc_dimension",
    "keyword": "p_abc_dimension",
    "dataType": "STRING",
    "defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": ""}]}},
}


def auth_env() -> dict[str, str]:
    result = subprocess.run(
        ["databricks", "auth", "env", "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)["env"]


def api(
    method: str, path: str, host: str, token: str, body: dict[str, Any] | None = None
) -> Any:
    url = f"{host}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.request(method, url, headers=headers, json=body, timeout=30)
    if not resp.ok:
        print(f"FALLO {method} {path}: HTTP {resp.status_code}")
        print(resp.text[:2000])
        resp.raise_for_status()
    return resp.json() if resp.text else {}


def build_dashboard_document() -> dict[str, Any]:
    return {
        "datasets": [
            {
                "name": "ds_ebitda_ajustado",
                "displayName": "EBITDA Ajustado USD",
                "queryLines": [SQL_EBITDA_AJUSTADO],
            },
            {
                "name": "ds_puente_mpm",
                "displayName": "Puente MPM",
                "queryLines": [SQL_PUENTE_MPM],
            },
            {
                "name": "ds_wms_distribution",
                "displayName": "Distribucion Costos WMS",
                "queryLines": [SQL_WMS_DISTRIBUTION],
                "parameters": [PARAM_MPM_LINE],
            },
            {
                "name": "ds_root_cause",
                "displayName": "Causa Raiz Operativa",
                "queryLines": [SQL_ROOT_CAUSE],
                "parameters": [PARAM_ABC_DIMENSION],
            },
        ],
        "pages": [
            {
                "name": "main",
                "displayName": "CFO",
                "layout": [
                    {
                        "widget": {
                            "name": "widget_ebitda_ajustado",
                            "queries": [
                                {
                                    "name": "main_query",
                                    "query": {
                                        "datasetName": "ds_ebitda_ajustado",
                                        "fields": [
                                            {
                                                "name": "ebitda_ajustado_usd",
                                                "expression": "`ebitda_ajustado_usd`",
                                            }
                                        ],
                                        "disaggregated": True,
                                    },
                                }
                            ],
                            "spec": {
                                "version": 2,
                                "widgetType": "counter",
                                "encodings": {
                                    "value": {
                                        "fieldName": "ebitda_ajustado_usd",
                                        "displayName": "EBITDA Ajustado (USD)",
                                    }
                                },
                                "frame": {
                                    "showTitle": True,
                                    "title": "EBITDA Ajustado (USD)",
                                },
                            },
                        },
                        "position": {"x": 0, "y": 0, "width": 2, "height": 3},
                    },
                    {
                        # Nivel 1: clic en una barra (ej. "Costos Logisticos
                        # WMS") setea el parametro dashboard p_mpm_line.
                        "widget": {
                            "name": "widget_puente_mpm",
                            "queries": [
                                {
                                    "name": "main_query",
                                    "query": {
                                        "datasetName": "ds_puente_mpm",
                                        "fields": [
                                            {
                                                "name": "concepto",
                                                "expression": "`concepto`",
                                            },
                                            {
                                                "name": "monto",
                                                "expression": "`monto`",
                                            },
                                            {
                                                "name": "orden",
                                                "expression": "`orden`",
                                            },
                                        ],
                                        "disaggregated": True,
                                    },
                                }
                            ],
                            "spec": {
                                "version": 3,
                                "widgetType": "bar",
                                "encodings": {
                                    "x": {
                                        "fieldName": "concepto",
                                        "scale": {"type": "categorical"},
                                        "displayName": "Concepto",
                                        "sort": {"by": "y-reversed"},
                                    },
                                    "y": {
                                        "fieldName": "monto",
                                        "scale": {"type": "quantitative"},
                                        "displayName": "Monto (USD)",
                                    },
                                },
                                "frame": {
                                    "showTitle": True,
                                    "title": (
                                        "Nivel 1: Puente MPM (configurar como "
                                        "fuente de filtro p_mpm_line en la UI)"
                                    ),
                                },
                            },
                        },
                        "position": {"x": 2, "y": 0, "width": 4, "height": 6},
                    },
                    {
                        # Nivel 2: escucha p_mpm_line (query parametrizada);
                        # clic en una porcion setea p_abc_dimension.
                        "widget": {
                            "name": "widget_wms_distribution",
                            "queries": [
                                {
                                    "name": "main_query",
                                    "query": {
                                        "datasetName": "ds_wms_distribution",
                                        "parameters": [
                                            {
                                                "keyword": "p_mpm_line",
                                                "name": "p_mpm_line",
                                            }
                                        ],
                                        "fields": [
                                            {
                                                "name": "dimension_driver",
                                                "expression": "`dimension_driver`",
                                            },
                                            {
                                                "name": "costo_total",
                                                "expression": "`costo_total`",
                                            },
                                        ],
                                        "disaggregated": True,
                                    },
                                }
                            ],
                            "spec": {
                                "version": 3,
                                "widgetType": "bar",
                                "encodings": {
                                    "x": {
                                        "fieldName": "dimension_driver",
                                        "scale": {"type": "categorical"},
                                        "displayName": "Dimension Driver",
                                    },
                                    "y": {
                                        "fieldName": "costo_total",
                                        "scale": {"type": "quantitative"},
                                        "displayName": "Costo Total (CLP)",
                                    },
                                },
                                "frame": {
                                    "showTitle": True,
                                    "title": (
                                        "Nivel 2: Dimensiones ABC (configurar "
                                        "como fuente de filtro "
                                        "p_abc_dimension en la UI)"
                                    ),
                                },
                            },
                        },
                        "position": {"x": 0, "y": 3, "width": 2, "height": 3},
                    },
                    {
                        # Nivel 3: tabla de detalle, escucha p_abc_dimension.
                        "widget": {
                            "name": "widget_root_cause",
                            "queries": [
                                {
                                    "name": "main_query",
                                    "query": {
                                        "datasetName": "ds_root_cause",
                                        "parameters": [
                                            {
                                                "keyword": "p_abc_dimension",
                                                "name": "p_abc_dimension",
                                            }
                                        ],
                                        "fields": [
                                            {
                                                "name": "PERIODO",
                                                "expression": "`PERIODO`",
                                            },
                                            {
                                                "name": "CEDI",
                                                "expression": "`CEDI`",
                                            },
                                            {
                                                "name": "CANAL",
                                                "expression": "`CANAL`",
                                            },
                                            {
                                                "name": "DESCRIPCION_RECURSO",
                                                "expression": "`DESCRIPCION_RECURSO`",
                                            },
                                            {
                                                "name": "VOLUMEN_CONSUMIDO",
                                                "expression": "`VOLUMEN_CONSUMIDO`",
                                            },
                                        ],
                                        "disaggregated": True,
                                    },
                                }
                            ],
                            "spec": {
                                "version": 1,
                                "widgetType": "table",
                                "encodings": {
                                    "columns": [
                                        {"fieldName": "PERIODO", "booleanValues": None},
                                        {"fieldName": "CEDI", "booleanValues": None},
                                        {"fieldName": "CANAL", "booleanValues": None},
                                        {
                                            "fieldName": "DESCRIPCION_RECURSO",
                                            "booleanValues": None,
                                        },
                                        {
                                            "fieldName": "VOLUMEN_CONSUMIDO",
                                            "booleanValues": None,
                                        },
                                    ]
                                },
                                "frame": {
                                    "showTitle": True,
                                    "title": "Nivel 3: Causa Raiz Operativa",
                                },
                            },
                        },
                        "position": {"x": 6, "y": 0, "width": 4, "height": 6},
                    },
                ],
            }
        ],
    }


def find_existing_dashboard_id(host: str, token: str, name: str) -> str | None:
    result = api("GET", "/api/2.0/lakeview/dashboards?page_size=100", host, token)
    for dashboard in result.get("dashboards", []):
        if dashboard.get("display_name") == name:
            return dashboard["dashboard_id"]
    return None


def upsert_lakeview_dashboard(host: str, token: str) -> str:
    document = build_dashboard_document()
    body = {
        "display_name": DASHBOARD_NAME,
        "serialized_dashboard": json.dumps(document),
        "warehouse_id": WAREHOUSE_ID,
    }
    existing_id = find_existing_dashboard_id(host, token, DASHBOARD_NAME)
    if existing_id:
        api("PATCH", f"/api/2.0/lakeview/dashboards/{existing_id}", host, token, body)
        return existing_id
    created = api("POST", "/api/2.0/lakeview/dashboards", host, token, body)
    return created["dashboard_id"]


def publish_dashboard(host: str, token: str, dashboard_id: str) -> None:
    api(
        "POST",
        f"/api/2.0/lakeview/dashboards/{dashboard_id}/published",
        host,
        token,
        {"embed_credentials": False, "warehouse_id": WAREHOUSE_ID},
    )


def main() -> None:
    env = auth_env()
    host = env["DATABRICKS_HOST"].rstrip("/")
    token = env["DATABRICKS_TOKEN"]
    org_id = env["DATABRICKS_WORKSPACE_ID"]

    dashboard_id = upsert_lakeview_dashboard(host, token)
    print(f"dashboard_id = {dashboard_id}")

    publish_dashboard(host, token, dashboard_id)

    dashboard_url = f"{host}/dashboardsv3/{dashboard_id}/published?o={org_id}"
    print("=== DASHBOARD CFO RENTABILIDAD (DRILL-DOWN) ACTUALIZADO ===")
    print(dashboard_url)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
