"""Motor matematico FIFO de inventario en canal (Farma): lee
``gold_farma_sellthrough`` y genera ``gold_farma_provision_risk``.

Granularidad del "lote": cada fila de ``gold_farma_sellthrough`` (matnr x
werks x fecha) se trata como el lote recibido ese dia -- es la unica
granularidad disponible rio abajo del cruce Sell-In/Sell-Out (el `lote` de
EDICOM es independiente/no correlacionado con el `lote` real de SAP, por lo
que un FIFO a nivel de lote SAP real no es reconstruible con los datos
disponibles).

Costo unitario y vida util de anaquel son simulados (no existen en el modelo
de datos actual); se documentan como supuestos en ``FINANCIAL_MATH.md``.
"""

import os

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

CATALOG = os.environ.get("SILVER_CATALOG", "mi_test_catalogo")
SCHEMA = os.environ.get("SILVER_SCHEMA", "default")

SELLTHROUGH_TABLE = f"{CATALOG}.{SCHEMA}.gold_farma_sellthrough"
PROVISION_TABLE = f"{CATALOG}.{SCHEMA}.gold_farma_provision_risk"

SHELF_LIFE_DAYS = 270  # vida util de anaquel simulada (9 meses), uniforme
PROVISION_THRESHOLD_DAYS = 90

# Costo unitario simulado por blister (moneda grupo), fijo por SKU para
# reproducibilidad entre corridas (no aleatorio).
COSTOS_UNITARIOS = {
    "MAT-FARMA-001": 1.20,
    "MAT-FARMA-002": 0.85,
    "MAT-FARMA-003": 0.95,
    "MAT-FARMA-004": 0.60,
    "MAT-FARMA-005": 0.40,
    "MAT-FARMA-006": 1.10,
    "MAT-FARMA-007": 0.75,
    "MAT-FARMA-008": 0.30,
}

spark = SparkSession.builder.getOrCreate()


def costos_unitarios_df() -> DataFrame:
    rows = list(COSTOS_UNITARIOS.items())
    return spark.createDataFrame(rows, ["matnr", "costo_unitario_simulado"])


def with_running_totals(sellthrough: DataFrame) -> DataFrame:
    by_date = Window.partitionBy("matnr", "werks").orderBy("fecha")
    by_sku_cedi = Window.partitionBy("matnr", "werks")
    return (
        sellthrough.withColumn(
            "acumulado_sellin", F.sum("cantidad_blisters_sellin").over(by_date)
        )
        .withColumn(
            "acumulado_sellout", F.sum("cantidad_blisters_sellout").over(by_date)
        )
        .withColumn(
            "stock_on_hand", F.col("acumulado_sellin") - F.col("acumulado_sellout")
        )
        .withColumn("total_sellout_final", F.max("acumulado_sellout").over(by_sku_cedi))
    )


def with_fifo_remaining_stock(df: DataFrame) -> DataFrame:
    # FIFO: el lote (dia) i queda agotado si el consumo acumulado total ya
    # superó el acumulado de Sell-In hasta e incluyendo ese lote; si no ha
    # llegado a tocarlo, el lote permanece intacto; si cae justo en medio,
    # queda parcialmente consumido.
    remaining = F.col("acumulado_sellin") - F.col("total_sellout_final")
    clamped = F.greatest(
        F.lit(0), F.least(F.col("cantidad_blisters_sellin"), remaining)
    )
    return df.withColumn("stock_remanente", clamped)


def with_expiry_provision(df: DataFrame, costos: DataFrame) -> DataFrame:
    df = (
        df.withColumn("fecha_caducidad", F.date_add(F.col("fecha"), SHELF_LIFE_DAYS))
        .withColumn(
            "dias_para_caducar", F.datediff(F.col("fecha_caducidad"), F.current_date())
        )
        .join(F.broadcast(costos), on="matnr", how="left")
    )
    is_risk = (F.col("stock_remanente") > 0) & (
        F.col("dias_para_caducar") < PROVISION_THRESHOLD_DAYS
    )
    return df.withColumn("is_provision_risk", is_risk).withColumn(
        "provision_risk_value",
        F.when(
            is_risk, F.col("stock_remanente") * F.col("costo_unitario_simulado")
        ).otherwise(F.lit(0.0)),
    )


def main() -> None:
    sellthrough = spark.table(SELLTHROUGH_TABLE)
    costos = costos_unitarios_df()

    with_totals = with_running_totals(sellthrough)
    with_fifo = with_fifo_remaining_stock(with_totals)
    final = with_expiry_provision(with_fifo, costos).select(
        "matnr",
        "descripcion",
        "werks",
        "nombre_cedi",
        "fecha",
        "cantidad_blisters_sellin",
        "cantidad_blisters_sellout",
        "acumulado_sellin",
        "acumulado_sellout",
        "stock_on_hand",
        "stock_remanente",
        "fecha_caducidad",
        "dias_para_caducar",
        "costo_unitario_simulado",
        "is_provision_risk",
        "provision_risk_value",
    )

    (
        final.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(PROVISION_TABLE)
    )

    n_total = spark.table(PROVISION_TABLE).count()
    n_risk = spark.table(PROVISION_TABLE).filter(F.col("is_provision_risk")).count()
    total_risk_value = (
        spark.table(PROVISION_TABLE).agg(F.sum("provision_risk_value")).collect()[0][0]
        or 0.0
    )

    print(f"gold_farma_provision_risk: {n_total} filas totales")
    print(f"Lotes en riesgo de provision (<90 dias a caducar): {n_risk}")
    print(f"Impacto monetario total (provision_risk_value): {total_risk_value:.2f}")

    import json

    result_json = json.dumps(
        {
            "provision_rows_total": n_total,
            "provision_risk_rows": n_risk,
            "provision_risk_value_total": round(float(total_risk_value), 2),
        }
    )
    print(result_json)

    try:
        dbutils.notebook.exit(result_json)  # noqa: F821
    except NameError:
        pass


if __name__ == "__main__":
    main()
