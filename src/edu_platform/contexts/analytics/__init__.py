"""Analytics context: gold-layer marts for instructors, advisors and admins.

    BR4  assessment_item_stats   pass rate per question / test case, anomaly flag
    BR6  org_progress_report     skill progress + completion per organisation (min-cohort)
    BR7  video_heatmap           play/pause/seek density per second of each video
    BR8  engagement_trend        windowed engagement score + declining-trend flag

All marts read only silver tables (published contracts) and never raw PII.
"""
