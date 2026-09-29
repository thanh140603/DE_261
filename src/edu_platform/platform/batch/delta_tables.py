"""Delta table helpers used by bronze/silver/gold writers.

Content (TODO):
- ``upsert(df, path, merge_keys, partition_by)``: MERGE INTO for idempotent re-runs.
- ``append_with_dedup(df, path, dedup_keys)`` for bronze appends.
- ``optimize(path, zorder_by)`` / ``vacuum(path, retention_hours)`` maintenance.
- ``time_travel(path, version | timestamp)`` for reproducible feature backfills.
- Set delta.enableChangeDataFeed=true on silver tables so gold marts consume
  changes incrementally.
"""

from __future__ import annotations

# TODO: implement helpers listed above.
