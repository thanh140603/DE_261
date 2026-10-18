"""Warehouse model registry (warehouse/models.yaml) as typed, immutable specs.

Pure: no Spark import, so the registry and its invariants are unit-tested without an engine.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

Layer = Literal["silver", "gold", "mart", "features"]
LAYERS: tuple[Layer, ...] = ("silver", "gold", "mart", "features")
STRATEGIES = frozenset({"incremental", "full", "scd2", "window", "snapshot"})


@dataclass(frozen=True)
class ModelSpec:
    name: str  # target table, schema-qualified
    layer: Layer
    kind: Literal["sql", "python"]
    strategy: str
    sql: str | None = None  # path relative to warehouse/transform
    source: str | None = None  # silver: bronze table exposed as view _src
    source_filter: str | None = None
    lookback_days: int | None = None
    # Late data: silver table + date expression whose rows processed since this model's last
    # successful run pull window_start back (e.g. a mobile event synced 5 days late).
    late_data_table: str | None = None
    late_data_date: str | None = None
    requirements: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class QualityCheck:
    name: str
    model: str
    severity: Literal["error", "warn"]
    sql: str  # path relative to warehouse/quality


@dataclass(frozen=True)
class Registry:
    models: tuple[ModelSpec, ...]
    checks: tuple[QualityCheck, ...]
    default_lookback_days: int

    def get(self, name: str) -> ModelSpec:
        for m in self.models:
            if m.name == name:
                return m
        raise KeyError(f"unknown model {name!r}")

    def select(
        self, layers: Iterable[str] | None = None, names: Iterable[str] | None = None
    ) -> list[ModelSpec]:
        """Models in registry order, filtered by layer and/or exact name."""
        wanted_layers = set(layers or LAYERS)
        wanted_names = set(names or ())
        unknown = wanted_names - {m.name for m in self.models}
        if unknown:
            raise KeyError(f"unknown model(s): {sorted(unknown)}")
        return [
            m
            for m in self.models
            if m.layer in wanted_layers and (not wanted_names or m.name in wanted_names)
        ]

    def checks_for(self, models: Iterable[ModelSpec]) -> list[QualityCheck]:
        names = {m.name for m in models}
        return [c for c in self.checks if c.model in names]

    def lookback(self, model: ModelSpec) -> int:
        return (
            model.lookback_days if model.lookback_days is not None else self.default_lookback_days
        )


def load_registry(path: Path) -> Registry:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    models: list[ModelSpec] = []
    for layer in LAYERS:
        for entry in raw.get("layers", {}).get(layer, []) or []:
            models.append(_model(layer, entry))
    checks = tuple(
        QualityCheck(
            name=c["name"], model=c["model"], severity=c.get("severity", "error"), sql=c["sql"]
        )
        for c in raw.get("quality", []) or []
    )
    registry = Registry(
        models=tuple(models),
        checks=checks,
        default_lookback_days=int(raw.get("defaults", {}).get("lookback_days", 3)),
    )
    _validate(registry)
    return registry


def _model(layer: Layer, entry: dict[str, Any]) -> ModelSpec:
    late = entry.get("late_data") or {}
    return ModelSpec(
        name=entry["name"],
        layer=layer,
        kind=entry.get("kind", "sql"),
        strategy=entry["strategy"],
        sql=entry.get("sql"),
        source=entry.get("source"),
        source_filter=entry.get("source_filter"),
        lookback_days=entry.get("lookback_days"),
        late_data_table=late.get("table"),
        late_data_date=late.get("date"),
        requirements=tuple(entry.get("requirements", ())),
        description=entry.get("description", ""),
    )


def _validate(registry: Registry) -> None:
    seen: set[str] = set()
    for m in registry.models:
        if m.name in seen:
            raise ValueError(f"duplicate model {m.name}")
        seen.add(m.name)
        if not m.name.startswith(f"{m.layer}."):
            raise ValueError(f"{m.name} is declared in layer {m.layer}")
        if m.strategy not in STRATEGIES:
            raise ValueError(f"{m.name}: unknown strategy {m.strategy}")
        if m.kind == "sql" and not m.sql:
            raise ValueError(f"{m.name}: sql model without a sql file")
        if m.layer == "silver" and not m.source:
            raise ValueError(f"{m.name}: silver models read a bronze source")
        if bool(m.late_data_table) != bool(m.late_data_date):
            raise ValueError(f"{m.name}: late_data needs both table and date")
    for c in registry.checks:
        if c.model not in seen:
            raise ValueError(f"check {c.name} references unknown model {c.model}")
