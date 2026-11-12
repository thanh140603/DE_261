"""Spark Structured Streaming filter used by the alternative benchmark."""

from __future__ import annotations

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
)

SCHEMA = StructType(
    [
        StructField("event_id", StringType()),
        StructField("learner_pseudonym", StringType()),
        StructField("course_id", StringType()),
        StructField("event_type", StringType()),
        StructField("verb", StringType()),
        StructField("occurred_at", StringType()),
        StructField("session_id", StringType()),
        StructField("platform", StringType()),
        StructField("duration_ms", IntegerType()),
        StructField("score", DoubleType()),
        StructField("progress", DoubleType()),
        StructField("ingest_time", LongType()),
    ]
)

spark = SparkSession.builder.appName("bench-spark-filter").getOrCreate()
spark.sparkContext.setLogLevel("WARN")
raw = (
    spark.readStream.format("kafka")
    .option("kafka.bootstrap.servers", "kafka:29092")
    .option("subscribe", "bench.events3")
    .option("startingOffsets", "earliest")
    .load()
)
parsed = (
    raw.select(F.from_json(F.col("value").cast("string"), SCHEMA).alias("v"))
    .select("v.*")
    .filter(F.col("score") > 0.5)
    .select("event_id", "learner_pseudonym", "score", "ingest_time")
)
payload = parsed.select(
    F.to_json(F.struct("event_id", "learner_pseudonym", "score", "ingest_time")).alias("value")
)
query = (
    payload.writeStream.format("kafka")
    .option("kafka.bootstrap.servers", "kafka:29092")
    .option("topic", "bench.spark.out3")
    .option("checkpointLocation", "/tmp/spark-bench-checkpoint")
    .outputMode("append")
    .trigger(processingTime="1 second")
    .start()
)
query.awaitTermination()
