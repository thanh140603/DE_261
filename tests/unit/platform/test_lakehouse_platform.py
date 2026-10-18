"""Spark configuration and Kafka topic catalogue (pure parts of the platform layer)."""

from __future__ import annotations

from pathlib import Path

import yaml

from edu_platform.platform.batch.spark_session import spark_conf
from edu_platform.platform.config import LakehouseSettings, Settings, SparkSettings
from edu_platform.platform.messaging.admin import topic_specs
from edu_platform.platform.messaging.topics import Topic

TOPICS_YAML = Path(__file__).resolve().parents[3] / "infra/kafka/topics.yaml"


def test_spark_conf_wires_delta_s3_and_metastore() -> None:
    settings = Settings(
        lakehouse=LakehouseSettings(s3_endpoint="http://minio:9000", s3_access_key="k"),
        spark=SparkSettings(hive_metastore_uri="thrift://hive-metastore:9083"),
    )
    conf = spark_conf(settings)
    assert conf["spark.sql.extensions"] == "io.delta.sql.DeltaSparkSessionExtension"
    assert conf["spark.sql.sources.partitionOverwriteMode"] == "dynamic"
    assert conf["spark.hadoop.fs.s3a.endpoint"] == "http://minio:9000"
    assert conf["spark.hadoop.fs.s3a.connection.ssl.enabled"] == "false"
    assert conf["spark.hadoop.hive.metastore.uris"] == "thrift://hive-metastore:9083"


def test_spark_conf_without_metastore_uses_embedded_catalog() -> None:
    conf = spark_conf(Settings(spark=SparkSettings(hive_metastore_uri=None)))
    assert "spark.sql.catalogImplementation" not in conf
    assert not any(k.startswith("spark.hadoop.fs.s3a") for k in conf if "endpoint" in k)


def test_topic_catalogue_covers_every_topic_constant() -> None:
    catalogue = yaml.safe_load(TOPICS_YAML.read_text())
    declared = {t["name"] for t in catalogue["topics"]}
    assert {t.value for t in Topic} <= declared


def test_topic_specs_apply_defaults_and_overrides() -> None:
    catalogue = {
        "defaults": {"partitions": 6, "replication_factor": 1, "config": {"retention.ms": 1}},
        "topics": [{"name": "a", "partitions": 24, "config": {"cleanup.policy": "compact"}}],
    }
    [spec] = topic_specs(catalogue, replication_factor=3)
    assert spec == {
        "name": "a",
        "partitions": 24,
        "replication_factor": 3,
        "config": {"retention.ms": "1", "cleanup.policy": "compact"},
    }
