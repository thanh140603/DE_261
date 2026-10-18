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
    # Shared lakehouse catalog (ADR 0009). None = Spark's embedded catalog (unit/local runs).
    hive_metastore_uri: str | None = None
    # Folder with ddl/, transform/, quality/ and models.yaml (repo `warehouse/`).
    warehouse_dir: str = "warehouse"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="EDU_", extra="ignore")

    env: Literal["local", "docker", "dev", "staging", "prod"] = "local"
    schema_registry_url: str = "http://localhost:8081"
    postgres_dsn: SecretStr = SecretStr("postgresql://lms:lms@localhost:5432/lms")
    redis_url: str = "redis://localhost:6379/0"
    corpus_bucket: str = "corpus"
    pii_hmac_secret: SecretStr = SecretStr("change-me")
    search_url: str = "http://localhost:9200"
    embedding_endpoint: str = "http://localhost:8000/embed"

    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    lakehouse: LakehouseSettings = Field(default_factory=LakehouseSettings)
    spark: SparkSettings = Field(default_factory=SparkSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
