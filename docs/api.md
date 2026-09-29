# Demo API contract (server: FastAPI, prefix `/api`)

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
  `{event_type:"assignment_created"|"deadline_approaching"|"course_updated", course_id, assignment_id?, hours_to_deadline?, title?}`
  -> `{event_id, notifications:{created, suppressed:[{learner_id, reason}]}}`
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
  { next_step:{course_id, lesson_id, title, reason} | null,
    courses:[{course_id, title, score, reason}],
    features:{longterm:{completion_rate_30d, avg_pass_rate_30d, active_days_30d, preferred_platform, skill_mastery:{[skill]:number}} | null,
              session:{session_id, active_minutes, events_in_session, last_verbs:[], current_course_id, struggle_score, updated_at} | null } }
  ```
- `POST /api/submissions` body `{learner_id, assignment_id, code}` -> `{submission_id, status:"queued"}` (202)
- `GET /api/submissions/{id}` ->
  ```
  { id, learner_id, assignment_id, language, status:"queued"|"running"|"graded"|"failed", attempt_number, submitted_at,
    result:{stdout, stderr, runtime_ms, memory_kb, exit_code, pass_rate,
            tests:[{test_case_id, status, expected, actual, diff, duration_ms}]} | null,
    feedback:{summary, failed_tests:[...same as tests], stderr_excerpt, hints:[]} | null }
  ```
- `GET /api/learners/{id}/submissions` -> `[Submission]` newest first (same shape, without stdout)

## Instructor (BR4 anomalies, BR7 heatmap, BR8 content sync + engagement)
- `GET /api/instructor/assessments?course_id=` -> `[{assignment_id, assignment_title, item_id, attempts, passes, pass_rate, assignment_median_pass_rate, is_anomalous}]`
- `GET /api/instructor/videos/{content_id}/heatmap` -> `{content_id, title, duration_sec, buckets:[{second, play, pause, seek, learners}]}` (one bucket per second, zeros included)
- `GET /api/instructor/courses/{course_id}/engagement` ->
  `{windows:[{start,end}], learners:[{pseudonym, scores:[number], declining:bool}], course_avg:[number]}`
- `GET /api/instructor/content/{content_id}` -> `{id, course_id, title, content_type, versions:[{number, published_at, checksum}], indexed_version, chunk_count, cache_state:"warm"|"invalidated", search_version}`
- `POST /api/instructor/content/{content_id}` body `{title?, body}` -> `{version, sync:[{step, status:"done"|"skipped", ms}], notifications_created}`

## Advisor (BR5)
- `GET /api/advisor/alerts` -> `[{learner_id, learner_name, course_id, course_title, score, top_signals:[], at}]` newest first
- `GET /api/advisor/learners/{id}/risk` -> `{learner_id, courses:[{course_id, score, computed_at, signals:[{kind, weight, observed_at}], history:[{at, score}], last_alert_at}], policy:{window_days, slide_days, alert_threshold, cooldown_days}}`

## Admin (BR6)
- `GET /api/admin/organisations/{org_id}/progress` -> `{organisation_id, as_of, min_cohort:5, rows:[{course_id, course_title, skill, cohort_size, completion_rate|null, avg_mastery|null, suppressed:bool}]}`
