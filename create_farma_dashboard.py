"""BI-as-Code: ensambla el Dashboard Lakeview "Farma Channel Risk &
Provisions" 100% via API REST (sin intervencion manual en la UI), igual
patron que ``create_cfo_dashboard.py``.
"""

import json
import subprocess
import sys
from typing import Any

import requests

GOLD_TABLE = "mi_test_catalogo.default.gold_farma_provision_risk"
WAREHOUSE_ID = "9d616c43551f0723"
DASHBOARD_NAME = "Farma Channel Risk & Provisions"

SQL_RISK_BY_CEDI = f"""SELECT nombre_cedi,
    SUM(provision_risk_value) AS provision_risk_value
FROM {GOLD_TABLE}
WHERE is_provision_risk
GROUP BY nombre_cedi
ORDER BY nombre_cedi"""

SQL_TOTAL_IMPACT = f"""SELECT SUM(provision_risk_value) AS total_impacto
FROM {GOLD_TABLE}
WHERE is_provision_risk"""


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
                "name": "ds_risk_by_cedi",
                "displayName": "Riesgo de Provision por CEDI",
                "queryLines": [SQL_RISK_BY_CEDI],
            },
            {
                "name": "ds_total_impact",
                "displayName": "Total Impacto Operating Profit",
                "queryLines": [SQL_TOTAL_IMPACT],
            },
        ],
        "pages": [
            {
                "name": "main",
                "displayName": "Farma",
                "layout": [
                    {
                        "widget": {
                            "name": "widget_risk_by_cedi",
                            "queries": [
                                {
                                    "name": "main_query",
                                    "query": {
                                        "datasetName": "ds_risk_by_cedi",
                                        "fields": [
                                            {
                                                "name": "nombre_cedi",
                                                "expression": "`nombre_cedi`",
                                            },
                                            {
                                                "name": "provision_risk_value",
                                                "expression": "`provision_risk_value`",
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
                                        "fieldName": "nombre_cedi",
                                        "scale": {"type": "categorical"},
                                        "displayName": "CEDI",
                                    },
                                    "y": {
                                        "fieldName": "provision_risk_value",
                                        "scale": {"type": "quantitative"},
                                        "displayName": "Riesgo de Provision",
                                    },
                                },
                                "frame": {
                                    "showTitle": True,
                                    "title": "Riesgo de Provision por CEDI",
                                },
                            },
                        },
                        "position": {"x": 0, "y": 0, "width": 3, "height": 6},
                    },
                    {
                        "widget": {
                            "name": "widget_total_impact",
                            "queries": [
                                {
                                    "name": "main_query",
                                    "query": {
                                        "datasetName": "ds_total_impact",
                                        "fields": [
                                            {
                                                "name": "total_impacto",
                                                "expression": "`total_impacto`",
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
                                        "fieldName": "total_impacto",
                                        "displayName": "Total Impacto Operating Profit",
                                    }
                                },
                                "frame": {
                                    "showTitle": True,
                                    "title": "Total Impacto en Operating Profit",
                                },
                            },
                        },
                        "position": {"x": 3, "y": 0, "width": 2, "height": 3},
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
    print("=== DASHBOARD FARMA CREADO ===")
    print(dashboard_url)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
