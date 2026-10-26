"""Simulador de broker EDI (EDICOM): genera mensajes de Sell-Out diarios y
los sube directo a MinIO (``s3://landing-zone/edicom/``), sin pasar por
Debezium/Kafka. Representa una fuente externa real, desacoplada de SAP.

Al iniciar hace un backfill de ``BACKFILL_DAYS`` dias y luego continua en un
loop, generando un dia nuevo de Sell-Out cada ``SIMULATION_INTERVAL_SECONDS``.
"""

import argparse
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import boto3

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "landing-zone")
MINIO_PREFIX = os.environ.get("MINIO_PREFIX", "edicom/sellout")

BACKFILL_DAYS = int(os.environ.get("EDICOM_BACKFILL_DAYS", "30"))
MESSAGES_PER_DAY_RANGE = (10, 30)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("edicom_simulator")


@dataclass
class PuntoVenta:
    gln: str
    nombre: str


# GLN de los CEDIs comerciales (map_cedi.is_commercial = True en
# generate_farma_data.py). El broker EDI solo ve Sell-Out de puntos
# comerciales, nunca de CEDIs de cross-docking.
PUNTOS_VENTA = [
    PuntoVenta("7707001000017", "CEDI Bogota Comercial"),
    PuntoVenta("7707001000024", "CEDI Medellin Comercial"),
    PuntoVenta("7707001000031", "CEDI Cali Comercial"),
]

# EAN-13 de los 8 SKUs (map_sku en generate_farma_data.py).
EANS = [
    "7701234500016",
    "7701234500023",
    "7701234500030",
    "7701234500047",
    "7701234500054",
    "7701234500061",
    "7701234500078",
    "7701234500085",
]


def make_s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )


def random_lote(fecha: date) -> str:
    return f"L{fecha.strftime('%y%m')}{random.randint(100, 999)}"


BAD_CODE_RATE = float(os.environ.get("EDICOM_BAD_CODE_RATE", "0.08"))


def maybe_corrupt(code: str) -> str:
    """Simula codigos de socio EDI sin homologar en las tablas maestras."""
    if random.random() < BAD_CODE_RATE:
        return str(random.randint(10**12, 10**13 - 1))
    return code


def generate_day_messages(fecha: date) -> list[dict[str, Any]]:
    n_messages = random.randint(*MESSAGES_PER_DAY_RANGE)
    messages = []
    for _ in range(n_messages):
        punto = random.choice(PUNTOS_VENTA)
        messages.append(
            {
                "gln": maybe_corrupt(punto.gln),
                "ean13": maybe_corrupt(random.choice(EANS)),
                "cantidad_blisters": random.randint(1, 50),
                "lote": random_lote(fecha),
                "fecha": fecha.isoformat(),
            }
        )
    return messages


def upload_day(s3: Any, fecha: date) -> int:
    messages = generate_day_messages(fecha)
    body = "\n".join(json.dumps(m) for m in messages)
    key = f"{MINIO_PREFIX}/date={fecha.isoformat()}/sellout_{fecha.isoformat()}.json"
    s3.put_object(Bucket=MINIO_BUCKET, Key=key, Body=body.encode("utf-8"))
    log.info("OK  %s (%d mensajes)", key, len(messages))
    return len(messages)


def backfill(s3: Any, days: int) -> None:
    start = date.today() - timedelta(days=days)
    for offset in range(days):
        upload_day(s3, start + timedelta(days=offset))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("SIMULATION_INTERVAL_SECONDS", "60")),
        help="Segundos entre cada dia simulado (default: 60).",
    )
    args = parser.parse_args()

    s3 = make_s3_client()

    log.info("Backfill inicial: %d dias", BACKFILL_DAYS)
    backfill(s3, BACKFILL_DAYS)

    current_day = date.today()
    log.info(
        "Simulacion continua iniciada. intervalo=%ss primer_dia=%s",
        args.interval,
        current_day.isoformat(),
    )
    while True:
        time.sleep(args.interval)
        current_day += timedelta(days=1)
        try:
            upload_day(s3, current_day)
        except Exception:
            log.exception("Error subiendo el dia %s", current_day.isoformat())


if __name__ == "__main__":
    main()
