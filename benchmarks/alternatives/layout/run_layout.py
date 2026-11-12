"""Compare Delta Hive partitioning, partition + Z-order, and liquid clustering.

Usage (inside the Spark image):
    python /script/run_layout.py --csv /data/org-facts-5m.csv \
      --out /results/layout_5m.json --rows 5000000
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pyspark.sql import SparkSession, functions


def build_spark() -> SparkSession:
    return (
        SparkSession.builder.appName("bench-layout")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.databricks.delta.optimize.maxFileSize", "134217728")
        .config("spark.databricks.delta.optimize.minFileSize", "1048576")
        .getOrCreate()
    )


def table_detail(spark: SparkSession, path: str) -> dict[str, Any]:
    row = spark.sql(f"DESCRIBE DETAIL delta.`{path}`").collect()[0]
    return {"files": int(row["numFiles"]), "bytes": int(row["sizeInBytes"])}


def measure(spark: SparkSession, path: str, where: str) -> dict[str, Any]:
    samples: list[float] = []
    rows = 0
    files: list[str] = []
    for _ in range(3):
        df = spark.read.format("delta").load(path).filter(where)
        files = df.inputFiles()
        started = time.perf_counter()
        rows = df.agg(functions.count("*").alias("rows")).collect()[0]["rows"]
        samples.append((time.perf_counter() - started) * 1000)
    local_files = [urlparse(file).path if file.startswith("file:") else file for file in files]
    return {
        "where": where,
        "rows": rows,
        "p50_ms": round(sorted(samples)[1], 3),
        "files": len(files),
        "bytes": sum(Path(file).stat().st_size for file in local_files),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--rows", type=int, default=0)
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default="/tmp/bench-layout")
    args = parser.parse_args()

    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)
    spark = build_spark()
    source = spark.read.option("header", "true").option("inferSchema", "true").csv(args.csv)
    if args.rows:
        source = source.limit(args.rows)
    source.createOrReplaceTempView("source")
    total = source.count()
    rows = [
        ("date", "event_date = '2026-10-15'"),
        ("course", "course_id = 'c-sql-101'"),
        ("org", "org_id = 'org-acme'"),
        (
            "combined",
            "event_date = '2026-10-15' AND course_id = 'c-sql-101' AND org_id = 'org-acme'",
        ),
    ]

    results: dict[str, Any] = {"rows": total, "queries": rows, "layouts": {}}

    # 1. Hive partition
    path = str(root / "partitioned")
    started = time.perf_counter()
    source.write.format("delta").mode("overwrite").partitionBy("event_date").save(path)
    results["layouts"]["partitioned"] = {
        "write_s": round(time.perf_counter() - started, 3),
        **table_detail(spark, path),
    }
    results["layouts"]["partitioned"]["queries"] = [
        measure(spark, path, where) for _, where in rows
    ]

    # 2. Partition + Z-order
    path_z = str(root / "partitioned_zorder")
    started = time.perf_counter()
    source.write.format("delta").mode("overwrite").partitionBy("event_date").save(path_z)
    write_s = time.perf_counter() - started
    started = time.perf_counter()
    spark.sql(f"OPTIMIZE delta.`{path_z}` ZORDER BY (course_id, org_id)")
    z_s = time.perf_counter() - started
    results["layouts"]["partitioned_zorder"] = {
        "write_s": round(write_s, 3),
        "zorder_s": round(z_s, 3),
        **table_detail(spark, path_z),
    }
    results["layouts"]["partitioned_zorder"]["queries"] = [
        measure(spark, path_z, where) for _, where in rows
    ]

    # 3. Liquid clustering
    path_l = str(root / "liquid")
    started = time.perf_counter()
    spark.sql(
        "CREATE TABLE bench_layout_liquid USING DELTA "
        "CLUSTER BY (event_date, course_id, org_id) "
        f"LOCATION '{path_l}' AS SELECT * FROM source"
    )
    write_l = time.perf_counter() - started
    started = time.perf_counter()
    spark.sql(f"OPTIMIZE delta.`{path_l}`")
    optimize_l = time.perf_counter() - started
    results["layouts"]["liquid"] = {
        "write_s": round(write_l, 3),
        "optimize_s": round(optimize_l, 3),
        **table_detail(spark, path_l),
    }
    results["layouts"]["liquid"]["queries"] = [measure(spark, path_l, where) for _, where in rows]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({k: v for k, v in results.items() if k != "layouts"}, indent=2))
    for name, data in results["layouts"].items():
        print(name, data["files"], data["bytes"])
    spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
