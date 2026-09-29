"""Notification context (BR1): event-driven learner notifications.

LMS domain events (assignment_created, deadline_approaching, course_updated,
plus submission_graded from grading and dropout alerts from risk) arrive on
Kafka; a rule engine decides audience + channel; Redis provides deduplication
and per-learner rate limiting; channel senders deliver push / in-app / email.
"""
