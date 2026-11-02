-- BR7 videos in the heatmap without a content version (inferred dim_content member): no
-- course, title or duration, so the video is unreachable from the instructor API.
-- Expected 0; see mart_org_progress_unresolved_dims.sql for the usual causes.
SELECT count(DISTINCT content_id) AS violations FROM mart.video_heatmap
WHERE content_version IS NULL;
