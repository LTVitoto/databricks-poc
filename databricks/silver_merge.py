"""Capa Silver: Auto Loader (cloudFiles) + MERGE INTO con manejo de CDC.

Lee los Parquet depositados por el script puente en el Volume de landing,
deduplica por `kunnr` dentro de cada micro-batch usando el `ts_ms` de nivel
raiz del envelope de Debezium (tiempo de captura del evento). No se usa el
`ts_ms` anidado dentro de `after`/`before`: esa es la columna de negocio con
`DEFAULT CURRENT_TIMESTAMP`, que no se actualiza sola en un UPDATE.

Aplica un MERGE INTO sobre la tabla Delta de destino: `op = 'd'` borra la
fila, altas/actualizaciones hacen upsert, y un guard por `event_ts_ms` evita
que un micro-batch fuera de orden sobreescriba un cambio mas reciente ya
aplicado en un micro-batch anterior.
"""

import os

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

CATALOG = os.environ.get("SILVER_CATALOG", "mi_test_catalogo")
SCHEMA = os.environ.get("SILVER_SCHEMA", "default")
TARGET_TABLE = f"{CATALOG}.{SCHEMA}.silver_sap_clientes_kna1"

VOLUME_ROOT = os.environ.get(
    "LANDING_VOLUME_ROOT", f"/Volumes/{CATALOG}/{SCHEMA}/paquet_demo"
)
SOURCE_PATH = f"{VOLUME_ROOT}/topics/sap.public.sap_clientes_kna1/"
CHECKPOINT_PATH = f"{VOLUME_ROOT}/_checkpoints/silver_kna1"
SCHEMA_LOCATION = f"{CHECKPOINT_PATH}/_schema"

spark = SparkSession.builder.getOrCreate()


def ensure_target_table() -> None:
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {TARGET_TABLE} (
            kunnr STRING NOT NULL,
            name1 STRING,
            ort01 STRING,
            land1 STRING,
            spras STRING,
            event_ts_ms BIGINT
        ) USING DELTA
        """)


def extract_business_columns(raw: DataFrame) -> DataFrame:
    return raw.select(
        F.coalesce(F.col("after.kunnr"), F.col("before.kunnr")).alias("kunnr"),
        F.col("after.name1").alias("name1"),
        F.col("after.ort01").alias("ort01"),
        F.col("after.land1").alias("land1"),
        F.col("after.spras").alias("spras"),
        F.col("op").alias("op"),
        F.col("ts_ms").alias("event_ts_ms"),
    )


def dedupe_latest_per_key(changes: DataFrame) -> DataFrame:
    window = Window.partitionBy("kunnr").orderBy(F.col("event_ts_ms").desc())
    return (
        changes.withColumn("_rn", F.row_number().over(window))
        .filter(F.col("_rn") == 1)
        .drop("_rn")
    )


def merge_batch(batch_df: DataFrame, batch_id: int) -> None:
    if batch_df.isEmpty():
        return
    staged = dedupe_latest_per_key(extract_business_columns(batch_df))
    staged.createOrReplaceTempView("staged_changes")
    spark.sql(f"""
        MERGE INTO {TARGET_TABLE} AS target
        USING staged_changes AS source
        ON target.kunnr = source.kunnr
        WHEN MATCHED AND source.op = 'd' THEN DELETE
        WHEN MATCHED AND source.event_ts_ms >= target.event_ts_ms THEN UPDATE SET
            name1 = source.name1,
            ort01 = source.ort01,
            land1 = source.land1,
            spras = source.spras,
            event_ts_ms = source.event_ts_ms
        WHEN NOT MATCHED AND source.op != 'd' THEN INSERT (
            kunnr, name1, ort01, land1, spras, event_ts_ms
        ) VALUES (
            source.kunnr, source.name1, source.ort01, source.land1,
            source.spras, source.event_ts_ms
        )
        """)


def main() -> None:
    ensure_target_table()
    raw_stream = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.schemaLocation", SCHEMA_LOCATION)
        .load(SOURCE_PATH)
    )
    query = (
        raw_stream.writeStream.foreachBatch(merge_batch)
        .option("checkpointLocation", CHECKPOINT_PATH)
        .trigger(availableNow=True)
        .start()
    )
    query.awaitTermination()


if __name__ == "__main__":
    main()
