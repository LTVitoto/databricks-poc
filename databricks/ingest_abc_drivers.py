# Databricks notebook source
# MAGIC %pip install -q openpyxl

# COMMAND ----------

"""Ingesta el maestro de drivers ABC (`CL_Drivers_ABC_Full.xlsx`) desde la
zona Bronze y lo consolida en `silver_maestro_drivers_abc`.

El archivo llega al Volume de Databricks via el bridge ya existente
(`sync_minio_databricks.py`, que sincroniza todo el bucket `landing-zone`
sin filtro de prefijo) -- no se usa boto3 directo contra MinIO desde
Databricks porque el bucket local (Docker, WSL2) no es alcanzable desde
compute cloud. Pandas lee el `.xlsx` ya sincronizado directamente desde el
path del Volume (montado como filesystem normal), que actua como el
"puente Pandas" pedido: consolida todas las pestanas del libro (logisticas
tipo `CL_CD0100` + la estrategica `CL_CORP`) taggeando cada fila con su
pestana de origen antes de convertir a Spark DataFrame.
"""

import json
import os
import re

import pandas as pd
from pyspark.sql import SparkSession

CATALOG = os.environ.get("SILVER_CATALOG", "mi_test_catalogo")
SCHEMA = os.environ.get("SILVER_SCHEMA", "default")
VOLUME_ROOT = os.environ.get(
    "LANDING_VOLUME_ROOT", f"/Volumes/{CATALOG}/{SCHEMA}/paquet_demo"
)

EXCEL_PATH = f"{VOLUME_ROOT}/bronze/abc_drivers/CL_Drivers_ABC_Full.xlsx"
TARGET_TABLE = f"{CATALOG}.{SCHEMA}.silver_maestro_drivers_abc"

spark = SparkSession.builder.getOrCreate()


def sanitize_column_name(name: str) -> str:
    # Delta no permite ' ,;{}()\n\t=' en nombres de columna (ej. columnas
    # del Excel como "CAPACIDAD_MENSUAL (Input)").
    sanitized = re.sub(r"[ ,;{}()\n\t=]+", "_", str(name))
    return re.sub(r"_+", "_", sanitized).strip("_")


def consolidate_sheets(path: str) -> pd.DataFrame:
    sheets = pd.read_excel(path, sheet_name=None)
    frames = []
    for sheet_name, df in sheets.items():
        df = df.copy()
        df.columns = [sanitize_column_name(c) for c in df.columns]
        df["CENTRO_COSTO_ORIGEN"] = sheet_name
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    consolidated_pdf = consolidate_sheets(EXCEL_PATH)
    sdf = spark.createDataFrame(consolidated_pdf)

    (
        sdf.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    count = spark.table(TARGET_TABLE).count()
    sheets_found = sorted(consolidated_pdf["CENTRO_COSTO_ORIGEN"].unique().tolist())

    print(f"{TARGET_TABLE}: {count} filas")
    print(f"Pestanas consolidadas: {sheets_found}")

    result_json = json.dumps({"rows": count, "sheets": sheets_found})
    print(result_json)

    try:
        dbutils.notebook.exit(result_json)  # noqa: F821
    except NameError:
        pass


if __name__ == "__main__":
    main()
