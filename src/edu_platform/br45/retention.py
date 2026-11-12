"""Preview or prune old activity deliveries after their streaming checkpoint commits."""

from __future__ import annotations

from typing import Any

from .config import AnalyticsSettings
from .contracts import timestamp
from .db import Db, state


def activity_deliveries(
    conn: Db, cfg: AnalyticsSettings, days: int, *, apply: bool = False
) -> dict[str, Any]:
    if days < cfg.lateness_days + 7:
        raise ValueError("Retention must cover both the lateness allowance and the window")
    if cfg.mode != "persistent" or cfg.engine_benchmark:
        raise ValueError("Select the persistent runtime for retention")
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('br45-cdc-progress'))")
    watermark = state(conn, "stream_watermark")
    freshness = state(conn, "feature_freshness") or {}
    progress = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM analytics.outbox WHERE published_at IS NULL) AS pending,"
        "EXISTS(SELECT 1 FROM analytics.domain_outbox WHERE published_at IS NULL) "
        "AS domain_pending,"
        "EXISTS(SELECT 1 FROM analytics.assessment_jobs WHERE status IN ('PENDING','RUNNING')) "
        "AS jobs_pending"
    ).fetchone()
    assert progress is not None
    if (
        not watermark
        or not freshness.get("caught_up")
        or freshness.get("published_offsets") != state(conn, "published_offsets")
        or any(progress.values())
    ):
        return {"status": "BLOCKED", "deleted": 0, "pending": progress, "watermark": watermark}
    where = (
        "published_at < now() - make_interval(days => %s) "
        "AND (payload->>'event_time')::timestamptz <= %s"
    )
    params = (days, timestamp(watermark))
    if apply:
        deleted = conn.execute("DELETE FROM analytics.outbox WHERE " + where, params).rowcount
        return {"status": "APPLIED", "deleted": deleted, "watermark": watermark}
    eligible = conn.execute(
        "SELECT count(*) AS total FROM analytics.outbox WHERE " + where, params
    ).fetchone()
    assert eligible is not None
    return {"status": "PREVIEW", "eligible": eligible["total"], "watermark": watermark}
