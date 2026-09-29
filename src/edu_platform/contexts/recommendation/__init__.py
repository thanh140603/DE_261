"""Recommendation context (BR2): dual-branch feature pipeline behind a Feature Store.

- Batch branch (Spark, daily): long-term learner features from silver
  (completion rate, avg pass_rate, preferred content types, skill mastery).
- Streaming branch (Flink, seconds): session features from live telemetry
  (current course, minutes active, last N verbs, struggle indicators).
- Offline store = Delta (training / backfill, point-in-time correct);
  online store = Redis (serving the recommender with < 10 ms lookups).
"""
