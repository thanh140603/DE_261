"""OnlineFeatureStore adapter on Redis (key edu:features:<group>:<learner_id>, HSET + EXPIRE).

Content (TODO): pipeline writes; JSON-encode list features; TTL from
  FeatureDefinition.freshness_sla.
"""

# TODO
