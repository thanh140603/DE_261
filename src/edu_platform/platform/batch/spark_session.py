"""SparkSession factory with Delta Lake, S3A and the shared Hive Metastore configured.

Every Spark entrypoint (batch jobs, the streaming landing job) builds its session here so
the lakehouse behaves the same everywhere:
- Delta SQL extensions + DeltaCatalog, UTC session time zone, AQE on.
- ``fs.s3a.*`` from settings (MinIO locally, S3 elsewhere); path-style addressing.
- Hive Metastore as the catalog when ``EDU_HIVE_METASTORE_URI`` is set (ADR 0010), so the
  tables Spark creates are immediately queryable from Trino.
- Dynamic partition overwrite: ``INSERT OVERWRITE`` replaces only the partitions it writes,
  which is what makes the window-strategy gold builds idempotent.
- Schema auto-merge stays off - schema evolution is explicit and versioned (warehouse/ddl).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from edu_platform.platform.config import Settings


def spark_conf(settings: Settings) -> dict[str, str]:
    """Spark configuration derived from settings (pure, unit-testable)."""
    conf = {
        "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
        "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        "spark.sql.session.timeZone": "UTC",
        "spark.sql.adaptive.enabled": "true",
        "spark.sql.shuffle.partitions": str(settings.spark.spark_shuffle_partitions),
        "spark.sql.sources.partitionOverwriteMode": "dynamic",
        "spark.databricks.delta.schema.autoMerge.enabled": "false",
        "spark.ui.showConsoleProgress": "false",
    }
    lake = settings.lakehouse
    if lake.s3_endpoint:
        conf |= {
            "spark.hadoop.fs.s3a.endpoint": lake.s3_endpoint,
            "spark.hadoop.fs.s3a.path.style.access": "true",
            "spark.hadoop.fs.s3a.connection.ssl.enabled": str(
                lake.s3_endpoint.startswith("https")
            ).lower(),
            "spark.hadoop.fs.s3a.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
            "spark.hadoop.fs.s3a.aws.credentials.provider": (
                "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider"
            ),
        }
        if lake.s3_access_key:
            conf["spark.hadoop.fs.s3a.access.key"] = lake.s3_access_key
        if lake.s3_secret_key:
            conf["spark.hadoop.fs.s3a.secret.key"] = lake.s3_secret_key.get_secret_value()
    if settings.spark.hive_metastore_uri:
        conf |= {
            "spark.sql.catalogImplementation": "hive",
            "spark.hadoop.hive.metastore.uris": settings.spark.hive_metastore_uri,
        }
    return conf


def build_spark(
    app_name: str, settings: Settings, extra_conf: Mapping[str, str] | None = None
) -> Any:
    """Return a configured SparkSession (pyspark is imported lazily: optional extra)."""
    from pyspark.sql import SparkSession

    builder = SparkSession.builder.appName(app_name).master(settings.spark.spark_master)
    for key, value in (spark_conf(settings) | dict(extra_conf or {})).items():
        builder = builder.config(key, value)
    if settings.spark.hive_metastore_uri:
        builder = builder.enableHiveSupport()
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
