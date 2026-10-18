-- BR6 k-anonymity: no published rate for a cohort smaller than k, and every small cohort flagged.
SELECT count(*) AS violations FROM mart.org_progress
WHERE as_of_date = DATE'${run_date}'
  AND ((cohort_size < min_cohort_k AND (completion_rate IS NOT NULL OR avg_mastery IS NOT NULL
                                        OR completed_learners IS NOT NULL OR NOT is_suppressed))
    OR (cohort_size >= min_cohort_k AND is_suppressed));
