# Integration tests (TODO)

Run against `docker compose up -d` (or testcontainers). Mark with `@pytest.mark.integration`.

Planned:
- kafka_publisher_roundtrip: KafkaEventPublisher -> KafkaConsumerLoop, headers + key.
- debezium_cdc_flow: insert into postgres.lesson_progress -> record on cdc.lms.public.lesson_progress.
- redis_notification_state: dedup NX semantics, sliding-window rate limit.
- delta_silver_upsert: NormalizeEvents twice on same partition is idempotent.
- flink_dropout_risk_minicluster: PyFlink MiniCluster, synthetic CDC stream -> alert emitted once.
