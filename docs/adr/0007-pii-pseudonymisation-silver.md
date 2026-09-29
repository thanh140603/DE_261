# ADR 0007: PII pseudonymisation at the silver boundary

Status: accepted - 2026-09-29

## Context
BR6 requires de-identified organisational reporting; regulations require minimising raw identifiers in analytics.

## Decision
Raw identifiers exist only in bronze (restricted ACL, short retention). Silver and gold carry HMAC-SHA256 pseudonyms with a versioned key; PiiPolicy lists dropped/hashed fields; org reports apply a min-cohort (k=5) suppression.

## Consequences
Joins back to real identities require the key service (notification context) - intentional. Key rotation needs a re-pseudonymisation backfill procedure (TODO runbook).
