"""Delta Lake sinks for bronze / silver / DLQ telemetry tables.

Content (TODO):
- DeltaBronzeSink.append: bronze.telemetry_raw partitioned by ingest_date, ingest_hour.
- DeltaSilverSink.upsert: silver.learning_events, MERGE on event_id,
  partitioned by event_date; enable Change Data Feed.
- DeltaDeadLetterSink.reject: bronze.telemetry_dlq with reason + raw payload.
- JSON-schema EventValidator using /schemas/telemetry/v1/learning_event.schema.json.
"""

from __future__ import annotations

# TODO: implement adapters listed above (uses platform.batch.delta_tables).
