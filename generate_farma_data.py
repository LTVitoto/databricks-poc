"""Genera datos simulados de la rama Farma (Sell-In) en Postgres:
`map_cedi`, `map_sku` (maestros de homologacion EDICOM) y `farma_sell_in`
(entregas SAP a farmacias, ~1 anio de historia).

Idempotente: crea las tablas si no existen y las vacia (TRUNCATE) antes de
poblarlas, para poder re-ejecutarse sin duplicar datos.
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

HISTORY_DAYS = 365
DELIVERIES_PER_DAY_RANGE = (5, 15)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("generate_farma_data")


def ean13_with_check_digit(base12: str) -> str:
    digits = [int(d) for d in base12]
    total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits))
    check = (10 - (total % 10)) % 10
    return base12 + str(check)


@dataclass
class Cedi:
    werks: str
    nombre_cedi: str
    gln: str
    is_commercial: bool


@dataclass
class Sku:
    matnr: str
    descripcion: str
    ean13: str
    factor_caja_blister: int


CEDIS = [
    Cedi(
        "CEDI001", "CEDI Bogota Comercial", ean13_with_check_digit("770700100001"), True
    ),
    Cedi(
        "CEDI002",
        "CEDI Medellin Comercial",
        ean13_with_check_digit("770700100002"),
        True,
    ),
    Cedi(
        "CEDI003", "CEDI Cali Comercial", ean13_with_check_digit("770700100003"), True
    ),
    Cedi(
        "CEDI004",
        "CEDI Barranquilla CrossDock",
        ean13_with_check_digit("770700100004"),
        False,
    ),
    Cedi(
        "CEDI005",
        "CEDI Bucaramanga CrossDock",
        ean13_with_check_digit("770700100005"),
        False,
    ),
]

SKUS = [
    Sku(
        "MAT-FARMA-001",
        "Analgesico 500mg x20",
        ean13_with_check_digit("770123450001"),
        10,
    ),
    Sku(
        "MAT-FARMA-002",
        "Antigripal Jarabe 120ml",
        ean13_with_check_digit("770123450002"),
        6,
    ),
    Sku(
        "MAT-FARMA-003",
        "Antialergico 10mg x10",
        ean13_with_check_digit("770123450003"),
        12,
    ),
    Sku(
        "MAT-FARMA-004",
        "Antiacido Tabletas x30",
        ean13_with_check_digit("770123450004"),
        8,
    ),
    Sku(
        "MAT-FARMA-005",
        "Vitamina C 1g Efervescente x10",
        ean13_with_check_digit("770123450005"),
        5,
    ),
    Sku(
        "MAT-FARMA-006",
        "Antiinflamatorio 50mg x20",
        ean13_with_check_digit("770123450006"),
        10,
    ),
    Sku(
        "MAT-FARMA-007",
        "Antitusivo Jarabe 90ml",
        ean13_with_check_digit("770123450007"),
        6,
    ),
    Sku(
        "MAT-FARMA-008",
        "Suero Oral Sobres x5",
        ean13_with_check_digit("770123450008"),
        20,
    ),
]


def connect() -> Any:
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD
    )


def ensure_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS map_cedi (
                werks VARCHAR(10) PRIMARY KEY,
                nombre_cedi VARCHAR(60) NOT NULL,
                gln VARCHAR(13) NOT NULL,
                is_commercial BOOLEAN NOT NULL DEFAULT TRUE
            );

            CREATE TABLE IF NOT EXISTS map_sku (
                matnr VARCHAR(18) PRIMARY KEY,
                descripcion VARCHAR(80) NOT NULL,
                ean13 VARCHAR(13) NOT NULL,
                factor_caja_blister INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS farma_sell_in (
                id BIGSERIAL PRIMARY KEY,
                matnr VARCHAR(18) NOT NULL REFERENCES map_sku(matnr),
                werks VARCHAR(10) NOT NULL REFERENCES map_cedi(werks),
                lote VARCHAR(20) NOT NULL,
                cantidad_cajas INTEGER NOT NULL,
                fecha DATE NOT NULL
            );

            ALTER TABLE map_cedi REPLICA IDENTITY FULL;
            ALTER TABLE map_sku REPLICA IDENTITY FULL;
            ALTER TABLE farma_sell_in REPLICA IDENTITY FULL;
            """)
    conn.commit()


def reset_data(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE farma_sell_in, map_sku, map_cedi;")
    conn.commit()


def load_maps(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO map_cedi (werks, nombre_cedi, gln, is_commercial) "
            "VALUES (%s, %s, %s, %s)",
            [(c.werks, c.nombre_cedi, c.gln, c.is_commercial) for c in CEDIS],
        )
        cur.executemany(
            "INSERT INTO map_sku (matnr, descripcion, ean13, factor_caja_blister) "
            "VALUES (%s, %s, %s, %s)",
            [(s.matnr, s.descripcion, s.ean13, s.factor_caja_blister) for s in SKUS],
        )
    conn.commit()


def random_lote(fecha: date) -> str:
    return f"L{fecha.strftime('%y%m')}{random.randint(100, 999)}"


def generate_sell_in(conn: Any) -> int:
    rows: list[tuple[Any, ...]] = []
    start = date.today() - timedelta(days=HISTORY_DAYS)
    for day_offset in range(HISTORY_DAYS):
        fecha = start + timedelta(days=day_offset)
        deliveries_today = random.randint(*DELIVERIES_PER_DAY_RANGE)
        for _ in range(deliveries_today):
            cedi = random.choice(CEDIS)
            sku = random.choice(SKUS)
            rows.append(
                (
                    sku.matnr,
                    cedi.werks,
                    random_lote(fecha),
                    random.randint(5, 200),
                    fecha,
                )
            )
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO farma_sell_in (matnr, werks, lote, cantidad_cajas, fecha) "
            "VALUES (%s, %s, %s, %s, %s)",
            rows,
        )
    conn.commit()
    return len(rows)


def main() -> None:
    conn = connect()
    try:
        ensure_schema(conn)
        reset_data(conn)
        load_maps(conn)
        total = generate_sell_in(conn)
        log.info(
            "map_cedi: %d filas (%d comerciales)",
            len(CEDIS),
            sum(c.is_commercial for c in CEDIS),
        )
        log.info("map_sku: %d filas", len(SKUS))
        log.info("farma_sell_in: %d filas (%d dias de historia)", total, HISTORY_DAYS)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
