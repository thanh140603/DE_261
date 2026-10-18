"""Warehouse runner: bootstraps the lakehouse catalog and builds models from the registry.

One code path for every cadence:
- batch (Airflow / CLI): ``run(run_date, layers)`` - silver models read the bronze window,
  gold/mart/features models read silver/gold;
- streaming: ``apply_silver(spec, micro_batch_df, ctx)`` - the same silver SQL runs against
  a Structured Streaming micro-batch instead of the bronze window.

Each model execution is logged to ``ops.pipeline_runs`` (rows written, resulting Delta
version for time travel) and quality checks are logged to ``ops.dq_results``; an ``error``
check with violations stops the run.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from edu_platform.platform.logging import get_logger
from edu_platform.platform.warehouse.registry import LAYERS, ModelSpec, QualityCheck, Registry
from edu_platform.platform.warehouse.sql import render, split_statements

SOURCE_VIEW = "_src"
log = get_logger(__name__)


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_date: date
    window_start: date
    window_end: date
    params: Mapping[str, object] = field(default_factory=dict)

    def sql_params(self) -> dict[str, object]:
        return {
            **self.params,
            "run_date": self.run_date.isoformat(),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
        }


# A python model gets the session and the context; its input (silver) is the view _src.
PythonModel = Callable[[Any, RunContext], None]


@dataclass(frozen=True)
class ModelResult:
    model: str
    status: str
    rows_written: int | None
    table_version: int | None
    seconds: float
    error: str | None = None


@dataclass(frozen=True)
class CheckResult:
    check: QualityCheck
    violations: int

    @property
    def passed(self) -> bool:
        return self.violations == 0


class QualityGateFailed(RuntimeError):
    pass


class WarehouseRunner:
    def __init__(
        self,
        spark: Any,
        registry: Registry,
        warehouse_dir: Path,
        *,
        params: Mapping[str, object],
        python_models: Mapping[str, PythonModel] | None = None,
    ) -> None:
        self._spark = spark
        self._registry = registry
        self._dir = warehouse_dir
        self._params = dict(params)
        self._python_models = dict(python_models or {})

    @property
    def spark(self) -> Any:
        return self._spark

    @property
    def registry(self) -> Registry:
        return self._registry

    # --- catalog ----------------------------------------------------------------------
    def bootstrap(self) -> list[str]:
        """Create schemas and tables (idempotent: CREATE ... IF NOT EXISTS)."""
        applied: list[str] = []
        for path in sorted((self._dir / "ddl").glob("*.sql")):
            for statement in split_statements(render(path.read_text("utf-8"), self._params)):
                self._spark.sql(statement)
            applied.append(path.name)
            log.info("ddl applied", file=path.name)
        return applied

    # --- batch ------------------------------------------------------------------------
    def context(
        self, run_date: date, *, start_date: date | None = None, run_id: str | None = None
    ) -> RunContext:
        return RunContext(
            run_id=run_id or f"{run_date.isoformat()}-{uuid.uuid4().hex[:8]}",
            run_date=run_date,
            window_start=start_date or run_date,
            window_end=run_date,
            params=self._params,
        )

    def run(
        self,
        run_date: date,
        *,
        layers: Iterable[str] | None = None,
        select: Iterable[str] | None = None,
        start_date: date | None = None,
        skip_quality: bool = False,
    ) -> list[ModelResult]:
        """Build the selected models for run_date; window = [start_date or lookback, run_date]."""
        base = self.context(run_date, start_date=start_date)
        models = self._registry.select(layers, select)
        results: list[ModelResult] = []
        for layer in LAYERS:
            layer_models = [m for m in models if m.layer == layer]
            if not layer_models:
                continue
            for spec in layer_models:
                result = self.run_model(spec, self._windowed(base, spec, start_date))
                results.append(result)
                if result.status != "success":
                    raise RuntimeError(f"{spec.name} failed: {result.error}")
            if not skip_quality:
                self.check_quality(base, layer_models)
        return results

    def run_model(self, spec: ModelSpec, ctx: RunContext) -> ModelResult:
        started = datetime.now(tz=UTC)
        t0 = time.monotonic()
        try:
            if spec.layer == "silver":
                self._register_bronze_window(spec, ctx)
            before = self._version(spec.name)
            self._execute(spec, ctx)
            rows, version = self._commits_since(spec.name, before)
            result = ModelResult(spec.name, "success", rows, version, time.monotonic() - t0)
        except Exception as exc:  # recorded in ops.pipeline_runs, then re-raised by run()
            log.error("model failed", model=spec.name, error=str(exc)[:500])
            result = ModelResult(spec.name, "failed", None, None, time.monotonic() - t0, str(exc))
        self._record_run(spec, ctx, result, started)
        log.info(
            "model built",
            model=spec.name,
            status=result.status,
            rows=result.rows_written,
            version=result.table_version,
            seconds=round(result.seconds, 1),
            window=f"{ctx.window_start}..{ctx.window_end}",
        )
        return result

    # --- streaming --------------------------------------------------------------------
    def apply_silver(self, spec: ModelSpec, micro_batch: Any, ctx: RunContext) -> None:
        """Run a silver model on a Structured Streaming micro-batch (foreachBatch).

        foreachBatch hands each micro-batch a cloned session: the view and the SQL must both
        live in that session, not in the one the runner was built with.
        """
        frame = micro_batch.where(spec.source_filter) if spec.source_filter else micro_batch
        frame.createOrReplaceTempView(SOURCE_VIEW)
        self._execute(spec, ctx, micro_batch.sparkSession)

    # --- quality ----------------------------------------------------------------------
    def check_quality(self, ctx: RunContext, models: Iterable[ModelSpec]) -> list[CheckResult]:
        results: list[CheckResult] = []
        for check in self._registry.checks_for(models):
            spec = self._registry.get(check.model)
            check_ctx = replace(
                ctx, window_start=ctx.run_date - timedelta(days=self._registry.lookback(spec))
            )
            sql = render(
                (self._dir / "quality" / check.sql).read_text("utf-8"), check_ctx.sql_params()
            )
            row = self._spark.sql(split_statements(sql)[0]).collect()[0]
            result = CheckResult(check, int(row["violations"] or 0))
            results.append(result)
            self._record_check(ctx, result)
            log.info(
                "quality check",
                check=check.name,
                severity=check.severity,
                violations=result.violations,
            )
        failed = [r for r in results if not r.passed and r.check.severity == "error"]
        if failed:
            names = ", ".join(f"{r.check.name}={r.violations}" for r in failed)
            raise QualityGateFailed(f"quality gate failed: {names}")
        return results

    # --- internals --------------------------------------------------------------------
    def _windowed(self, ctx: RunContext, spec: ModelSpec, start_date: date | None) -> RunContext:
        """window_start = explicit start or run_date - lookback, pulled back for late data."""
        start = start_date or ctx.run_date - timedelta(days=self._registry.lookback(spec))
        late = self._late_data_start(spec)
        if late is not None and late < start:
            log.info("window extended for late data", model=spec.name, start=str(late))
            start = late
        return replace(ctx, window_start=start)

    def _late_data_start(self, spec: ModelSpec) -> date | None:
        """Oldest driver date of silver rows processed since the last successful build began."""
        if not spec.late_data_table:
            return None
        last = self._spark.sql(
            "SELECT max(started_at) AS t FROM ops.pipeline_runs "
            f"WHERE model = '{spec.name}' AND status = 'success'"
        ).collect()[0]["t"]
        if last is None:
            return None
        row = self._spark.sql(
            f"SELECT min({spec.late_data_date}) AS d FROM {spec.late_data_table} "
            f"WHERE _processed_at > TIMESTAMP'{last.isoformat(sep=' ')}'"
        ).collect()[0]
        found: date | None = row["d"]
        return found

    def _register_bronze_window(self, spec: ModelSpec, ctx: RunContext) -> None:
        predicate = (
            f"ingest_date BETWEEN DATE'{ctx.window_start.isoformat()}' "
            f"AND DATE'{ctx.window_end.isoformat()}'"
        )
        if spec.source_filter:
            predicate += f" AND ({spec.source_filter})"
        self._spark.sql(
            f"CREATE OR REPLACE TEMPORARY VIEW {SOURCE_VIEW} AS "
            f"SELECT * FROM {spec.source} WHERE {predicate}"
        )

    def _execute(self, spec: ModelSpec, ctx: RunContext, session: Any = None) -> None:
        spark = session or self._spark
        if spec.kind == "python":
            model = self._python_models.get(spec.name)
            if model is None:
                raise KeyError(f"python model {spec.name} is not registered by the entrypoint")
            model(spark, ctx)
            return
        assert spec.sql is not None
        sql = render((self._dir / "transform" / spec.sql).read_text("utf-8"), ctx.sql_params())
        for statement in split_statements(sql):
            spark.sql(statement)

    def _version(self, table: str) -> int:
        return int(self._spark.sql(f"DESCRIBE HISTORY {table} LIMIT 1").collect()[0]["version"])

    def _commits_since(self, table: str, version: int) -> tuple[int, int]:
        """Rows written by the commits after ``version`` and the table's new version."""
        history = self._spark.sql(f"DESCRIBE HISTORY {table}").where(f"version > {version}")
        written = 0
        latest = version
        for row in history.collect():
            metrics: dict[str, str] = row["operationMetrics"] or {}
            latest = max(latest, int(row["version"]))
            if row["operation"] == "MERGE":
                written += sum(
                    int(metrics.get(k, 0))
                    for k in (
                        "numTargetRowsInserted",
                        "numTargetRowsUpdated",
                        "numTargetRowsDeleted",
                    )
                )
            else:
                written += int(metrics.get("numOutputRows", 0))
        return written, latest

    def _record_run(
        self, spec: ModelSpec, ctx: RunContext, result: ModelResult, started: datetime
    ) -> None:
        row = (
            ctx.run_id,
            spec.name,
            spec.layer,
            ctx.run_date,
            spec.strategy,
            ctx.window_start,
            ctx.window_end,
            result.status,
            result.rows_written,
            result.table_version,
            started.replace(tzinfo=None),
            datetime.now(tz=UTC).replace(tzinfo=None),
            (result.error or "")[:2000] or None,
        )
        self._spark.createDataFrame(
            [row], self._spark.table("ops.pipeline_runs").schema
        ).write.format("delta").mode("append").saveAsTable("ops.pipeline_runs")

    def _record_check(self, ctx: RunContext, result: CheckResult) -> None:
        row = (
            ctx.run_id,
            result.check.name,
            result.check.model,
            result.check.severity,
            result.violations,
            result.passed,
            ctx.run_date,
            datetime.now(tz=UTC).replace(tzinfo=None),
        )
        self._spark.createDataFrame([row], self._spark.table("ops.dq_results").schema).write.format(
            "delta"
        ).mode("append").saveAsTable("ops.dq_results")
