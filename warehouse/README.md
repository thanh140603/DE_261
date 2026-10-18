# Lakehouse warehouse as code

Everything that defines the data warehouse lives here; `src/edu_platform/platform/warehouse`
only executes it. Design: [docs/architecture/data-warehouse.md](../docs/architecture/data-warehouse.md).

```
ddl/            CREATE SCHEMA / CREATE TABLE (Delta, Spark SQL), applied in file order by
                `edu warehouse bootstrap`; idempotent (IF NOT EXISTS)
transform/      one SQL file per model, by layer: silver/ gold/ mart/ features/
quality/        one query per gate, returning a single `violations` count
models.yaml     registry: build order, load strategy, sources, late-data drivers, gates
```

## Conventions

- **One model = one target table**, named in the first line of its first statement.
- **Every model is idempotent** for a run date: silver MERGEs on business keys, gold/marts
  use `INSERT OVERWRITE` (full), `INSERT INTO ... REPLACE WHERE <window>` (window/snapshot)
  or an SCD2 MERGE. Rerunning never duplicates.
- **Parameters** are `${name}` (only the braced form; `'$.json.path'` is left alone):
  `${run_date}`, `${window_start}`, `${window_end}`, `${lakehouse_root}` and the policy
  parameters from `entrypoints/batch/warehouse_job.py::policy_params` (taken from the domain
  value objects - never hard-code a business threshold in SQL).
- **Silver models read the view `_src`**: the bronze window (batch) or the micro-batch (stream).
- **Gold reads silver/gold, marts read gold.** Nothing past bronze sees a raw identifier;
  use the `pseudonymize()` SQL function when parsing a new source.
- Policies are table properties: `edu.retention_days` (bronze), `edu.zorder`, `edu.pii`, `edu.owner`.

## Adding a model

1. `CREATE TABLE IF NOT EXISTS` in the right `ddl/` file (grain in the COMMENT).
2. `transform/<layer>/<table>.sql`.
3. Register it in `models.yaml` (strategy; `late_data` driver if it is a dated window fact).
4. Optional gate in `quality/` + `models.yaml`.
5. `pytest tests/unit/warehouse` renders every SQL file with the real parameters and checks
   the registry against the DDL.

```bash
edu warehouse run --run-date 2026-10-17 --select gold.fct_submission           # one model
edu warehouse run --run-date 2026-10-17 --layer gold --start-date 2026-09-01   # backfill a range
```
