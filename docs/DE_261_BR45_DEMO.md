# DE_261 walkthrough for BR4 and BR5

Use the [restoration runbook](BR45_RESTORATION.md) to build and start the current checkout. Commands below describe the original workstation walkthrough.

## Classroom accounts and live pipeline on port 8000

Run from the repository root. The classroom uses a separate PostgreSQL database, Debezium connector, Kafka topics and consumer group, and Spark checkpoint on the existing Compose network.

```bash
# Choose the shared classroom password before the first initialization.
export EDU_BR45_CLASSROOM_PASSWORD='DE261-Classroom-Only'
(cd apps/web && npm run build)
docker compose -f docker-compose.yml -f docker-compose.br45-classroom.yml \
  up -d --no-build --pull never demo br45-classroom-cdc br45-classroom-stream
```

Use the password you set above for all three accounts at [Learner sign-in](http://127.0.0.1:8000/learner). The first initialization stores the account hashes. Later starts preserve the existing profiles, credentials, and progress.

| Username | Student | Preset |
| --- | --- | --- |
| `an.demo` | An Pham | Recent Python activity, a prior FizzBuzz attempt, and completed SQL Foundations |
| `chi.demo` | Chi Hoang | Four previous-week Python activities and an overdue FizzBuzz lab |
| `ha.demo` | Ha Dang | New enrollment with limited history |

1. Open [Advisor](http://127.0.0.1:8000/advisor) with `advisor-demo`. In **Python for Data**, open **Chi Hoang** and check the initial warning. Page through the low-risk learners to find **Ha Dang**, whose enrollment is too new to score.
2. Sign in as Chi. Start and complete two different Python lessons to record four activities. Wait for the Advisor poll to show the recent activity and the lower score. The overdue lab still contributes risk points.
3. Open **Code Lab** and select **FizzBuzz**. Submit a solution and inspect its feedback. Open [Instructor](http://127.0.0.1:8000/instructor) with `instructor-demo` and select **FizzBuzz** in **Python for Data**. The attempt and its per-test evaluations share the Code Lab submission ID. Check Chi’s Advisor record again after the submission.
4. Sign out and sign in as An or Ha to smoke-test their courses, recommendations, and submission history. The recorded benchmark comparisons appear below both staff dashboards.

Use this FizzBuzz solution to smoke-test a passing attempt.

```python
def fizzbuzz(n):
    return [
        "FizzBuzz" if i % 15 == 0 else "Fizz" if i % 3 == 0 else "Buzz" if i % 5 == 0 else str(i)
        for i in range(1, n + 1)
    ]
```

Dung Vo studies regularly, Khoa Bui catches up on a missed SQL lab, and Lan Do retries a failed Python submission. The server runs these routines without a browser. A completed bot cycle advances the classroom clock one logical hour, about once per wall-clock minute after the previous boundary reaches the risk mart. Assessment and activity timestamps use that classroom clock. Allow a streaming batch and the dashboard poll for updates to appear.

For frontend changes, compile the assets and restart the classroom web container. For Python changes, run the restart command alone. The restart uses the same image and bind mounts. Sign in again after a web restart.

```bash
(cd apps/web && npm run build)
docker compose -f docker-compose.yml -f docker-compose.br45-classroom.yml restart demo
```

To return port 8000 to the earlier replay, stop the classroom workers and recreate the web container with the replay overlay. The classroom database and checkpoints remain available.

```bash
docker compose -f docker-compose.yml -f docker-compose.br45-classroom.yml \
  stop br45-classroom-cdc br45-classroom-stream
docker compose -f docker-compose.yml -f docker-compose.br45-replay.yml \
  up -d --no-build --pull never --no-deps --force-recreate demo
```

## Simulated live replay on port 8000

The replay uses the existing Instructor and Advisor dashboards. Each of the three synthetic courses has its own assessments and fictional learners. Both dashboards share four stages. The server advances after 60 seconds, or when you click **Advance demo** on either dashboard. A click restarts the countdown.

From the repository root, with the existing local Docker image and Compose dependencies running:

```bash
(cd apps/web && npm run build)
DEMO_PORT=8000 docker compose -f docker-compose.yml -f docker-compose.br45-replay.yml \
  up -d --no-build --pull never --no-deps --force-recreate demo
```

- Open [Instructor](http://127.0.0.1:8000/instructor) with `instructor-demo`. In **Python for Data**, select **Sum even numbers** to follow the test corrections from 2/24 to 22/24 passes.
- Open [Advisor](http://127.0.0.1:8000/advisor) with `advisor-demo`. Select **Linh Dao** in **Python for Data** and follow the alert and risk history from 100 to 0 points. **Measured benchmarks** under each dashboard shows the saved performance results separately from the replay.

After a React change, compile the frontend assets, then restart the container. For a Python-only change, run the restart command by itself. Both use the same Docker image, and a restart returns the replay to stage one.

```bash
(cd apps/web && npm run build)
docker compose -f docker-compose.yml -f docker-compose.br45-replay.yml restart demo
```

To return port 8000 to persistent BR45, recreate the web container with the base Compose file.

```bash
DEMO_PORT=8000 docker compose -f docker-compose.yml \
  up -d --no-build --pull never --no-deps --force-recreate demo
```

## Persistent walkthrough on port 8001

The Instructor reviews a suspicious grading result, then the Advisor follows a learner from an early warning through re-engagement. Both views use the same synthetic **Python for Data** course. PostgreSQL source writes go through Debezium and Kafka. BR4 serves SQL assessment marts, and BR5 uses Spark Structured Streaming to update activity windows and risk.

## Prepare the demo

Run from the repository root with Docker Compose, `jq`, and the project's Python environment. Set up that environment with `python3 -m venv .venv` and `.venv/bin/pip install -e '.[demo,dev]'` if needed. Use a local demo stack because its manual clock applies to every course in that stack.

```bash
export EDU_BR45_CLOCK_MODE=manual
docker compose --profile br45 up -d --build br45-init br45-cdc br45-stream redis

RUN=rehearsal-01
DATA="data/br45-demo/DE_261_BR45_${RUN}.json"
br45demo() { .venv/bin/python -m edu_platform.br45.demo_dataset "$@"; }
br45demo build --run-id "$RUN"

docker compose run --detach --no-deps --name "de261-br45-web-$RUN" \
  --publish 127.0.0.1:8001:8000 \
  --env "EDU_BR45_AUTH=$(jq -c .auth "$DATA")" demo

br45demo apply "$DATA" baseline
br45demo check "$DATA" baseline
```

The generator uses the persisted BR45 clock, or the current UTC hour on a fresh stack. The default host PostgreSQL port is 5433. If the stack publishes another port, set `EDU_BR45_DSN` to that local database before using the CLI. The fixture expects the default BR45 policy and hourly windows. Its JSON contains source rows, staged writes, local demonstration tokens, and hand-calculated expectations. For an offline copy, pass a timezone-aware UTC hour with `build --at`.

## BR4 · Review and correct an assessment

1. Open [Instructor](http://127.0.0.1:8001/instructor). In **Assessment health**, connect with `br45-instructor-demo` and select the synthetic course. Leave the date fields blank to follow the demo clock.
2. Select **Normalize input rows**. Point out the 24 passes in 28 valid attempts, the first and latest valid rates of 20/24 and 24/24, and the two excluded attempts. Select **Validate CSV headers** to show why five passes from five learners still leave the question with insufficient data.
3. Select **Sum even numbers** and open the test-case breakdown. The `case-empty-input` test has two passes from 24 learners, while both peers pass 24/24. In this scenario the grading team finds a faulty expected result for the empty input test. The regrade corrects the 20 affected evaluations and leaves two genuine failures.

```bash
br45demo apply "$DATA" regrade
br45demo check "$DATA" regrade
```

The next successful dashboard poll shows 22/24 for both the question and the empty input test. The review flags clear. The evidence records the 20 source updates in Debezium's WAL envelopes.

## BR5 · Acknowledge an alert and show recovery

1. Open [Advisor](http://127.0.0.1:8001/advisor) and connect with `br45-advisor-demo`. Keep the default date and level filters. Select the learner whose ID ends in `needs-outreach`. The initial score is 100, with 0 recent and 4 previous-week activities and 1 of 1 required deadlines missed.
2. Compare the 50-point learner who missed the same deadline but was recently active. On the next page of the risk queue, inspect the new enrollment that is too recent to score and `learner-24`, whose submission is present and whose last activity is unknown. Return to `needs-outreach` on the first page and click **Acknowledge**.

```bash
br45demo check "$DATA" acknowledged
br45demo apply "$DATA" reengage
br45demo check "$DATA" reengage
```

3. Show four recent and four previous-week activities, the drop to 50 points, and the resolved alert. The risk history includes the 100- and 50-point checkpoints. The missed assignment remains outstanding, so the advisor can follow up on the work still due.

The `check` command polls the APIs and CDC audit log, then records expected and observed values in `DE_261_BR45_<run-id>_evidence.json` beside the dataset. For a retry, apply the same stage again. A completed stage is a no-op, including a baseline retry after regrading. Use a fresh run ID for a new walkthrough, starting at the current persisted clock. Stop the scoped web container with `docker stop "de261-br45-web-$RUN"` when finished.

## CO5173 evaluation

| Criterion | Evidence to present |
| --- | --- |
| Data correctness | Compare the generated expectations with the API and CDC values in the evidence JSON. Explain the valid-attempt denominator, the sample-size guard, the event-time windows, and the single alert's state changes. |
| BR4 processing performance | The existing benchmark compares PostgreSQL SQL aggregation with Python over the same validated grading facts at 1,000, 10,000, and 100,000 evaluations. It also measures persisted refresh, mart reads, and correction refresh. [BR4 benchmark CSV](evidence/br45/br4_benchmark.csv) |
| BR5 processing performance | The existing benchmark compares Spark's Kafka-to-persisted-window processing with a Python batch calculation at 1,000, 10,000, and 100,000 unique events. It starts at normalized Kafka messages and measures through the window sink. The separate end-to-end evidence covers CDC-to-alert latency. [BR5 benchmark CSV](evidence/br45/br5_stream_benchmark.csv) · [End-to-end evidence](evidence/br45/final_e2e_result.json) |
| Usefulness to each role | The instructor identifies the test to inspect and confirms the corrected result. The advisor can explain a warning, record acknowledgement, and check the learner's response. These are scripted demonstrations of the two workflows. |

For historical BR5 effectiveness, report the existing held-out 2014 Open University Learning Analytics Dataset (OULAD) evaluation separately. On pooled daily cutoff observations, the default policy had precision of 12.1%, recall of 11.1%, F1 of 0.116, and average precision of 0.058 for withdrawal within 30 days. This historical comparison measures predictive performance at daily resolution. The live demo evaluates the intervention workflow with synthetic records. [OULAD evaluation](evidence/br45-v2/oulad_evaluation.json) · [Open University dataset](https://research.stem.open.ac.uk/ouanalyse/dataset/)
