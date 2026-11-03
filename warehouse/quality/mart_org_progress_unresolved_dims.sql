-- BR6 rows whose organisation or course did not resolve to a real (non-inferred) dimension
-- member: the report shows ids instead of names and lesson_count = 0 turns completion into 0 %.
-- Expected 0; non-zero usually means the run window missed the reference CDC rows
-- (backfill with an earlier --start-date) or the CDC connector is not capturing them.
SELECT count(*) AS violations FROM mart.org_progress
WHERE as_of_date = DATE'${run_date}' AND (organisation_name IS NULL OR course_title IS NULL);
