"""Typed runtime configuration (12-factor: everything from env / .env).

All settings share the ``EDU_`` prefix so they never collide with Spark/Flink
environment variables inside the same container.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class KafkaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDU_KAFKA_")
    bootstrap_servers: str = "localhost:9092"
    security_protocol: str = "PLAINTEXT"
    consumer_group_prefix: str = "edu"


class LakehouseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDU_")
    lakehouse_root: str = "s3a://lakehouse"
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: SecretStr | None = None

    def layer_path(
        self, layer: Literal["bronze", "silver", "gold", "mart", "features", "ops"], table: str
    ) -> str:
        return f"{self.lakehouse_root}/{layer}/{table}"


class SparkSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDU_")
    spark_master: str = "local[*]"
    spark_shuffle_partitions: int = 8
    # Shared lakehouse catalog (ADR 0010). None = Spark's embedded catalog (unit/local runs).
    hive_metastore_uri: str | None = None
    # Folder with ddl/, transform/, quality/ and models.yaml (repo `warehouse/`).
    warehouse_dir: str = "warehouse"


class TrinoSettings(BaseSettings):
    """SQL warehouse used to serve the lakehouse marts (ADR 0010). Read-only ``app`` user."""

    model_config = SettingsConfigDict(env_prefix="EDU_TRINO_")
    host: str = "localhost"
    port: int = 8091
    user: str = "app"
    catalog: str = "lakehouse"
    http_scheme: str = "http"
    timeout_seconds: float = 15.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="EDU_", extra="ignore")

    env: Literal["local", "docker", "dev", "staging", "prod"] = "local"
    # demo  = in-process adapters (ADR 0008)
    # service = Kafka/Redis services own the writes; the API is a read model/BFF
    br13_mode: Literal["demo", "service"] = "demo"
    schema_registry_url: str = "http://localhost:8081"
    postgres_dsn: SecretStr = SecretStr("postgresql://lms:lms@localhost:5432/lms")
    redis_url: str = "redis://localhost:6379/0"
    grading_service_url: str = "http://localhost:8001"
    # Phase 5: the optional projector copies grading.* to public.*. Keep it off
    # by default so BR4/BR6 lakehouse baselines are untouched unless explicitly enabled.
    grading_project_to_lms: bool = False
    email_smtp_url: str | None = None
    email_from: str = "no-reply@edu.local"
    push_webhook_url: str | None = None
    corpus_bucket: str = "corpus"
    pii_hmac_secret: SecretStr = SecretStr("change-me")
    search_url: str = "http://localhost:9200"
    embedding_endpoint: str = "http://localhost:8000/embed"
    # Structured Streaming checkpoints (MinIO bucket locally); one sub-folder per app/query.
    stream_checkpoint_root: str = "s3a://checkpoints"
    stream_progress_seconds: int = 30  # how often streaming apps log their last busy batch

    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    lakehouse: LakehouseSettings = Field(default_factory=LakehouseSettings)
    spark: SparkSettings = Field(default_factory=SparkSettings)
    trino: TrinoSettings = Field(default_factory=TrinoSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
