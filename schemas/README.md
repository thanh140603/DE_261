# Data contracts

Versioned schemas for every message and table that crosses a context boundary.
Rules:
- A schema folder is `<domain>/v<major>/`. Breaking change = new major folder,
  new topic suffix (`.v2`), dual-write period, then retire.
- Non-breaking additions bump the `schema_version` minor inside the payload and
  must have a migration step in `contexts/telemetry/infrastructure/schema_migrations.py`.
- CI validates every JSON schema and checks BACKWARD compatibility against the
  registry (TODO: scripts/check_schema_compat.py).
