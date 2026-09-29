"""NotificationStateStore adapter on Redis.

Content (TODO):
- dedup:      SET edu:notif:dedup:<key> 1 NX EX <ttl>
- rate limit: sliding window via ZADD/ZREMRANGEBYSCORE on edu:notif:rl:<learner>
- opt-out:    SISMEMBER edu:notif:optout:<learner> <channel>
"""

# TODO
