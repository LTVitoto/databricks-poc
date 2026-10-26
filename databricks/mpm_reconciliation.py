"""Construye el puente MPM IFRS 18/8: Resultado Operacional (SAP/ACDOCA) ->
EBITDA Operacional (menos costos WMS/ABC) -> EBITDA Ajustado (menos costos
corporativos estrategicos, hoja CL_CORP).

Los costos del motor ABC y CL_CORP estan en CLP nominal del maestro de
drivers; `gold_acdoca_ifrs18.ksl` esta en USD (moneda grupo). Se homologan
ambos costos a USD dividiendo por la tasa USD->CLP de `silver_fx_rates`
(poblada por `ingest_fx_rates.py`) antes de restarlos del Resultado
Operacional.
"""

import os

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

CATALOG = os.environ.get("SILVER_CATALOG", "mi_test_catalogo")
SCHEMA = os.environ.get("SILVER_SCHEMA", "default")

ACDOCA_TABLE = f"{CATALOG}.{SCHEMA}.gold_acdoca_ifrs18"
ABC_COSTS_TABLE = f"{CATALOG}.{SCHEMA}.gold_abc_operational_costs"
DRIVERS_TABLE = f"{CATALOG}.{SCHEMA}.silver_maestro_drivers_abc"
FX_TABLE = f"{CATALOG}.{SCHEMA}.silver_fx_rates"
TARGET_TABLE = f"{CATALOG}.{SCHEMA}.gold_mpm_reconciliation"

spark = SparkSession.builder.getOrCreate()


def get_usd_clp_rate() -> float:
    row = (
        spark.table(FX_TABLE)
        .filter((F.col("base_currency") == "USD") & (F.col("quote_currency") == "CLP"))
        .orderBy(F.col("fetched_at").desc())
        .limit(1)
        .collect()[0]
    )
    return float(row["rate"])


def main() -> None:
    usd_clp_rate = get_usd_clp_rate()

    resultado_operacional = float(
        spark.table(ACDOCA_TABLE)
        .filter((F.col("ifrs18_category") == "Operating") & F.col("rassc").isNull())
        .agg(-F.sum("ksl"))
        .collect()[0][0]
    )

    costos_wms_clp = float(
        spark.table(ABC_COSTS_TABLE).agg(F.sum("costo_asignado_linea")).collect()[0][0]
    )

    costos_corporativos_clp = float(
        spark.table(DRIVERS_TABLE)
        .filter(F.col("CENTRO_COSTO_ORIGEN") == "CL_CORP")
        .agg(F.sum("COSTO_TOTAL_CLP_Input"))
        .collect()[0][0]
    )

    costos_wms_usd = costos_wms_clp / usd_clp_rate
    costos_corporativos_usd = costos_corporativos_clp / usd_clp_rate

    ebitda_operacional = resultado_operacional - costos_wms_usd
    ebitda_ajustado = ebitda_operacional - costos_corporativos_usd

    rows = [
        (1, "1_Resultado Operacional", resultado_operacional),
        (2, "2_(-) Costos WMS", -costos_wms_usd),
        (3, "3_(=) EBITDA Operacional", ebitda_operacional),
        (4, "4_(-) Costos Corporativos", -costos_corporativos_usd),
        (5, "5_(=) EBITDA Ajustado", ebitda_ajustado),
    ]
    puente = spark.createDataFrame(rows, ["orden", "concepto", "monto"])

    (
        puente.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    print(f"Tasa USD->CLP aplicada: {usd_clp_rate}")
    for _, concepto, monto in rows:
        print(f"{concepto}: {monto:,.2f}")


if __name__ == "__main__":
    main()
