"""Risk context (BR5): early warning for learners at risk of dropping out.

CDC & Stream Windowing: Debezium row-level changes (lesson_progress,
submissions, grades, enrollments) are joined with silver telemetry in a Flink
job; a sliding-window risk score is computed per learner and, when it crosses
the policy threshold, a ``DropoutRiskDetected`` alert is published for advisors.
"""
