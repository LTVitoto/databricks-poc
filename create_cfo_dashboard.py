"""Orquesta BI-as-Code: crea Queries + Visualizations (API clasica de
Databricks SQL) y ensambla un Dashboard Lakeview ("CFO IFRS 18 Performance")
con 2 widgets de barras, 100% via API REST, sin intervencion manual en la UI.

La API clasica de contenedores de dashboard (api/2.0/preview/sql/dashboards)
esta deshabilitada en este workspace (HTTP 404, RPC no implementado); el
contenedor se crea con la API Lakeview (api/2.0/lakeview/dashboards), que es
la soportada activamente. Idempotente: si ya existe un dashboard con el mismo
`display_name`, se actualiza (PATCH) en lugar de duplicarlo.
"""

import json
import subprocess
import sys
from typing import Any

import requests

GOLD_TABLE = "mi_test_catalogo.default.gold_acdoca_ifrs18"
WAREHOUSE_ID = "9d616c43551f0723"
DASHBOARD_NAME = "CFO IFRS 18 Performance"

SQL_WATERFALL = f"""WITH consolidado AS (
    SELECT ifrs18_category, -SUM(ksl) AS resultado_ksl
    FROM {GOLD_TABLE}
    WHERE rassc IS NULL
    GROUP BY ifrs18_category
),
ordenado AS (
    SELECT ifrs18_category AS categoria, resultado_ksl,
        CASE ifrs18_category
            WHEN 'Operating' THEN 1 WHEN 'Investing' THEN 2
            WHEN 'Financing' THEN 3 WHEN 'Taxes' THEN 4 END AS orden
    FROM consolidado
)
SELECT categoria, resultado_ksl, orden FROM ordenado
UNION ALL
SELECT 'Resultado Neto', SUM(resultado_ksl), 5 FROM ordenado
ORDER BY orden"""

SQL_SEGMENTO = f"""WITH operativo AS (
    SELECT rbukrs, -SUM(ksl) AS operating_profit_ksl,
        SUM(CASE WHEN mpm_tag = 'EBITDA_ADJUSTED' THEN ksl ELSE 0 END)
            AS depreciacion_addback_ksl
    FROM {GOLD_TABLE}
    WHERE rassc IS NULL AND ifrs18_category = 'Operating'
    GROUP BY rbukrs
)
SELECT rbukrs AS sociedad, operating_profit_ksl, depreciacion_addback_ksl,
    operating_profit_ksl + depreciacion_addback_ksl AS ebitda_ajustado_ksl
FROM operativo ORDER BY rbukrs"""


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


def get_data_source_id(host: str, token: str, warehouse_id: str) -> str:
    sources = api("GET", "/api/2.0/preview/sql/data_sources", host, token)
    for source in sources:
        if warehouse_id in (source.get("warehouse_id"), source.get("endpoint_id")):
            return source["id"]
    raise RuntimeError(f"No se encontro data_source para warehouse {warehouse_id}")


def create_query(
    host: str, token: str, data_source_id: str, name: str, description: str, sql: str
) -> str:
    body = {
        "name": name,
        "description": description,
        "query": sql,
        "data_source_id": data_source_id,
        "options": {},
    }
    created = api("POST", "/api/2.0/preview/sql/queries", host, token, body)
    return created["id"]


def create_bar_chart(
    host: str, token: str, query_id: str, name: str, x_col: str, y_col: str
) -> str:
    body = {
        "query_id": query_id,
        "type": "CHART",
        "name": name,
        "description": "",
        "options": {
            "globalSeriesType": "column",
            "sortX": True,
            "legend": {"enabled": True},
            "xAxis": {"type": "-", "labels": {"enabled": True}},
            "yAxis": [{"type": "linear"}, {"type": "linear", "opposite": True}],
            "series": {"stacking": None},
            "columnMapping": {x_col: "x", y_col: "y"},
        },
    }
    created = api("POST", "/api/2.0/preview/sql/visualizations", host, token, body)
    return created["id"]


def build_dashboard_document() -> dict[str, Any]:
    return {
        "datasets": [
            {
                "name": "ds_waterfall",
                "displayName": "Waterfall PL IFRS18",
                "queryLines": [SQL_WATERFALL],
            },
            {
                "name": "ds_segmento",
                "displayName": "EBITDA por segmento",
                "queryLines": [SQL_SEGMENTO],
            },
        ],
        "pages": [
            {
                "name": "main",
                "displayName": "CFO",
                "layout": [
                    {
                        "widget": {
                            "name": "widget_waterfall",
                            "queries": [
                                {
                                    "name": "main_query",
                                    "query": {
                                        "datasetName": "ds_waterfall",
                                        "fields": [
                                            {
                                                "name": "categoria",
                                                "expression": "`categoria`",
                                            },
                                            {
                                                "name": "resultado_ksl",
                                                "expression": "`resultado_ksl`",
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
                                        "fieldName": "categoria",
                                        "scale": {"type": "categorical"},
                                        "displayName": "Categoria",
                                    },
                                    "y": {
                                        "fieldName": "resultado_ksl",
                                        "scale": {"type": "quantitative"},
                                        "displayName": "Resultado KSL",
                                    },
                                },
                                "frame": {
                                    "showTitle": True,
                                    "title": "P&L IFRS18 por categoria",
                                },
                            },
                        },
                        "position": {"x": 0, "y": 0, "width": 3, "height": 6},
                    },
                    {
                        "widget": {
                            "name": "widget_segmento",
                            "queries": [
                                {
                                    "name": "main_query",
                                    "query": {
                                        "datasetName": "ds_segmento",
                                        "fields": [
                                            {
                                                "name": "sociedad",
                                                "expression": "`sociedad`",
                                            },
                                            {
                                                "name": "ebitda_ajustado_ksl",
                                                "expression": "`ebitda_ajustado_ksl`",
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
                                        "fieldName": "sociedad",
                                        "scale": {"type": "categorical"},
                                        "displayName": "Sociedad",
                                    },
                                    "y": {
                                        "fieldName": "ebitda_ajustado_ksl",
                                        "scale": {"type": "quantitative"},
                                        "displayName": "EBITDA Ajustado KSL",
                                    },
                                },
                                "frame": {
                                    "showTitle": True,
                                    "title": "EBITDA Ajustado AU vs BR",
                                },
                            },
                        },
                        "position": {"x": 3, "y": 0, "width": 3, "height": 6},
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

    data_source_id = get_data_source_id(host, token, WAREHOUSE_ID)
    print(f"data_source_id = {data_source_id}")

    q1 = create_query(
        host,
        token,
        data_source_id,
        "CFO - Waterfall PL IFRS18",
        "Waterfall P&L IFRS18 consolidado, IC eliminado (IFRS10)",
        SQL_WATERFALL,
    )
    print(f"query_waterfall = {q1}")

    q2 = create_query(
        host,
        token,
        data_source_id,
        "CFO - EBITDA Ajustado por Segmento IFRS8",
        "Operating Profit / EBITDA ajustado AU vs BR (IFRS8, MPM IFRS18)",
        SQL_SEGMENTO,
    )
    print(f"query_segmento = {q2}")

    viz1 = create_bar_chart(
        host, token, q1, "P&L IFRS18 por categoria", "categoria", "resultado_ksl"
    )
    print(f"viz_waterfall = {viz1}")

    viz2 = create_bar_chart(
        host, token, q2, "EBITDA Ajustado AU vs BR", "sociedad", "ebitda_ajustado_ksl"
    )
    print(f"viz_segmento = {viz2}")

    dashboard_id = upsert_lakeview_dashboard(host, token)
    print(f"dashboard_id = {dashboard_id}")

    publish_dashboard(host, token, dashboard_id)

    dashboard_url = f"{host}/dashboardsv3/{dashboard_id}/published?o={org_id}"
    print("=== DASHBOARD CREADO ===")
    print(dashboard_url)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
