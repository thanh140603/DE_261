# Demo API contract (server: FastAPI, prefix `/api`)

BR4/BR5 also expose persistent, course-scoped analytics. Their full contract,
metric semantics and examples are documented in
[BR4/BR5 implementation](BR4_BR5_IMPLEMENTATION.md#8-apis-and-user-interface)
and the server's `/docs` / `/openapi.json`. Use an analytics bearer token;
these results come from PostgreSQL rather than the legacy simulator.

All responses JSON. Timestamps ISO-8601 UTC. Errors: `{ "detail": "..." }` with 4xx/5xx.
Live updates: `GET /api/events` is Server-Sent Events; each message is
`{ "type": <string>, "at": <iso>, "payload": <object> }` with types:
`telemetry.raw`, `telemetry.silver`, `telemetry.dlq`, `notification`, `risk.alert`,
`submission.graded`, `content.sync`, `stats` (stats payload = same shape as /pipeline/stats).

## Reference data
- `GET /api/health` -> `{status:"ok", mode:"demo"}`
- `GET /api/demo/overview` ->
  ```
  { organisations:[{id,name}],
    courses:[{id,title,org_id,skill,lessons:[{id,title,content_id,duration_sec}]}],
    learners:[{id,name,org_id,course_ids:[],advisor_id}],
    assignments:[{id,title,course_id,language:"python"|"sql",prompt,starter_code,test_case_ids:[]}],
    advisors:[{id,name}] }
  ```

## Simulation (drives the pipelines)
- `POST /api/simulate/start` body `{rate_per_sec?:number}` -> `{running:true, rate_per_sec}`
- `POST /api/simulate/stop` -> `{running:false}`
- `GET  /api/simulate/status` -> `{running, rate_per_sec, generated}`
- `POST /api/simulate/telemetry` body
  `{learner_id, verb, course_id?, content_id?, video_position_sec?, platform?, late_seconds?, schema_version?:"1.0"|"1.1", malformed?:bool}`
  -> `{event_id, outcome:"silver"|"dlq", reason?}`
- `POST /api/simulate/burst` body `{count:number}` -> `{generated, silver, dlq}`
- `POST /api/simulate/lms-event` body
  `{event_type:"assignment_created"|"deadline_approaching"|"course_updated", course_id, learner_id?, assignment_id?, hours_to_deadline?, title?}`
  -> `{event_id, queued?:bool, notifications:{created, suppressed:[{learner_id, reason}]}}`
  In service mode the event is published to Kafka; `queued:true` means the
  notification service owns routing and the count is not known synchronously.
- `POST /api/simulate/cdc` body
  `{table:"lesson_progress"|"enrollments"|"grades", learner_id, course_id, lesson_id?, percent_done?, status?, score?}`
  -> `{applied:true, risk?:{learner_id, course_id, score, alerted:bool}}`
- `POST /api/simulate/scenario/{name}` name in `at_risk_learner | broken_test_case | content_update | late_mobile_events`
  -> `{name, steps:[{at, message}], outcome:object}`

## Pipeline observability
- `GET /api/pipeline/stats` ->
  ```
  { bronze, silver, dlq, late_events, topics:{[topic]:count}, notifications_sent,
    notifications_suppressed, submissions_graded, risk_alerts, feature_rows,
    content_versions, last_event_at }
  ```
- `GET /api/pipeline/topics` -> `[{topic, count, last_at}]`
- `GET /api/pipeline/topics/{topic}?limit=20` -> `[{key, event_type, at, payload}]` newest first
- `GET /api/pipeline/dlq?limit=20` -> `[{event_id, reason, at, payload}]`
- `GET /api/pipeline/silver?limit=50&learner_id=` -> `[LearningEvent]` newest first
  LearningEvent = `{event_id, learner_pseudonym, course_id, content_id, session_id, verb, platform, occurred_at, received_at, lateness_seconds, video_position_sec, schema_version, late:bool}`

## Learner (BR1 notifications, BR2 recommendations, BR3 feedback)
- `GET /api/learners/{id}/notifications` -> `[{id, title, body, channels:[], priority, created_at, source_event_type, deep_link}]` newest first
- `GET /api/learners/{id}/recommendations` ->
  ```
  { next_step:{course_id, title, difficulty, category, score, reason} | null,
    enrolled:[{course_id, title, difficulty, category, completed}],
    courses:[{course_id, title, difficulty, category, score, reason}],
    features:{longterm:{completion_rate_30d, avg_pass_rate_30d, active_days_30d, preferred_platform, skill_mastery:{[skill]:number}} | null,
              session:{session_id, active_minutes, events_in_session, last_verbs:[], current_course_id, struggle_score, updated_at, started_at} | null } }
  ```
- `POST /api/submissions` body `{learner_id, assignment_id, code}` -> `{submission_id, status:"queued"}` (202)
  In service mode the API proxies to `grading-ingest`; the rest of this contract
  is unchanged. `EDU_BR13_MODE=demo` keeps the in-process grader.
- `GET /api/submissions/{id}` ->
  ```
  { id, learner_id, assignment_id, language, status:"queued"|"running"|"graded"|"failed", attempt_number, submitted_at,
    result:{stdout, stderr, runtime_ms, memory_kb, exit_code, pass_rate,
            tests:[{test_case_id, status, expected, actual, diff, duration_ms}]} | null,
    feedback:{summary, failed_tests:[...same as tests], stderr_excerpt, hints:[]} | null }
  ```
- `GET /api/learners/{id}/submissions` -> `[Submission]` newest first (same shape, without stdout)

## Instructor (BR4 anomalies, BR7 heatmap, BR8 content sync + engagement)

The persistent BR4 UI uses `/instructor/courses/{course_id}/questions/statistics`,
`/instructor/questions/{question_id}/statistics`,
`/instructor/questions/{question_id}/test-cases`,
`/instructor/courses/{course_id}/anomalies`, and `/instructor/anomalies/{id}`.
List responses are `{items,total,offset,limit}` and require an instructor token.
The `/assessments` endpoint below remains the older synthetic demo contract.

- `GET /api/instructor/assessments?course_id=` -> `[{assignment_id, assignment_title, item_id, attempts, passes, pass_rate, assignment_median_pass_rate, is_anomalous}]`
- `GET /api/instructor/videos/{content_id}/heatmap` -> `{content_id, title, duration_sec, buckets:[{second, play, pause, seek, learners}]}` (one bucket per second, zeros included)
- `GET /api/instructor/courses/{course_id}/engagement` ->
  `{windows:[{start,end}], learners:[{pseudonym, scores:[number], declining:bool}], course_avg:[number]}`
- `GET /api/instructor/content/{content_id}` -> `{id, course_id, title, content_type, versions:[{number, published_at, checksum}], indexed_version, chunk_count, cache_state:"warm"|"invalidated", search_version}`
- `POST /api/instructor/content/{content_id}` body `{title?, body}` -> `{version, sync:[{step, status:"done"|"skipped", ms}], notifications_created}`

## Advisor (BR5)

- `GET /api/advisor/alerts` -> `{items:[{id,student_id,course_id,score,level,reasons,status,evaluated_at,created_at,acknowledged_at,resolved_at}],total,offset,limit}`
- `GET /api/advisor/courses/{course_id}/at-risk-students` -> paginated risk rows plus monitored/risk-level summary
- `GET /api/advisor/students/{student_id}/risk` -> `{student_id,courses:[Risk]}`
- `GET /api/advisor/students/{student_id}/risk-history` -> paginated historical risk rows
- `PATCH /api/advisor/alerts/{id}/acknowledge` and `/resolve` -> persisted alert with lifecycle timestamps

These persistent endpoints require an advisor bearer token with an explicit
course scope. `Risk` includes 0–100 points, level, eligibility, features, reasons,
evaluation timestamp and policy. GET lists support offset/limit and applicable
course/level/date/status filters. Client code uses `analytics.ts`.

The older synthetic alert list remains at `/api/advisor/demo-alerts`, and the
older synthetic learner profile remains at `/api/advisor/learners/{id}/risk`.
The legacy `api.ts` client targets those demo endpoints.

## Admin (BR6)
- `GET /api/admin/organisations/{org_id}/progress` -> `{organisation_id, as_of, min_cohort:5, rows:[{course_id, course_title, skill, cohort_size, completion_rate|null, avg_mastery|null, suppressed:bool}]}` (older synthetic demo contract)

## Staff authentication

`POST /api/auth/staff/{role}/session` accepts `{username,password}` and sets a role-specific cookie. `GET` returns `{id,name,role,courses,organisations}` from that session. `DELETE` revokes the session and returns 204. Roles are `instructor`, `advisor` and `admin`. For staff data requests, send `X-Staff-Role` with the session cookie. Cookie-authenticated writes and staff session writes require the app's origin. Scripts can send a configured Bearer token. [Account setup](STAFF_AUTH.md)

## Lakehouse analytics (BR6, BR7, BR8)

Read from the warehouse marts (`mart.org_progress`, `mart.video_heatmap`,
`mart.engagement_trend`) through Trino as the read-only `app` user. Bearer tokens
come from `EDU_BR45_AUTH`, the same token file as BR4/BR5; an `admin` account
carries `organisations:[...]`, an `instructor` account `courses:[...]`.
Errors: 401 no/invalid token, 403 wrong role or outside scope, 404 nothing built
yet, 422 bad `as_of`, 503 Trino unavailable. Dates are UTC calendar days;
`built_at` is when the mart was built. Client code uses `analytics.ts`.

- `GET /api/lakehouse/session` -> `{id, role, courses:[{id,title}], organisations:[{id,name}]}` (names from `gold.dim_*`)
- `GET /api/admin/organisations/{org_id}/skill-progress?as_of=YYYY-MM-DD` (admin) ->
  `{organisation_id, organisation_name, as_of, built_at, min_cohort, rows:[{course_id, course_title, skill, cohort_size, completion_rate|null, avg_mastery|null, completed_learners|null, suppressed}]}`.
  Latest daily snapshot on or before `as_of`. Rates of a suppressed row (cohort < `min_cohort`) are always null.
- `GET /api/instructor/courses/{course_id}/videos` (instructor) -> `{course_id, videos:[{content_id, title, versions:[{version, duration_sec}]}]}` (versions newest first)
- `GET /api/instructor/videos/{content_id}/interaction-heatmap?version=` (instructor, course of the video in scope) ->
  `{video:{content_id, version, title, course_id, duration_sec}, as_of, window_days, built_at, versions:[...], seconds:[{second, play, pause, seek, learners, intensity}]}`.
  One row per second of that version (zeros included); newest version when `version` is omitted.
  `&live=true` (default) adds `live:{days, updated_at, seconds:[{second, play, pause, seek, learners}]} | null`:
  streamed events (Redis) for the days after `as_of`, newest version only, positions clamped
  to the video length; `null` when not applicable or Redis is unavailable.
- `GET /api/instructor/courses/{course_id}/engagement-trend?as_of=` (instructor) ->
  `{course_id, as_of, built_at, decline_ratio, declining_count, week_starts:[date], course_avg:[number], learners:[{learner_pseudonym, scores:[number], deltas:[number|null], declining}]}` (oldest week first)
  plus `live:{day, updated_at, scores:{pseudonym: points}, course_avg} | null` = today's
  streamed engagement (only without `as_of`, when the mart is older than today).

## Content sync (BR8)

Instructor token, course-scoped (403 outside scope, 404 unknown content, 503 when PostgreSQL,
MinIO, Redis or OpenSearch is unavailable). Publishing returns 202: the sync happens
asynchronously through CDC (`docs/adr/0013-br8-content-sync-cdc-opensearch.md`).

- `GET /api/instructor/courses/{course_id}/content` -> `{course_id, items:[ContentStatus]}`
- `GET /api/instructor/content/{content_id}/sync-status` -> `ContentStatus` =
  `{content_id, course_id, content_type, title, version, object_key, duration_sec, updated_at, indexed_version|null, indexed_at|null, chunk_count, cache_state:"warm"|"invalidated", in_sync}`
  (`version` = LMS row, `indexed_version` = what search serves; `in_sync` when equal)
- `POST /api/instructor/content/{content_id}/versions` body `{body, title?}` -> 202
  `{...catalog row, changed, status:"pending_sync"|"unchanged"}` (identical body and title create no version)
- `GET /api/instructor/content/{content_id}/document` -> `{content_id, course_id, title, version, body, cache:"hit"|"miss"}`
  (read-through Redis cache; a sync invalidates it)
- `GET /api/instructor/courses/{course_id}/search?q=&mode=hybrid|keyword&limit=10` ->
  `{course_id, query, mode, hits:[{content_id, version, title, ordinal, section_path, snippet, score}]}` (current versions only)
