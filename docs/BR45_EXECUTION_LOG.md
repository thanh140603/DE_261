# BR4 / BR5 execution ledger

Target: implement the accepted maximum-evidence plan on this workstation, without paid
infrastructure or deleting existing application data. Reserve at least 2 GiB free disk.

## Work packages

- [ ] Restore minimal services and isolated test environment.
- [ ] Independent source oracle; additive v2 migrations and contracts.
- [ ] Spark/Delta assessment path, async materialization, cohort analysis.
- [ ] BR5 batching, scoped policies, domain-event outbox and warehouse integration.
- [ ] Flink alternative and equivalent replay verification.
- [ ] Role-specific UI, freshness, activity timeline and intervention notes.
- [ ] OULAD effectiveness and labeled BR4 effectiveness evaluation.
- [ ] Resource-bounded comparative benchmarks and restart/CDC acceptance.
- [ ] Six-chapter Vietnamese report, traceability, charts, browser video and final audit.

## Evidence rules

New results go under `docs/evidence/br45-v2/`; old evidence stays unchanged.
Raw datasets and disposable run state stay under ignored `data/br45-v2/`.
Report actual PASS / FAIL / SKIP / RESOURCE_LIMIT, never extrapolated successes.
OULAD daily observations are evaluated at daily resolution; accelerated streaming is replay.

## Initial inspection (2026-11-01)

Only demo web/API was running; analytics returned HTTP 503. Disk available at execution
start: 8.9 GiB; RAM available: 6.1 GiB; 6 logical CPUs. Existing `dockerhelper.md` is
untracked user content and must be preserved. No applicable AGENTS.md found.

## Continuation (2026-11-02)

- Restored the stopped data services without resetting volumes. Added explicit MinIO/Hive
  readiness dependencies to the v2 Spark service after observing a missing-MinIO failure.
- Fixed OULAD missing dates (`?`), retained exclusions and temporal learner split.
  Completed evaluation of 10,655,280 VLE rows yielding 77,106 cutoff observations.
  Outputs: `docs/evidence/br45-v2/oulad_{evaluation.json,metrics.csv,predictions.csv}`.
- Held-out 2014 pooled sample: 41,839 observations, 1,492 positives. Default policy:
  precision 0.120879, recall 0.110590, F1 0.115506, average precision 0.058081.
  Calibrated threshold 85 (selected only on 2013) has lower test F1 0.102998;
  do not promote this threshold on the strength of calibration results.
- Added independent oracle boundary/retraction/dedup and tied-score metric tests.
  271 unit tests pass; mypy passes all 22 BR45 Python modules.
- Flink Java source compiles successfully against Flink 1.19.3 plus Kafka/JDBC
  connectors. Seven classes packaged locally; runtime equivalence is NOT yet verified.
- Requested a new Spark publication for the current default date window. Existing
  historical jobs were successful; the new request requires separate verification.
- Outstanding: fresh Spark/Trino/oracle parity; Flink runtime/harness and benchmarks;
  BR4 effectiveness fixtures; full v2 browser/E2E checks; report and video.

OULAD evaluation is offline effectiveness evidence, NOT a ten-million-event streaming benchmark.
