"""Pipeline Farma: cruza Sell-In (SAP/CDC) vs Sell-Out (EDICOM), normalizado
a blisters, separando matches exitosos (``gold_farma_sellthrough``) de
registros de Sell-Out cuyo EAN o GLN no homologa contra las tablas maestras
(``gold_farma_quarantine``).

Lee la Capa Silver (extraccion deduplicada del envelope de Debezium para
`farma_sell_in`/`map_sku`/`map_cedi`, mismo criterio de `ts_ms` que el resto
del proyecto) y los mensajes EDICOM (JSON plano, sin envelope CDC).
"""

import json
import os

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

CATALOG = os.environ.get("SILVER_CATALOG", "mi_test_catalogo")
SCHEMA = os.environ.get("SILVER_SCHEMA", "default")
VOLUME_ROOT = os.environ.get(
    "LANDING_VOLUME_ROOT", f"/Volumes/{CATALOG}/{SCHEMA}/paquet_demo"
)

SELL_IN_PATH = f"{VOLUME_ROOT}/topics/sap.public.farma_sell_in/"
MAP_SKU_PATH = f"{VOLUME_ROOT}/topics/sap.public.map_sku/"
MAP_CEDI_PATH = f"{VOLUME_ROOT}/topics/sap.public.map_cedi/"
EDICOM_PATH = f"{VOLUME_ROOT}/edicom/sellout/"

SELLTHROUGH_TABLE = f"{CATALOG}.{SCHEMA}.gold_farma_sellthrough"
QUARANTINE_TABLE = f"{CATALOG}.{SCHEMA}.gold_farma_quarantine"

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


def read_edicom_sellout() -> DataFrame:
    return (
        spark.read.format("json")
        .load(EDICOM_PATH)
        .withColumn("fecha", F.to_date("fecha"))
    )


def build_sellout_matched(
    edicom: DataFrame, map_sku: DataFrame, map_cedi: DataFrame
) -> DataFrame:
    return edicom.join(F.broadcast(map_sku), on="ean13", how="left").join(
        F.broadcast(map_cedi), on="gln", how="left"
    )


def split_quarantine(matched: DataFrame) -> DataFrame:
    return (
        matched.filter(F.col("matnr").isNull() | F.col("werks").isNull())
        .withColumn(
            "motivo",
            F.when(
                F.col("matnr").isNull() & F.col("werks").isNull(),
                F.lit("EAN y GLN sin homologar"),
            )
            .when(F.col("matnr").isNull(), F.lit("EAN sin homologar en map_sku"))
            .otherwise(F.lit("GLN sin homologar en map_cedi")),
        )
        .select("gln", "ean13", "cantidad_blisters", "lote", "fecha", "motivo")
    )


def build_sellout_clean(matched: DataFrame) -> DataFrame:
    return matched.filter(
        F.col("matnr").isNotNull()
        & F.col("werks").isNotNull()
        & (F.col("is_commercial"))
    )


def build_sellin_normalized(
    sell_in: DataFrame, map_sku: DataFrame, map_cedi: DataFrame
) -> DataFrame:
    return (
        sell_in.join(F.broadcast(map_sku), on="matnr", how="inner")
        .join(F.broadcast(map_cedi), on="werks", how="inner")
        .filter(F.col("is_commercial"))
        .withColumn(
            "cantidad_blisters_sellin",
            F.col("cantidad_cajas") * F.col("factor_caja_blister"),
        )
    )


def build_sellthrough(
    sellin_normalized: DataFrame, sellout_clean: DataFrame
) -> DataFrame:
    dims = ["matnr", "descripcion", "werks", "nombre_cedi", "fecha"]
    sellin_agg = sellin_normalized.groupBy(*dims).agg(
        F.sum("cantidad_blisters_sellin").alias("cantidad_blisters_sellin")
    )
    sellout_agg = sellout_clean.groupBy(*dims).agg(
        F.sum("cantidad_blisters").alias("cantidad_blisters_sellout")
    )
    return (
        sellin_agg.join(sellout_agg, on=dims, how="full_outer")
        .withColumn(
            "cantidad_blisters_sellin",
            F.coalesce(F.col("cantidad_blisters_sellin"), F.lit(0)),
        )
        .withColumn(
            "cantidad_blisters_sellout",
            F.coalesce(F.col("cantidad_blisters_sellout"), F.lit(0)),
        )
        .withColumn(
            "gap_blisters",
            F.col("cantidad_blisters_sellin") - F.col("cantidad_blisters_sellout"),
        )
    )


def main() -> None:
    map_sku = read_latest_snapshot(MAP_SKU_PATH, ["matnr"])
    map_cedi = read_latest_snapshot(MAP_CEDI_PATH, ["werks"])
    sell_in = read_latest_snapshot(SELL_IN_PATH, ["id"]).withColumn(
        # Debezium codifica DATE de Postgres como dias desde epoch (INT32).
        "fecha",
        F.expr("date_add(DATE'1970-01-01', fecha)"),
    )
    edicom = read_edicom_sellout()

    matched = build_sellout_matched(edicom, map_sku, map_cedi)
    quarantine = split_quarantine(matched)
    sellout_clean = build_sellout_clean(matched)
    sellin_normalized = build_sellin_normalized(sell_in, map_sku, map_cedi)
    sellthrough = build_sellthrough(sellin_normalized, sellout_clean)

    (
        sellthrough.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(SELLTHROUGH_TABLE)
    )
    (
        quarantine.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(QUARANTINE_TABLE)
    )

    n_sellthrough = spark.table(SELLTHROUGH_TABLE).count()
    n_quarantine = spark.table(QUARANTINE_TABLE).count()
    n_edicom_total = edicom.count()

    print(f"EDICOM Sell-Out total:        {n_edicom_total}")
    print(
        f"gold_farma_sellthrough:       {n_sellthrough} filas (matnr x werks x fecha)"
    )
    print(f"gold_farma_quarantine:        {n_quarantine} filas")

    result_json = json.dumps(
        {
            "edicom_total": n_edicom_total,
            "gold_farma_sellthrough_count": n_sellthrough,
            "gold_farma_quarantine_count": n_quarantine,
        }
    )
    print(result_json)

    try:
        dbutils.notebook.exit(result_json)  # noqa: F821
    except NameError:
        pass


if __name__ == "__main__":
    main()
