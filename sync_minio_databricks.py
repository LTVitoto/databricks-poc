#!/usr/bin/env python3
"""Script puente: sincroniza Parquet nuevos de MinIO (landing-zone) hacia un
Volume de Databricks.

Usa el Databricks CLI (``databricks fs cp``) ya autenticado localmente.
Idempotente: guarda el ETag de cada objeto ya subido en un archivo de estado
local y solo sube objetos nuevos o modificados.
"""

import argparse
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "landing-zone")
MINIO_PREFIX = os.environ.get("MINIO_PREFIX", "topics/")

DATABRICKS_VOLUME_ROOT = os.environ.get(
    "DATABRICKS_VOLUME_ROOT", "dbfs:/Volumes/mi_test_catalogo/default/paquet_demo"
)
DATABRICKS_PROFILE = os.environ.get("DATABRICKS_CLI_PROFILE", "DEFAULT")

STATE_FILE = Path(
    os.environ.get("SYNC_STATE_FILE", str(Path(__file__).with_name(".sync_state.json")))
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync_minio_databricks")

_created_dirs: set[str] = set()


def load_state() -> dict[str, str]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict[str, str]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def make_s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )


def list_pending_objects(s3: Any, state: dict[str, str]) -> list[dict[str, Any]]:
    pending = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=MINIO_BUCKET, Prefix=MINIO_PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            etag = obj["ETag"].strip('"')
            if state.get(key) != etag:
                pending.append({"key": key, "etag": etag, "size": obj["Size"]})
    return pending


def ensure_remote_dir(target_dir: str) -> None:
    if target_dir in _created_dirs:
        return
    subprocess.run(
        ["databricks", "fs", "mkdir", target_dir, "--profile", DATABRICKS_PROFILE],
        check=True,
        capture_output=True,
        text=True,
    )
    _created_dirs.add(target_dir)


def upload_to_volume(local_path: Path, relative_key: str) -> None:
    target_path = f"{DATABRICKS_VOLUME_ROOT}/{relative_key}"
    target_dir = target_path.rsplit("/", 1)[0]
    ensure_remote_dir(target_dir)
    subprocess.run(
        [
            "databricks",
            "fs",
            "cp",
            str(local_path),
            target_path,
            "--overwrite",
            "--profile",
            DATABRICKS_PROFILE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def sync_once(s3: Any, state: dict[str, str]) -> int:
    pending = list_pending_objects(s3, state)
    if not pending:
        return 0
    log.info("Objetos pendientes de subir: %d", len(pending))
    synced = 0
    with tempfile.TemporaryDirectory() as tmp_dir:
        for item in pending:
            key = item["key"]
            local_path = Path(tmp_dir) / Path(key).name
            try:
                s3.download_file(MINIO_BUCKET, key, str(local_path))
                upload_to_volume(local_path, key)
                state[key] = item["etag"]
                synced += 1
                log.info("OK  %s (%d bytes)", key, item["size"])
            except (ClientError, subprocess.CalledProcessError) as exc:
                detail = (
                    exc.stderr
                    if isinstance(exc, subprocess.CalledProcessError)
                    else exc
                )
                log.error("FALLO %s: %s", key, detail)
            finally:
                if local_path.exists():
                    local_path.unlink()
    save_state(state)
    return synced


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecuta un solo ciclo de sincronizacion y termina.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("SYNC_POLL_INTERVAL", "5")),
        help="Segundos entre ciclos de polling (default: 5).",
    )
    args = parser.parse_args()

    log.info(
        "Puente MinIO -> Databricks Volume. bucket=%s volume=%s",
        MINIO_BUCKET,
        DATABRICKS_VOLUME_ROOT,
    )
    s3 = make_s3_client()
    state = load_state()

    if args.once:
        synced = sync_once(s3, state)
        log.info("Ciclo unico completo: %d objetos sincronizados", synced)
        return

    while True:
        try:
            synced = sync_once(s3, state)
            if synced:
                log.info("Ciclo completo: %d objetos sincronizados", synced)
        except Exception:
            log.exception("Error inesperado en el ciclo de sincronizacion")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
