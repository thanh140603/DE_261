"""SparkSession factory with Delta Lake + S3A configured.

Content (TODO):
- ``build_spark(app_name, settings)`` returning a SparkSession with:
    spark.sql.extensions = io.delta.sql.DeltaSparkSessionExtension
    spark.sql.catalog.spark_catalog = org.apache.spark.sql.delta.catalog.DeltaCatalog
    fs.s3a.* (endpoint / keys / path.style.access) for MinIO
    delta.schema.autoMerge disabled - schema evolution is explicit and versioned
- AQE on, shuffle partitions sized from env.
- Register shared UDFs (pseudonymise, parse_xapi_verb).
"""

from __future__ import annotations

from typing import Any

from edu_platform.platform.config import Settings


def build_spark(app_name: str, settings: Settings) -> Any:
    raise NotImplementedError  # TODO: see module docstring
