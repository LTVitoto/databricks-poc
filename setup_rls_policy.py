"""Aplica Row-Level Security (RLS) en Unity Catalog sobre las tablas Gold
criticas, via una funcion de filtrado dinamico respaldada por una tabla de
mapeo usuario->pais (patron estandar de Databricks para RLS sin depender de
grupos reales de cuenta, apropiado para este PoC de un solo usuario real).
"""

import json
import subprocess
from typing import Any

import requests

CATALOG = "mi_test_catalogo"
SCHEMA = "default"
MAP_TABLE = f"{CATALOG}.{SCHEMA}.rls_user_country_map"
FILTER_FUNCTION = f"{CATALOG}.{SCHEMA}.rls_country_filter"
WAREHOUSE_ID = "9d616c43551f0723"

MY_USER_EMAIL = "victor.figueroa.pinto@gmail.com"

STATEMENTS = [
    f"""
    CREATE TABLE IF NOT EXISTS {MAP_TABLE} (
        user_email STRING,
        pais STRING
    )
    """,
    f"""
    MERGE INTO {MAP_TABLE} AS t
    USING (SELECT '{MY_USER_EMAIL}' AS user_email, 'GLOBAL' AS pais) AS s
    ON t.user_email = s.user_email
    WHEN MATCHED THEN UPDATE SET t.pais = s.pais
    WHEN NOT MATCHED THEN INSERT (user_email, pais) VALUES (s.user_email, s.pais)
    """,
    f"""
    CREATE OR REPLACE FUNCTION {FILTER_FUNCTION}(entidad STRING)
    RETURNS BOOLEAN
    RETURN EXISTS (
        SELECT 1 FROM {MAP_TABLE} m
        WHERE m.user_email = current_user()
          AND (m.pais = 'GLOBAL' OR m.pais = entidad)
    )
    """,
    # Unity Catalog no permite Row Filters en tablas con CHECK constraints
    # (ROW_LEVEL_SECURITY_FEATURE_NOT_SUPPORTED.CHECK_CONSTRAINT). RLS tiene
    # prioridad sobre las constraints de la fase de Data Quality anterior.
    f"ALTER TABLE {CATALOG}.{SCHEMA}.gold_acdoca_ifrs18 "
    "DROP CONSTRAINT IF EXISTS chk_ifrs18_category",
    f"ALTER TABLE {CATALOG}.{SCHEMA}.gold_acdoca_ifrs18 "
    "DROP CONSTRAINT IF EXISTS chk_ksl_not_null",
    f"""
    ALTER TABLE {CATALOG}.{SCHEMA}.gold_acdoca_ifrs18
    SET ROW FILTER {FILTER_FUNCTION} ON (rbukrs)
    """,
    f"""
    ALTER TABLE {CATALOG}.{SCHEMA}.gold_farma_provision_risk
    SET ROW FILTER {FILTER_FUNCTION} ON (werks)
    """,
]


def auth_env() -> dict[str, str]:
    result = subprocess.run(
        ["databricks", "auth", "env", "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)["env"]


def run_statement(host: str, token: str, statement: str) -> Any:
    resp = requests.post(
        f"{host}/api/2.0/sql/statements",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "warehouse_id": WAREHOUSE_ID,
            "statement": statement,
            "wait_timeout": "30s",
        },
        timeout=40,
    )
    resp.raise_for_status()
    data = resp.json()
    state = data.get("status", {}).get("state")
    if state != "SUCCEEDED":
        print("FALLO statement:")
        print(statement)
        print(json.dumps(data, indent=2)[:1500])
        raise RuntimeError(f"Statement no exitoso: {state}")
    return data


def main() -> None:
    env = auth_env()
    host = env["DATABRICKS_HOST"].rstrip("/")
    token = env["DATABRICKS_TOKEN"]

    for statement in STATEMENTS:
        run_statement(host, token, statement)
        print("OK:", " ".join(statement.strip().split())[:90])

    print("RLS aplicado: rls_user_country_map, rls_country_filter,")
    print("gold_acdoca_ifrs18(rbukrs), gold_farma_provision_risk(werks)")


if __name__ == "__main__":
    main()
