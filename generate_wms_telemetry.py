"""Genera telemetria WMS simulada en Postgres (`wms_telemetry`): eventos de
consumo de las 3 dimensiones ABC pedidas -- Tiempo (Segundos_Efectivos),
Transaccional (Movimientos_Pallet) y Volumen (Cajas_Despachadas) -- ligados
a un SKU y un Pedido, taggeados con el `ID_RECURSO_POOL` exacto del maestro
de drivers (`silver_maestro_drivers_abc`) para permitir un JOIN 1:1 sin
fan-out en el motor ABC.

Idempotente: crea la tabla si no existe y la vacia (TRUNCATE) antes de
poblarla.
"""

import logging
import os
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import psycopg2

PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_DB = os.environ.get("PG_DB", "sapdb")
PG_USER = os.environ.get("PG_USER", "sapadmin")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "sappassword")

CENTROS_COSTO = ["CL_CD0100", "CL_CD0200", "CL_CD0300"]
SKUS = [f"SKU-ABC-{i:03d}" for i in range(1, 16)]
N_PEDIDOS = 500
HISTORY_DAYS = 30
EVENTS_PER_DAY_RANGE = (80, 120)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("generate_wms_telemetry")


@dataclass
class DimensionSpec:
    dimension_driver: str
    resource_pools: list[str]
    cantidad_range: tuple[float, float]


DIMENSIONES = [
    DimensionSpec(
        "Segundos_Efectivos",
        ["DRV_MOD_CUADRILLA", "DRV_MOD_TRIAJE"],
        (30.0, 600.0),
    ),
    DimensionSpec("Movimientos_Pallet", ["DRV_EQP_GRUA"], (1.0, 20.0)),
    DimensionSpec("Cajas_Despachadas", ["DRV_MAT_EMBALAJE"], (1.0, 100.0)),
]

PEDIDOS = [f"PED-{i:06d}" for i in range(1, N_PEDIDOS + 1)]


def connect() -> Any:
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD
    )


def ensure_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wms_telemetry (
                id BIGSERIAL PRIMARY KEY,
                sku VARCHAR(20) NOT NULL,
                pedido VARCHAR(20) NOT NULL,
                centro_costo_origen VARCHAR(20) NOT NULL,
                id_recurso_pool VARCHAR(30) NOT NULL,
                dimension_driver VARCHAR(30) NOT NULL,
                cantidad_consumida NUMERIC(15, 4) NOT NULL,
                fecha DATE NOT NULL
            );
            ALTER TABLE wms_telemetry REPLICA IDENTITY FULL;
            """)
    conn.commit()


def reset_data(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE wms_telemetry;")
    conn.commit()


def generate_events(conn: Any) -> int:
    rows: list[tuple[Any, ...]] = []
    start = date.today() - timedelta(days=HISTORY_DAYS)
    for day_offset in range(HISTORY_DAYS):
        fecha = start + timedelta(days=day_offset)
        n_events = random.randint(*EVENTS_PER_DAY_RANGE)
        for _ in range(n_events):
            dim = random.choice(DIMENSIONES)
            resource_pool = random.choice(dim.resource_pools)
            cantidad = round(random.uniform(*dim.cantidad_range), 4)
            rows.append(
                (
                    random.choice(SKUS),
                    random.choice(PEDIDOS),
                    random.choice(CENTROS_COSTO),
                    resource_pool,
                    dim.dimension_driver,
                    cantidad,
                    fecha,
                )
            )
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO wms_telemetry "
            "(sku, pedido, centro_costo_origen, id_recurso_pool, "
            "dimension_driver, cantidad_consumida, fecha) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    conn.commit()
    return len(rows)


def main() -> None:
    conn = connect()
    try:
        ensure_schema(conn)
        reset_data(conn)
        total = generate_events(conn)
        log.info(
            "wms_telemetry: %d filas (%d dias, %d CEDIs, %d dimensiones)",
            total,
            HISTORY_DAYS,
            len(CENTROS_COSTO),
            len(DIMENSIONES),
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
