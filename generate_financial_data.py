"""Genera datos financieros simulados (VBRK/VBRP/ACDOCA/IFRS18_FSV_MAP) en
Postgres para la Fase 2 (Consolidacion IFRS 10/8/18).

Idempotente: crea las tablas si no existen y las vacia (TRUNCATE) antes de
poblarlas, para poder re-ejecutarse sin duplicar datos.
"""

import itertools
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

RCLNT = "100"
RLDNR = "0L"
GJAHR = "2026"

SALES_PAIRS_PER_COMPANY = 800
NON_SALES_BUCKETS = [
    # (racct, cantidad, signo, rango_monto, fkber)
    ("600000", 150, 1, (500, 5000), "FERT"),
    ("620000", 100, 1, (1000, 8000), "FERT"),
    ("650000", 100, None, (50, 2000), "VERT"),
    ("700000", 150, -1, (500, 6000), "TRES"),
    ("710000", 100, None, (50, 1500), "TRES"),
    ("800000", 150, 1, (1000, 9000), "TRES"),
    ("810000", 50, None, (50, 1500), "TRES"),
    ("900000", 100, 1, (800, 7000), "STEU"),
]

IFRS18_ACCOUNTS = [
    ("400000", "Ventas Externas", "Operating", False, None),
    ("500000", "Costo de Ventas (COGS)", "Operating", False, None),
    ("600000", "Gastos Operativos Generales", "Operating", False, None),
    ("620000", "Depreciacion y Amortizacion", "Operating", False, "EBITDA_ADJUSTED"),
    ("650000", "Diferencia de Cambio Operativa", "Operating", True, None),
    ("700000", "Resultado por Inversiones", "Investing", False, None),
    ("710000", "Diferencia de Cambio sobre Inversiones", "Investing", True, None),
    ("800000", "Gastos de Intereses (Deuda)", "Financing", False, None),
    ("810000", "Diferencia de Cambio sobre Deuda", "Financing", True, None),
    ("900000", "Impuesto a las Ganancias", "Taxes", False, None),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("generate_financial_data")

_doc_counter = itertools.count(1)


def next_doc_number() -> str:
    return f"9{next(_doc_counter):09d}"


@dataclass
class CompanyProfile:
    bukrs: str
    currency: str
    segment: str
    kunnr_pool: list[str]
    intercompany_kunnr: str
    price_range: tuple[float, float]
    fx_to_group: float
    intercompany_pct: float


PROFILES = [
    CompanyProfile(
        bukrs="AU",
        currency="AUD",
        segment="MINERIA_AU",
        kunnr_pool=[f"20000000{i:02d}" for i in range(1, 51)],
        intercompany_kunnr="90000000BR",
        price_range=(5000.0, 50000.0),
        fx_to_group=0.65,
        intercompany_pct=0.15,
    ),
    CompanyProfile(
        bukrs="BR",
        currency="BRL",
        segment="INDUSTRIAL_BR",
        kunnr_pool=[f"30000000{i:02d}" for i in range(1, 51)],
        intercompany_kunnr="",
        price_range=(200.0, 5000.0),
        fx_to_group=0.19,
        intercompany_pct=0.0,
    ),
]


def connect() -> Any:
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD
    )


def ensure_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ifrs18_fsv_map (
                racct VARCHAR(10) PRIMARY KEY,
                account_desc VARCHAR(60) NOT NULL,
                ifrs18_category VARCHAR(20) NOT NULL
                    CHECK (ifrs18_category IN
                        ('Operating', 'Investing', 'Financing', 'Taxes')),
                is_fx_account BOOLEAN NOT NULL DEFAULT FALSE,
                mpm_tag VARCHAR(30)
            );

            CREATE TABLE IF NOT EXISTS vbrk (
                vbeln VARCHAR(10) PRIMARY KEY,
                bukrs VARCHAR(4) NOT NULL,
                kunnr VARCHAR(10) NOT NULL,
                fkdat DATE NOT NULL,
                netwr NUMERIC(15, 2) NOT NULL,
                waerk VARCHAR(5) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vbrp (
                vbeln VARCHAR(10) NOT NULL REFERENCES vbrk(vbeln),
                posnr VARCHAR(6) NOT NULL,
                matnr VARCHAR(18),
                matkl VARCHAR(20),
                prctr VARCHAR(10),
                netwr NUMERIC(15, 2) NOT NULL,
                PRIMARY KEY (vbeln, posnr)
            );

            CREATE TABLE IF NOT EXISTS acdoca (
                rclnt VARCHAR(3) NOT NULL,
                rldnr VARCHAR(2) NOT NULL,
                rbukrs VARCHAR(4) NOT NULL,
                gjahr VARCHAR(4) NOT NULL,
                belnr VARCHAR(10) NOT NULL,
                docln VARCHAR(6) NOT NULL,
                racct VARCHAR(10) NOT NULL REFERENCES ifrs18_fsv_map(racct),
                segment VARCHAR(20),
                prctr VARCHAR(10),
                fkber VARCHAR(10),
                hsl NUMERIC(15, 2) NOT NULL,
                ksl NUMERIC(15, 2) NOT NULL,
                rassc VARCHAR(10),
                PRIMARY KEY (rclnt, rldnr, rbukrs, gjahr, belnr, docln)
            );

            ALTER TABLE vbrk REPLICA IDENTITY FULL;
            ALTER TABLE vbrp REPLICA IDENTITY FULL;
            ALTER TABLE acdoca REPLICA IDENTITY FULL;
            ALTER TABLE ifrs18_fsv_map REPLICA IDENTITY FULL;
            """)
    conn.commit()


def reset_data(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE acdoca, vbrp, vbrk, ifrs18_fsv_map;")
    conn.commit()


def load_ifrs18_fsv_map(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO ifrs18_fsv_map
                (racct, account_desc, ifrs18_category, is_fx_account, mpm_tag)
            VALUES (%s, %s, %s, %s, %s)
            """,
            IFRS18_ACCOUNTS,
        )
    conn.commit()


def random_date_2026() -> date:
    start = date(2026, 1, 1)
    return start + timedelta(days=random.randint(0, 299))


def generate_sales(conn: Any, profile: CompanyProfile) -> int:
    acdoca_rows: list[tuple[Any, ...]] = []
    vbrk_rows: list[tuple[Any, ...]] = []
    vbrp_rows: list[tuple[Any, ...]] = []

    remaining_items = SALES_PAIRS_PER_COMPANY
    ic_items_target = round(SALES_PAIRS_PER_COMPANY * profile.intercompany_pct)
    ic_items_assigned = 0

    while remaining_items > 0:
        items_in_doc = min(remaining_items, random.randint(2, 6))
        remaining_items -= items_in_doc
        vbeln = next_doc_number()
        is_ic_doc = ic_items_assigned < ic_items_target and profile.intercompany_kunnr
        kunnr = (
            profile.intercompany_kunnr
            if is_ic_doc
            else random.choice(profile.kunnr_pool)
        )
        doc_total = 0.0
        docln_seq = itertools.count(1)

        for item_idx in range(1, items_in_doc + 1):
            unit_amount = round(random.uniform(*profile.price_range), 2)
            posnr = f"{item_idx * 10:06d}"
            prctr = f"PC-{profile.bukrs}-{random.choice(['MIN1', 'MIN2'])}"
            vbrp_rows.append(
                (
                    vbeln,
                    posnr,
                    f"MAT-{profile.bukrs}-{item_idx:03d}",
                    profile.segment,
                    prctr,
                    unit_amount,
                )
            )
            doc_total += unit_amount

            rassc = profile.intercompany_kunnr[-2:] if is_ic_doc else None
            if is_ic_doc:
                ic_items_assigned += 1

            revenue_hsl = -unit_amount
            cogs_hsl = round(unit_amount * 0.6, 2)

            acdoca_rows.append(
                (
                    RCLNT,
                    RLDNR,
                    profile.bukrs,
                    GJAHR,
                    vbeln,
                    f"{next(docln_seq):06d}",
                    "400000",
                    profile.segment,
                    prctr,
                    "VERT",
                    revenue_hsl,
                    round(revenue_hsl * profile.fx_to_group, 2),
                    rassc,
                )
            )
            acdoca_rows.append(
                (
                    RCLNT,
                    RLDNR,
                    profile.bukrs,
                    GJAHR,
                    vbeln,
                    f"{next(docln_seq):06d}",
                    "500000",
                    profile.segment,
                    prctr,
                    "VERT",
                    cogs_hsl,
                    round(cogs_hsl * profile.fx_to_group, 2),
                    rassc,
                )
            )

        vbrk_rows.append(
            (
                vbeln,
                profile.bukrs,
                kunnr,
                random_date_2026(),
                round(doc_total, 2),
                profile.currency,
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO vbrk (vbeln, bukrs, kunnr, fkdat, netwr, waerk) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            vbrk_rows,
        )
        cur.executemany(
            "INSERT INTO vbrp (vbeln, posnr, matnr, matkl, prctr, netwr) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            vbrp_rows,
        )
        cur.executemany(
            "INSERT INTO acdoca (rclnt, rldnr, rbukrs, gjahr, belnr, docln, racct, "
            "segment, prctr, fkber, hsl, ksl, rassc) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            acdoca_rows,
        )
    conn.commit()
    return len(acdoca_rows)


def generate_non_sales(conn: Any, profile: CompanyProfile) -> int:
    rows: list[tuple[Any, ...]] = []
    for racct, count, sign, amount_range, fkber in NON_SALES_BUCKETS:
        for _ in range(count):
            amount = round(random.uniform(*amount_range), 2)
            effective_sign = sign if sign is not None else random.choice([1, -1])
            hsl = effective_sign * amount
            belnr = next_doc_number()
            prctr = f"PC-{profile.bukrs}-{random.choice(['MIN1', 'MIN2'])}"
            rows.append(
                (
                    RCLNT,
                    RLDNR,
                    profile.bukrs,
                    GJAHR,
                    belnr,
                    "000001",
                    racct,
                    profile.segment,
                    prctr,
                    fkber,
                    hsl,
                    round(hsl * profile.fx_to_group, 2),
                    None,
                )
            )
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO acdoca (rclnt, rldnr, rbukrs, gjahr, belnr, docln, racct, "
            "segment, prctr, fkber, hsl, ksl, rassc) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    conn.commit()
    return len(rows)


def main() -> None:
    conn = connect()
    try:
        ensure_schema(conn)
        reset_data(conn)
        load_ifrs18_fsv_map(conn)
        for profile in PROFILES:
            sales_lines = generate_sales(conn, profile)
            non_sales_lines = generate_non_sales(conn, profile)
            log.info(
                "%s: %d lineas ACDOCA (%d ventas + %d no-ventas)",
                profile.bukrs,
                sales_lines + non_sales_lines,
                sales_lines,
                non_sales_lines,
            )
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM acdoca;")
            total = cur.fetchone()[0]
            cur.execute("SELECT rbukrs, COUNT(*) FROM acdoca GROUP BY rbukrs;")
            by_company = cur.fetchall()
        log.info("Total ACDOCA: %d | por sociedad: %s", total, by_company)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
