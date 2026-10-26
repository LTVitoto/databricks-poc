# Databricks notebook source
# MAGIC %pip install -q xgboost

# COMMAND ----------

"""Entrena ``xgboost.XGBRegressor`` sobre un DataFrame de Pandas extraido de
``gold_farma_provision_risk``, con el parche de Unity Catalog aplicado antes
de ``mlflow.start_run()`` para evitar la consulta bloqueada via Spark
Connect.
"""

import json
import os

import mlflow
import mlflow.tracking._model_registry.utils
import mlflow.xgboost
import xgboost as xgb
from pyspark.sql import SparkSession
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split

# 1. Parche para evitar que MLflow consulte a Spark Connect
mlflow.tracking._model_registry.utils._get_registry_uri_from_spark_session = (
    lambda: "databricks-uc"
)

# 2. Forzar URIs explicitos hacia Databricks y Unity Catalog
mlflow.set_tracking_uri("databricks")
mlflow.set_registry_uri("databricks-uc")

# 3. Desactivar autologging para evitar lecturas ocultas de Spark configs
mlflow.xgboost.autolog(disable=True)

CATALOG = os.environ.get("SILVER_CATALOG", "mi_test_catalogo")
SCHEMA = os.environ.get("SILVER_SCHEMA", "default")
SOURCE_TABLE = f"{CATALOG}.{SCHEMA}.gold_farma_provision_risk"

FEATURE_COLS = [
    "cantidad_blisters_sellin",
    "cantidad_blisters_sellout",
    "stock_on_hand",
    "stock_remanente",
    "dias_para_caducar",
    "costo_unitario_simulado",
]
LABEL_COL = "provision_risk_value"
PARAMS = {"max_depth": 5, "n_estimators": 100, "learning_rate": 0.1}

spark = SparkSession.builder.getOrCreate()


def main() -> None:
    sdf = spark.table(SOURCE_TABLE).select(*FEATURE_COLS, LABEL_COL).na.drop()
    pdf = sdf.toPandas()

    x = pdf[FEATURE_COLS]
    y = pdf[LABEL_COL]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=42
    )

    with mlflow.start_run(run_name="farma_provision_risk_xgboost") as run:
        mlflow.log_params(PARAMS)
        mlflow.log_param("feature_cols", ",".join(FEATURE_COLS))
        mlflow.log_param("label_col", LABEL_COL)
        mlflow.log_param("n_rows", len(pdf))

        xgb_model = xgb.XGBRegressor(**PARAMS, random_state=42)
        xgb_model.fit(x_train, y_train)

        predictions = xgb_model.predict(x_test)
        rmse = mean_squared_error(y_test, predictions) ** 0.5
        mlflow.log_metric("rmse", rmse)

        mlflow.xgboost.log_model(xgb_model, "farma_risk_xgboost")

        run_id = run.info.run_id
        model_uri = f"runs:/{run_id}/farma_risk_xgboost"

    print(f"RMSE: {rmse:.4f}")
    print(f"MLflow run_id: {run_id}")
    print(f"Model URI: {model_uri}")

    result_json = json.dumps(
        {"rmse": float(rmse), "run_id": run_id, "model_uri": model_uri}
    )
    print(result_json)

    try:
        dbutils.notebook.exit(result_json)  # noqa: F821
    except NameError:
        pass


if __name__ == "__main__":
    main()
