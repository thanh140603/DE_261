"""Grading context (BR3 feedback, feeds BR4 assessment mart).

Decoupled Grading Ingestion: submissions are buffered on a queue so sandbox
load spikes never block the LMS; sandbox execution output (stdout, stderr,
runtime, memory, per-test assertions) is normalised into a structured
``ExecutionResult`` and turned into learner-facing feedback.
"""
