"""Compare event-id outputs from the Spark and Flink filter jobs."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable

from confluent_kafka import Consumer, KafkaError


def read(topic: str, limit: int) -> list[dict[str, object]]:
    consumer = Consumer(
        {
            "bootstrap.servers": "localhost:9092",
            "group.id": f"check-{topic}-{int(time.time())}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([topic])
    rows: list[dict[str, object]] = []
    while len(rows) < limit:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error() and msg.error().code() != KafkaError._PARTITION_EOF:
            raise RuntimeError(msg.error())
        rows.append(json.loads(msg.value()))
    consumer.close()
    return rows


def ids(rows: Iterable[dict[str, object]]) -> set[str]:
    return {str(row["event_id"]) for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=49_913)
    args = parser.parse_args()
    spark = read("bench.spark.out3", args.limit)
    flink = read("bench.flink.out3", args.limit)
    spark_ids, flink_ids = ids(spark), ids(flink)
    result = {
        "spark_rows": len(spark),
        "flink_rows": len(flink),
        "spark_unique_ids": len(spark_ids),
        "flink_unique_ids": len(flink_ids),
        "missing_in_flink": len(spark_ids - flink_ids),
        "missing_in_spark": len(flink_ids - spark_ids),
        "match": spark_ids == flink_ids,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
