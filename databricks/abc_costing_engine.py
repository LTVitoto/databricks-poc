"""Motor de prorrateo ABC: cruza `silver_wms_telemetry` (consumo real por
SKU/Pedido) con `silver_maestro_drivers_abc` (tasa unitaria por recurso),
uniendo por (`centro_costo_origen`, `id_recurso_pool`) -- match 1:1 exacto
por pool de recurso, sin fan-out (ver nota en `generate_wms_telemetry.py`
sobre "Segundos_Efectivos" teniendo dos pools de recurso distintos).

El costo asignado por linea = cantidad_consumida * TASA_UNITARIA_CALCULADA.
Las filas de `CL_CORP` (drivers estrategicos) no tienen contraparte en WMS
y por lo tanto no matchean -- quedan fuera de este costeo operativo por
diseno (se usan en `mpm_reconciliation.py`, no aqui).
"""

import os

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

CATALOG = os.environ.get("SILVER_CATALOG", "mi_test_catalogo")
SCHEMA = os.environ.get("SILVER_SCHEMA", "default")

WMS_TABLE = f"{CATALOG}.{SCHEMA}.silver_wms_telemetry"
DRIVERS_TABLE = f"{CATALOG}.{SCHEMA}.silver_maestro_drivers_abc"
TARGET_TABLE = f"{CATALOG}.{SCHEMA}.gold_abc_operational_costs"

spark = SparkSession.builder.getOrCreate()


def main() -> None:
    wms = spark.table(WMS_TABLE)
    drivers = spark.table(DRIVERS_TABLE).filter(
        F.col("CENTRO_COSTO_ORIGEN") != "CL_CORP"
    )

    joined = wms.join(
        F.broadcast(drivers),
        on=(
            (wms.centro_costo_origen == drivers.CENTRO_COSTO_ORIGEN)
            & (wms.id_recurso_pool == drivers.ID_RECURSO_POOL)
        ),
        how="inner",
    )

    costed = joined.select(
        wms.id.alias("wms_telemetry_id"),
        wms.sku,
        wms.pedido,
        wms.centro_costo_origen,
        wms.id_recurso_pool,
        wms.dimension_driver,
        wms.cantidad_consumida,
        drivers.DESCRIPCION_RECURSO.alias("descripcion_recurso"),
        drivers.TASA_UNITARIA_CALCULADA.alias("tasa_unitaria_calculada"),
        (wms.cantidad_consumida * drivers.TASA_UNITARIA_CALCULADA).alias(
            "costo_asignado_linea"
        ),
        wms.fecha,
    )

    (
        costed.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    n_total = spark.table(TARGET_TABLE).count()
    n_wms = wms.count()
    total_cost = (
        spark.table(TARGET_TABLE).agg(F.sum("costo_asignado_linea")).collect()[0][0]
    )

    print(f"{TARGET_TABLE}: {n_total} filas costeadas de {n_wms} eventos WMS")
    print(f"Costo ABC total asignado: {total_cost:.2f}")


if __name__ == "__main__":
    main()
