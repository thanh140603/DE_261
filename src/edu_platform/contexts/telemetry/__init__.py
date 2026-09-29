"""Telemetry context - the medallion entry point for clickstream / xAPI events (BR6, BR7 base).

Responsibilities
- Accept high-velocity, late and out-of-order JSON events from web/Android/iOS.
- Land raw events untouched (bronze), then validate, migrate schema versions,
  pseudonymise PII and deduplicate into silver.
- Publish the silver ``learning_events`` table as the contract every other
  context reads from.
"""
