"""Auditoria de Row-Level Security: alterna el pais asignado al usuario
actual en ``rls_user_country_map`` (unico usuario real de este PoC) y
compara los totales que la MISMA tabla Gold entrega bajo cada identidad
simulada (BR, AU, GLOBAL), demostrando que el ROW FILTER de Unity Catalog
esta efectivamente restringiendo las filas visibles.
"""

import json
import subprocess
from typing import Any

import requests

CATALOG = "mi_test_catalogo"
SCHEMA = "default"
MAP_TABLE = f"{CATALOG}.{SCHEMA}.rls_user_country_map"
WAREHOUSE_ID = "9d616c43551f0723"
MY_USER_EMAIL = "victor.figueroa.pinto@gmail.com"

SCENARIOS = ["BR", "AU", "GLOBAL"]

QUERIES = {
    "gold_acdoca_ifrs18 (SUM ksl)": (
        f"SELECT ROUND(SUM(ksl), 2) FROM {CATALOG}.{SCHEMA}.gold_acdoca_ifrs18"
    ),
    "gold_farma_provision_risk (SUM provision_risk_value)": (
        f"SELECT ROUND(SUM(provision_risk_value), 2) "
        f"FROM {CATALOG}.{SCHEMA}.gold_farma_provision_risk"
    ),
}


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
    return resp.json()


def set_scenario(host: str, token: str, pais: str) -> None:
    run_statement(
        host,
        token,
        f"UPDATE {MAP_TABLE} SET pais = '{pais}' WHERE user_email = '{MY_USER_EMAIL}'",
    )


def main() -> None:
    env = auth_env()
    host = env["DATABRICKS_HOST"].rstrip("/")
    token = env["DATABRICKS_TOKEN"]

    results: dict[str, dict[str, Any]] = {label: {} for label in QUERIES}

    for pais in SCENARIOS:
        set_scenario(host, token, pais)
        for label, sql in QUERIES.items():
            data = run_statement(host, token, sql)
            value = data["result"]["data_array"][0][0]
            results[label][pais] = value

    print("=== Auditoria RLS: mismo SELECT, distinta identidad simulada ===")
    for label, by_pais in results.items():
        print(f"\n{label}")
        for pais in SCENARIOS:
            print(f"  pais={pais:7s} -> {by_pais[pais]}")

    print("\n" + json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
