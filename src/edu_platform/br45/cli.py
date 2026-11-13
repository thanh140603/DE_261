from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import UTC, datetime, timedelta

from .config import settings
from .contracts import timestamp
from .db import ROOT, connect, migrate, state


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent BR4/BR5 tools; fixtures are SYNTHETIC")
    parser.add_argument(
        "command",
        choices=[
            "migrate",
            "seed",
            "clock",
            "recover",
            "reset-demo",
            "br4",
            "cdc",
            "stream",
            "register",
            "benchmark",
            "backfill",
            "retention",
            "diagnostics",
        ],
    )
    parser.add_argument(
        "--at", type=timestamp, default=None, help="Timezone-aware evaluation timestamp"
    )
    parser.add_argument("--students", type=int, default=24)
    parser.add_argument("--connect-url", default="http://localhost:8083")
    parser.add_argument("--output", default="docs/evidence/br45")
    parser.add_argument("--target-dsn", help="Empty br45_rebuild_<run> database for backfill")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--apply", action="store_true", help="Apply a retention preview")
    args = parser.parse_args()
    if args.command == "retention":
        from .retention import activity_deliveries

        with connect() as conn:
            print(json.dumps(activity_deliveries(conn, settings(), args.days, apply=args.apply)))
        return
    if args.command == "diagnostics":
        cfg = settings()
        name = "br45-postgres-cdc"
        if cfg.cdc_identity:
            name = "br45-" + cfg.cdc_identity.replace("_", "-")
        if cfg.classroom:
            name = "br45-classroom-cdc"
        if cfg.engine_benchmark:
            name = "br45-engine-benchmark"
        with urllib.request.urlopen(
            f"{args.connect_url}/connectors/{name}/status", timeout=10
        ) as response:
            print(json.dumps(json.load(response), indent=2))
        return
    if args.command == "backfill":
        from .backfill import stage

        if not args.target_dsn:
            parser.error("backfill requires --target-dsn")
        print(json.dumps(stage(settings().dsn, args.target_dsn), indent=2))
        return
    if args.command == "migrate":
        migrate()
        print("Applied BR4/BR5 migrations")
        return
    if args.command == "register":
        from confluent_kafka import KafkaError, KafkaException
        from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]

        from .contracts import CONTRACTS

        cfg = settings()
        admin = AdminClient({"bootstrap.servers": cfg.kafka})
        names = [cfg.topic_prefix + t for t in CONTRACTS] + [
            cfg.activity_topic,
            cfg.clean_topic,
            cfg.domain_topic,
        ]
        if not (cfg.classroom or cfg.engine_benchmark):
            names.extend(
                ("risk.learner_score.v1", "risk.dropout_alert.v1", "risk.alert_transition.v1")
            )
        for future in admin.create_topics(
            [NewTopic(t, num_partitions=1, replication_factor=1) for t in names]
        ).values():
            try:
                future.result(timeout=30)
            except KafkaException as exc:
                if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                    raise
        spec = json.loads((ROOT / "infra/debezium/br45-connector.json").read_text())
        # Local defaults in checked-in connector; environment overrides deployment credentials.
        from urllib.parse import urlparse

        dsn = urlparse(settings().dsn)
        spec["config"].update(
            {
                "database.user": dsn.username,
                "database.password": dsn.password,
                "database.dbname": dsn.path.lstrip("/"),
            }
        )
        spec["config"]["topic.prefix"] = cfg.topic_prefix.removesuffix(".br45.")
        if cfg.cdc_identity:
            spec["name"] = "br45-" + cfg.cdc_identity.replace("_", "-")
            spec["config"].update(
                {
                    "database.hostname": dsn.hostname,
                    "database.port": str(dsn.port or 5432),
                    "slot.name": "br45_" + cfg.cdc_identity + "_slot",
                    "publication.name": "br45_" + cfg.cdc_identity + "_pub",
                }
            )
        if cfg.classroom:
            spec["name"] = "br45-classroom-cdc"
            spec["config"].update(
                {
                    "slot.name": "br45_classroom_slot",
                    "publication.name": "br45_classroom_pub",
                    "topic.prefix": cfg.topic_prefix.removesuffix(".br45."),
                }
            )
        if cfg.engine_benchmark:
            if dsn.path != "/br45_bench" or dsn.hostname != "br45-bench-postgres":
                parser.error("Benchmark CDC registration requires the isolated br45_bench service")
            spec["name"] = "br45-engine-benchmark"
            spec["config"].update(
                {
                    "database.hostname": dsn.hostname,
                    "database.port": str(dsn.port or 5432),
                    "slot.name": "br45_engine_bench_slot",
                    "publication.name": "br45_engine_bench_pub",
                    "topic.prefix": cfg.topic_prefix.removesuffix(".br45."),
                }
            )
        request = urllib.request.Request(
            args.connect_url + "/connectors/" + spec["name"] + "/config",
            data=json.dumps(spec["config"]).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            print(json.dumps({"connector": spec["name"], "status": response.status}))
        return
    if args.command in {"cdc", "stream"}:
        if args.command == "cdc":
            from .cdc import run
            from .lakehouse import bootstrap

            if settings().assessment_engine == "spark":
                bootstrap()
        else:
            from .streaming import run
        run()
        return
    if args.command == "benchmark":
        from .benchmark import run as benchmark

        benchmark(args.output)
        return
    with connect() as conn:
        at = args.at or (
            timestamp(state(conn, "evaluation_clock"))
            if state(conn, "evaluation_clock")
            else datetime.now(UTC)
        )
        at = datetime.fromtimestamp(
            int(at.timestamp()) // settings().slide_seconds * settings().slide_seconds, UTC
        )
        if args.command == "seed":
            from .fixtures import seed

            if not 2 <= args.students <= 100000:
                parser.error("--students must be between 2 and 100000")
            print(json.dumps(seed(conn, at, args.students), indent=2))
        elif args.command == "recover":
            from .fixtures import recover

            recover(conn, at)
            print("Wrote SYNTHETIC recovery activity into PostgreSQL; await CDC/Spark")
        elif args.command == "clock":
            from .fixtures import PREFIX, upsert

            if args.at is None:
                parser.error("clock requires --at; choose a monotonic evaluation timestamp")
            upsert(conn, "clocks", {"id": PREFIX + "clock", "evaluated_at": at})
            print("Wrote evaluation clock to PostgreSQL: " + at.isoformat())
        elif args.command == "reset-demo":
            from .fixtures import reset

            reset(conn)
            print("Deleted only br45-demo-* source rows; audit records are retained")
        elif args.command == "br4":
            from .assessment import refresh

            q, t = refresh(conn, at - timedelta(days=30), at)
            print(json.dumps({"questions": q, "test_cases": t}, indent=2, default=str))


if __name__ == "__main__":
    main()
