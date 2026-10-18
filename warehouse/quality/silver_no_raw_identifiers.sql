-- PII boundary (ADR 0007): every learner reference past bronze is an HMAC pseudonym
-- (k<key version>_<24 hex>), never a raw LMS id.
SELECT sum(n) AS violations FROM (
  SELECT count(*) AS n FROM silver.learners WHERE NOT learner_pseudonym RLIKE '^k[0-9]+_[0-9a-f]{24}$'
  UNION ALL SELECT count(*) FROM silver.enrollments WHERE NOT learner_pseudonym RLIKE '^k[0-9]+_[0-9a-f]{24}$'
  UNION ALL SELECT count(*) FROM silver.submissions WHERE NOT learner_pseudonym RLIKE '^k[0-9]+_[0-9a-f]{24}$'
  UNION ALL SELECT count(*) FROM silver.learning_events
            WHERE event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
              AND NOT learner_pseudonym RLIKE '^k[0-9]+_[0-9a-f]{24}$'
);
