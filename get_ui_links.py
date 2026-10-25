"""Construye e imprime URLs directas de la interfaz web de Databricks para
validacion visual: Data Explorer (tabla Gold), ultimo Job Run exitoso del
Workflow, y SQL Editor.
"""

import json
import subprocess
from typing import Any

CATALOG = "mi_test_catalogo"
SCHEMA = "default"
GOLD_TABLE = "gold_acdoca_ifrs18"
JOB_ID = "204650251307272"


def run_databricks_json(*args: str) -> Any:
    result = subprocess.run(
        ["databricks", *args, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def get_host_and_org() -> tuple[str, str]:
    data = run_databricks_json("auth", "env")["env"]
    return data["DATABRICKS_HOST"].rstrip("/"), data["DATABRICKS_WORKSPACE_ID"]


def get_latest_successful_run_url(job_id: str) -> str:
    runs = run_databricks_json("jobs", "list-runs", "--job-id", job_id)
    for run in runs:
        if run.get("state", {}).get("result_state") == "SUCCESS":
            return run["run_page_url"]
    raise RuntimeError(f"No se encontro un run exitoso para el job {job_id}")


def main() -> None:
    host, org_id = get_host_and_org()

    data_explorer_url = (
        f"{host}/explore/data/{CATALOG}/{SCHEMA}/{GOLD_TABLE}?o={org_id}"
    )
    job_run_url = get_latest_successful_run_url(JOB_ID)
    sql_editor_url = f"{host}/sql/editor?o={org_id}"

    print("=== Enlaces de validacion Databricks (CFO) ===")
    print(f"1. Data Explorer - tabla Gold:   {data_explorer_url}")
    print(f"2. Job Run exitoso (Workflow):   {job_run_url}")
    print(f"3. SQL Editor:                   {sql_editor_url}")


if __name__ == "__main__":
    main()
