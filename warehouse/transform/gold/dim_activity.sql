-- gold.dim_activity: the closed learning-verb vocabulary (telemetry.domain.Verb) with the
-- categories the analytics domain scores on. engagement_category mirrors EngagementPolicy's
-- verb -> weight mapping; video_interaction mirrors BuildVideoHeatmap's play/pause/seek.
-- tests/unit/warehouse/test_vocabulary_sync.py fails if this drifts from the domain.
INSERT OVERWRITE gold.dim_activity
SELECT xxhash64(verb) AS activity_key, verb, activity_group, engagement_category, video_interaction, description
FROM VALUES
  ('logged_in', 'access',     'login',      CAST(NULL AS STRING), 'Signed in on any platform'),
  ('viewed',    'content',    'view',       NULL,                 'Opened a lesson, slide deck or page'),
  ('played',    'content',    'view',       'play',               'Started / resumed video playback'),
  ('paused',    'content',    NULL,         'pause',              'Paused video playback'),
  ('seeked',    'content',    NULL,         'seek',               'Jumped to another video position (rewind / forward)'),
  ('completed', 'content',    'view',       NULL,                 'Finished a lesson or content item'),
  ('attempted', 'assessment', 'attempt',    NULL,                 'Started an exercise or quiz'),
  ('submitted', 'assessment', 'attempt',    NULL,                 'Submitted an exercise for grading'),
  ('posted',    'social',     'discussion', NULL,                 'Posted in a course discussion')
AS v(verb, activity_group, engagement_category, video_interaction, description);
