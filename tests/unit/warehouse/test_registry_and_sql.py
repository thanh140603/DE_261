"""The warehouse registry, its SQL files and the DDL must agree (no Spark needed)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from edu_platform.entrypoints.batch.warehouse_job import policy_params
from edu_platform.platform.warehouse.registry import (
    LAYERS,
    ModelSpec,
    Registry,
    _validate,
    load_registry,
)
from edu_platform.platform.warehouse.sql import render, split_statements

WAREHOUSE = Path(__file__).resolve().parents[3] / "warehouse"
REGISTRY = load_registry(WAREHOUSE / "models.yaml")
PARAMS = {
    "lakehouse_root": "s3a://lakehouse",
    "run_date": "2026-10-17",
    "window_start": "2026-10-14",
    "window_end": "2026-10-17",
    **policy_params(),
}
CREATED = {
    m.group(1)
    for path in (WAREHOUSE / "ddl").glob("*.sql")
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+\.\w+)", path.read_text())
}


def test_every_model_targets_a_table_created_by_the_ddl() -> None:
    missing = {m.name for m in REGISTRY.models} - CREATED
    assert not missing


def test_every_layer_has_models_and_silver_reads_bronze() -> None:
    assert {m.layer for m in REGISTRY.models} == set(LAYERS)
    for m in REGISTRY.select(["silver"]):
        assert m.source in CREATED and m.source.startswith("bronze.")


def test_late_data_drivers_are_silver_tables() -> None:
    for m in REGISTRY.models:
        if m.late_data_table:
            assert m.late_data_table in CREATED and m.late_data_table.startswith("silver.")


@pytest.mark.parametrize(
    "model", [m for m in REGISTRY.models if m.kind == "sql"], ids=lambda m: m.name
)
def test_sql_model_renders_and_writes_its_target(model: ModelSpec) -> None:
    sql = render((WAREHOUSE / "transform" / str(model.sql)).read_text(), PARAMS)
    statements = split_statements(sql)
    assert statements, model.name
    assert any(model.name in s.split("\n", 1)[0] for s in statements), "first line names target"
    if model.layer == "silver":
        assert "FROM _src" in sql, "silver models read the bronze window / micro-batch view"
    if model.strategy == "window":
        assert "REPLACE WHERE" in sql and "${" not in sql


def test_quality_checks_render_to_one_violations_query() -> None:
    for check in REGISTRY.checks:
        statements = split_statements(
            render((WAREHOUSE / "quality" / check.sql).read_text(), PARAMS)
        )
        assert len(statements) == 1 and "violations" in statements[0], check.name


def test_ddl_files_split_into_create_statements() -> None:
    for path in sorted((WAREHOUSE / "ddl").glob("*.sql")):
        for statement in split_statements(render(path.read_text(), PARAMS)):
            assert statement.startswith("CREATE "), (path.name, statement[:60])


def test_render_is_strict_but_ignores_json_paths() -> None:
    assert (
        render("get_json_object(v, '$.id') = '${x}'", {"x": 1})
        == "get_json_object(v, '$.id') = '1'"
    )
    with pytest.raises(KeyError, match="missing"):
        render("${missing}", {})


def test_split_drops_comment_lines() -> None:
    sql = "-- header; not a statement\nSELECT 1;\n  -- note\nSELECT 2;\n"
    assert split_statements(sql) == ["SELECT 1", "SELECT 2"]


def test_select_filters_and_rejects_unknown_names() -> None:
    gold = REGISTRY.select(["gold"])
    assert gold and all(m.layer == "gold" for m in gold)
    assert [m.name for m in REGISTRY.select(names=["mart.org_progress"])] == ["mart.org_progress"]
    with pytest.raises(KeyError):
        REGISTRY.select(names=["gold.nope"])


@pytest.mark.parametrize(
    ("spec", "error"),
    [
        (ModelSpec("gold.x", "silver", "sql", "incremental", sql="a.sql", source="b.t"), "layer"),
        (ModelSpec("gold.x", "gold", "sql", "sometimes", sql="a.sql"), "strategy"),
        (ModelSpec("gold.x", "gold", "sql", "full"), "sql file"),
        (ModelSpec("silver.x", "silver", "sql", "incremental", sql="a.sql"), "bronze source"),
    ],
)
def test_invalid_registry_is_rejected(spec: ModelSpec, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        _validate(Registry(models=(spec,), checks=(), default_lookback_days=3))
