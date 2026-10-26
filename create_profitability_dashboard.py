"""BI-as-Code: ensambla el Dashboard Lakeview "CFO: Rentabilidad ABC &
IFRS 18" 100% via API REST, mismo patron que ``create_cfo_dashboard.py`` /
``create_farma_dashboard.py``.
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
WAREHOUSE_ID = "9d616c43551f0723"
DASHBOARD_NAME = "CFO: Rentabilidad ABC & IFRS 18"

SQL_EBITDA_AJUSTADO = f"""SELECT monto AS ebitda_ajustado_usd
FROM {MPM_TABLE}
WHERE orden = 5"""

SQL_PUENTE_MPM = f"""SELECT orden, concepto, monto
FROM {MPM_TABLE}
ORDER BY orden"""

SQL_WMS_DISTRIBUTION = f"""SELECT dimension_driver,
    SUM(costo_asignado_linea) AS costo_total
FROM {ABC_TABLE}
GROUP BY dimension_driver
ORDER BY dimension_driver"""


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
                                        "sort": {
                                            "by": "y-reversed",
                                        },
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
                                        "Puente MPM: Resultado Operacional -> "
                                        "EBITDA Ajustado"
                                    ),
                                },
                            },
                        },
                        "position": {"x": 2, "y": 0, "width": 4, "height": 6},
                    },
                    {
                        "widget": {
                            "name": "widget_wms_distribution",
                            "queries": [
                                {
                                    "name": "main_query",
                                    "query": {
                                        "datasetName": "ds_wms_distribution",
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
                                    "title": "Distribucion de Costos WMS por Dimension",
                                },
                            },
                        },
                        "position": {"x": 0, "y": 3, "width": 2, "height": 3},
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
    print("=== DASHBOARD CFO RENTABILIDAD CREADO ===")
    print(dashboard_url)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
