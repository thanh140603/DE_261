"""One local Spark session for every ``spark``-marked test module.

A JVM resolves ``spark.jars.packages`` only when it starts, so per-module sessions with
different packages break when modules run in one pytest process (the first session wins).
This session loads everything the modules need: Delta Lake and the Kafka connector.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture(scope="session")
def spark_session(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    pyspark = pytest.importorskip("pyspark")
    pytest.importorskip("delta")
    if shutil.which("java") is None:
        pytest.skip("a JDK is required for Spark")
    from delta import configure_spark_with_delta_pip
    from pyspark.sql import SparkSession

    scala = "2.13" if pyspark.__version__.startswith("4") else "2.12"
    root = tmp_path_factory.mktemp("spark")
    builder = (
        SparkSession.builder.appName("edu-integration-tests")
        .master("local[2]")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.warehouse.dir", str(root / "spark-warehouse"))
        .config("spark.ui.enabled", "false")
    )
    kafka = f"org.apache.spark:spark-sql-kafka-0-10_{scala}:{pyspark.__version__}"
    session = configure_spark_with_delta_pip(builder, extra_packages=[kafka]).getOrCreate()
    yield session
    session.stop()
