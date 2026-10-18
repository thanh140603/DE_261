-- gold.dim_organisation (SCD1, full rebuild). Inferred members for organisations referenced by
-- enrollments / learners before their CDC row arrived; -1 = no organisation (B2C learner).
INSERT OVERWRITE gold.dim_organisation
WITH src AS (
  SELECT organisation_id, name, plan FROM silver.organisations
),
refs AS (
  SELECT organisation_id FROM silver.enrollments WHERE organisation_id IS NOT NULL
  UNION SELECT organisation_id FROM silver.learners WHERE organisation_id IS NOT NULL
)
SELECT xxhash64(organisation_id), organisation_id, name, plan, false, current_timestamp() FROM src
UNION ALL
SELECT xxhash64(r.organisation_id), r.organisation_id, NULL, NULL, true, current_timestamp()
FROM refs r LEFT ANTI JOIN src s ON s.organisation_id = r.organisation_id
UNION ALL
SELECT -1, 'n/a', 'No organisation (B2C)', NULL, false, current_timestamp();
