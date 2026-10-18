-- SCD2 integrity: exactly one current version per learner and no overlapping validity ranges.
SELECT (
  SELECT count(*) FROM (
    SELECT learner_pseudonym FROM gold.dim_learner GROUP BY learner_pseudonym HAVING count_if(is_current) <> 1)
) + (
  SELECT count(*) FROM gold.dim_learner a JOIN gold.dim_learner b
    ON a.learner_pseudonym = b.learner_pseudonym AND a.learner_key < b.learner_key
   AND a.valid_from < b.valid_to AND b.valid_from < a.valid_to
) AS violations;
