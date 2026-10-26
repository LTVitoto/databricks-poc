"""Materializa `silver_wms_telemetry` desde el Parquet crudo (envelope
Debezium) de `wms_telemetry`, deduplicado por el `ts_ms` de nivel raiz del
envelope (mismo criterio usado en todo el proyecto).
"""

import os

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

CATALOG = os.environ.get("SILVER_CATALOG", "mi_test_catalogo")
SCHEMA = os.environ.get("SILVER_SCHEMA", "default")
VOLUME_ROOT = os.environ.get(
    "LANDING_VOLUME_ROOT", f"/Volumes/{CATALOG}/{SCHEMA}/paquet_demo"
)

SOURCE_PATH = f"{VOLUME_ROOT}/topics/sap.public.wms_telemetry/"
TARGET_TABLE = f"{CATALOG}.{SCHEMA}.silver_wms_telemetry"

spark = SparkSession.builder.getOrCreate()


def read_latest_snapshot(path: str, key_cols: list[str]) -> DataFrame:
    raw = spark.read.format("parquet").load(path)
    extracted = raw.select(
        "after.*",
        F.col("op").alias("_op"),
        F.col("ts_ms").alias("_event_ts_ms"),
    ).filter(F.col("_op") != "d")
    window = Window.partitionBy(*key_cols).orderBy(F.col("_event_ts_ms").desc())
    return (
        extracted.withColumn("_rn", F.row_number().over(window))
        .filter(F.col("_rn") == 1)
        .drop("_rn", "_op", "_event_ts_ms")
    )


def main() -> None:
    silver = read_latest_snapshot(SOURCE_PATH, ["id"])

    (
        silver.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    count = spark.table(TARGET_TABLE).count()
    print(f"{TARGET_TABLE}: {count} filas")


if __name__ == "__main__":
    main()
