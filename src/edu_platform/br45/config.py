from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalyticsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDU_BR45_", extra="ignore")

    dsn: str = "postgresql://lms:lms@localhost:5433/lms"
    kafka: str = "localhost:9092"
    topic_prefix: str = "br45.cdc.br45."
    activity_topic: str = "br45.activity.v1"
    checkpoint: str = "/tmp/de261-br45-checkpoint"
    slide_seconds: int = Field(default=3600, ge=60, le=86400)
    lateness_days: int = Field(default=21, ge=14, le=60)
    min_students: int = Field(default=20, ge=1)
    question_threshold: float = Field(default=0.30, ge=0, le=1)
    case_threshold: float = Field(default=0.20, ge=0, le=1)
    peer_gap: float = Field(default=0.50, ge=0, le=1)
    drop_threshold: float = Field(default=0.30, ge=0, le=1)
    inactivity_points: int = Field(default=35, ge=0, le=100)
    missed_points: int = Field(default=30, ge=0, le=100)
    completion_points: int = Field(default=20, ge=0, le=100)
    decline_points: int = Field(default=15, ge=0, le=100)
    medium_threshold: int = Field(default=30, ge=1, le=100)
    high_threshold: int = Field(default=60, ge=1, le=100)
    critical_threshold: int = Field(default=80, ge=1, le=100)
    alert_threshold: int = Field(default=60, ge=1, le=100)
    cooldown_hours: int = Field(default=72, ge=0)
    auth: str = "{}"  # JSON token -> {id, role, courses}; no implicit anonymous access.
    clock_mode: Literal["wall", "manual"] = "manual"

    @model_validator(mode="after")
    def coherent_policy(self) -> AnalyticsSettings:
        if 604800 % self.slide_seconds:
            raise ValueError("slide_seconds must divide a 7-day window exactly")
        if not self.medium_threshold < self.high_threshold < self.critical_threshold:
            raise ValueError("Risk level thresholds must increase: medium < high < critical")
        return self


@lru_cache
def settings() -> AnalyticsSettings:
    return AnalyticsSettings()
