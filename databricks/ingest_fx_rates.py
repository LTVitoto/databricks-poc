"""Ingesta el tipo de cambio USD->CLP desde el oraculo de divisas
(fxratesapi.com) y lo persiste en `silver_fx_rates` para que
`mpm_reconciliation.py` homologue los costos CLP del motor ABC a la misma
moneda base de `gold_acdoca_ifrs18` (USD).
"""

import json
import os
from datetime import datetime, timezone

import requests
from pyspark.sql import SparkSession

CATALOG = os.environ.get("SILVER_CATALOG", "mi_test_catalogo")
SCHEMA = os.environ.get("SILVER_SCHEMA", "default")
TARGET_TABLE = f"{CATALOG}.{SCHEMA}.silver_fx_rates"

FX_API_URL = "https://api.fxratesapi.com/latest"
BASE_CURRENCY = "USD"
QUOTE_CURRENCY = "CLP"

spark = SparkSession.builder.getOrCreate()


def fetch_fx_rate() -> float:
    resp = requests.get(FX_API_URL, params={"base": BASE_CURRENCY}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return float(data["rates"][QUOTE_CURRENCY])


def main() -> None:
    rate = fetch_fx_rate()
    fetched_at = datetime.now(timezone.utc)

    rows = [(BASE_CURRENCY, QUOTE_CURRENCY, rate, fetched_at)]
    sdf = spark.createDataFrame(
        rows, ["base_currency", "quote_currency", "rate", "fetched_at"]
    )

    (
        sdf.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    print(f"{BASE_CURRENCY}->{QUOTE_CURRENCY}: {rate}")

    result_json = json.dumps(
        {"base": BASE_CURRENCY, "quote": QUOTE_CURRENCY, "rate": rate}
    )
    print(result_json)

    try:
        dbutils.notebook.exit(result_json)  # noqa: F821
    except NameError:
        pass


if __name__ == "__main__":
    main()
