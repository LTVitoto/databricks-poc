"""Capa Gold: P&L consolidado IFRS 18 con eliminacion intercompany (IFRS 10)
y segmentacion por sociedad (IFRS 8).

Lee los Parquet crudos (envelope Debezium) de `acdoca` e `ifrs18_fsv_map`
desde el Volume de landing, deduplica por clave usando el `ts_ms` de nivel
raiz del envelope (mismo criterio que la capa Silver), cruza por `RACCT` y
persiste el resultado como tabla Delta gobernada en Unity Catalog (con
restricciones `CHECK` de calidad de datos). Las eliminaciones intercompany
(`RASSC IS NOT NULL`, IFRS 10) se filtran solo al momento de agregar el P&L,
no al escribir la tabla Gold (que conserva todas las lineas para trazabilidad).

El signo de `KSL`/`HSL` sigue la convencion contable SAP (credito negativo,
debito positivo). Las metricas de utilidad que se presentan se invierten de
signo (`-SUM(ksl)`) para mostrarse como un numero positivo cuando hay ganancia.
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

ACDOCA_PATH = f"{VOLUME_ROOT}/topics/sap.public.acdoca/"
MAP_PATH = f"{VOLUME_ROOT}/topics/sap.public.ifrs18_fsv_map/"
GOLD_TABLE = f"{CATALOG}.{SCHEMA}.gold_acdoca_ifrs18"

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


def build_enriched(acdoca: DataFrame, fsv_map: DataFrame) -> DataFrame:
    return acdoca.join(fsv_map, on="racct", how="left")


def write_gold_table(enriched: DataFrame) -> None:
    (
        enriched.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(GOLD_TABLE)
    )


def add_constraint_if_absent(name: str, expression: str) -> None:
    try:
        spark.sql(
            f"ALTER TABLE {GOLD_TABLE} ADD CONSTRAINT {name} CHECK ({expression})"
        )
    except Exception as exc:
        if "already exists" not in str(exc).lower():
            raise


def enforce_data_quality() -> None:
    add_constraint_if_absent(
        "chk_ifrs18_category",
        "ifrs18_category IN ('Operating', 'Investing', 'Financing', 'Taxes')",
    )
    add_constraint_if_absent("chk_ksl_not_null", "ksl IS NOT NULL")


def pl_by_category(consolidated: DataFrame) -> DataFrame:
    return (
        consolidated.groupBy("ifrs18_category")
        .agg((-F.sum("ksl")).alias("resultado_ksl"))
        .orderBy("ifrs18_category")
    )


def operating_profit_and_ebitda_by_segment(consolidated: DataFrame) -> DataFrame:
    operating = consolidated.filter(F.col("ifrs18_category") == "Operating")
    return (
        operating.groupBy("rbukrs")
        .agg(
            (-F.sum("ksl")).alias("operating_profit_ksl"),
            F.sum(
                F.when(F.col("mpm_tag") == "EBITDA_ADJUSTED", F.col("ksl")).otherwise(0)
            ).alias("depreciacion_addback_ksl"),
        )
        .withColumn(
            "ebitda_ajustado_ksl",
            F.col("operating_profit_ksl") + F.col("depreciacion_addback_ksl"),
        )
        .orderBy("rbukrs")
    )


def intercompany_summary(gold: DataFrame) -> DataFrame:
    return (
        gold.filter(F.col("rassc").isNotNull())
        .groupBy("rbukrs", "rassc")
        .agg(
            F.count("*").alias("lineas_eliminadas"), F.sum("ksl").alias("ksl_eliminado")
        )
    )


def main() -> None:
    acdoca = read_latest_snapshot(
        ACDOCA_PATH, ["rclnt", "rldnr", "rbukrs", "gjahr", "belnr", "docln"]
    )
    fsv_map = read_latest_snapshot(MAP_PATH, ["racct"])

    enriched = build_enriched(acdoca, fsv_map)
    write_gold_table(enriched)
    enforce_data_quality()

    gold = spark.table(GOLD_TABLE)
    consolidated = gold.filter(F.col("rassc").isNull())  # IFRS 10 elimination

    category_df = pl_by_category(consolidated)
    segment_df = operating_profit_and_ebitda_by_segment(consolidated)
    ic_df = intercompany_summary(gold)

    category_df.show(truncate=False)
    segment_df.show(truncate=False)
    ic_df.show(truncate=False)

    result = {
        "gold_table": GOLD_TABLE,
        "pl_por_categoria_ifrs18": [row.asDict() for row in category_df.collect()],
        "operating_profit_ebitda_por_segmento_ifrs8": [
            row.asDict() for row in segment_df.collect()
        ],
        "intercompany_eliminado_ifrs10": [row.asDict() for row in ic_df.collect()],
    }
    result_json = json.dumps(result, indent=2, default=str)
    print(result_json)

    try:
        dbutils.notebook.exit(result_json)  # noqa: F821
    except NameError:
        pass


if __name__ == "__main__":
    main()
