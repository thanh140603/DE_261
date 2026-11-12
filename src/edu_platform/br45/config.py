from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RiskPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inactivity_points: int = Field(default=35, ge=0, le=100)
    missed_points: int = Field(default=30, ge=0, le=100)
    completion_points: int = Field(default=20, ge=0, le=100)
    decline_points: int = Field(default=15, ge=0, le=100)
    medium_threshold: int = Field(default=30, ge=1, le=100)
    high_threshold: int = Field(default=60, ge=1, le=100)
    critical_threshold: int = Field(default=80, ge=1, le=100)
    alert_threshold: int = Field(default=60, ge=1, le=100)
    cooldown_hours: int = Field(default=72, ge=0)
    minimum_reference_events: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def thresholds_increase(self) -> RiskPolicy:
        if not self.medium_threshold < self.high_threshold < self.critical_threshold:
            raise ValueError("Risk level thresholds must increase: medium < high < critical")
        return self


class AnalyticsSettings(BaseSettings, RiskPolicy):
    model_config = SettingsConfigDict(env_prefix="EDU_BR45_", extra="ignore")

    dsn: str = "postgresql://lms:lms@localhost:5433/lms"
    kafka: str = "localhost:9092"
    topic_prefix: str = "br45.cdc.br45."
    activity_topic: str = Field(default="br45.activity.v1", pattern=r"^[A-Za-z0-9._-]+$")
    checkpoint: str = "/tmp/de261-br45-checkpoint"
    slide_seconds: int = Field(default=3600, ge=60, le=86400)
    lateness_days: int = Field(default=21, ge=14, le=60)
    min_students: int = Field(default=20, ge=1)
    question_threshold: float = Field(default=0.30, ge=0, le=1)
    case_threshold: float = Field(default=0.20, ge=0, le=1)
    peer_gap: float = Field(default=0.50, ge=0, le=1)
    drop_threshold: float = Field(default=0.30, ge=0, le=1)
    auth: str = "{}"  # JSON token -> {id, role, courses?, organisations?}; no anonymous access.
    clock_mode: Literal["wall", "manual"] = "manual"
    assessment_engine: Literal["spark", "postgres"] = "spark"
    lakehouse_root: str = "/data/br45-v2/lakehouse"
    clean_topic: str = Field(default="br45.clean.v2", pattern=r"^[A-Za-z0-9._-]+$")
    domain_topic: str = Field(default="br45.analytics.v2", pattern=r"^[A-Za-z0-9._-]+$")
    policy_version: int = Field(default=1, ge=1)
    benchmark_run: str = ""
    min_free_disk_gib: float = Field(default=2, ge=2)
    mode: Literal["persistent", "classroom", "replay"] = "persistent"
    replay: bool = False
    classroom: bool = False
    landing_group: str = "br45-landing-v1"
    cdc_identity: str = Field(default="", pattern=r"^[a-z0-9_]{0,40}$")
    engine_benchmark: bool = False
    benchmark_window_run: str = ""

    @model_validator(mode="after")
    def coherent_policy(self) -> AnalyticsSettings:
        if self.replay and self.classroom:
            raise ValueError("Classroom and replay are mutually exclusive")
        legacy_mode: Literal["replay", "classroom"] | None = None
        if self.replay:
            legacy_mode = "replay"
        if self.classroom:
            legacy_mode = "classroom"
        if legacy_mode and self.mode not in {"persistent", legacy_mode}:
            raise ValueError("BR45_MODE conflicts with legacy mode flags")
        self.mode = legacy_mode or self.mode
        self.replay = self.mode == "replay"
        self.classroom = self.mode == "classroom"
        if self.classroom and (self.clock_mode != "manual" or self.engine_benchmark):
            raise ValueError("Classroom requires a manual clock and isolated classroom inputs")
        if self.cdc_identity and (self.classroom or self.replay or self.engine_benchmark):
            raise ValueError("A custom connector identity is reserved for the persistent runtime")
        if self.replay and self.engine_benchmark:
            raise ValueError("Replay and benchmark modes are mutually exclusive")
        if len({self.activity_topic, self.clean_topic, self.domain_topic}) != 3:
            raise ValueError("Activity, clean CDC and domain topics must be distinct")
        if not self.topic_prefix.endswith(".br45."):
            raise ValueError("The Debezium topic prefix must end in .br45.")
        if not self.lakehouse_root.strip() or not self.checkpoint.strip():
            raise ValueError("A lakehouse root and checkpoint path are required")
        if 604800 % self.slide_seconds:
            raise ValueError("slide_seconds must divide a 7-day window exactly")
        return self


@lru_cache
def settings() -> AnalyticsSettings:
    return AnalyticsSettings()
