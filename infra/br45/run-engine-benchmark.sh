#!/usr/bin/env bash
# Run from the repository root with the base Kafka and Connect services available.
set -euo pipefail

engine=${1:?Usage: bash infra/br45/run-engine-benchmark.sh prepare|br4|spark|flink RUN_ID}
run=${2:-}
work=data/br45-engine-benchmark
python=${PYTHON:-.venv/bin/python}
compose=(docker compose -f docker-compose.yml -f docker-compose.br45-benchmark.yml)
export EDU_BR45_ENGINE_BENCHMARK=true
export EDU_BR45_DSN=postgresql://lms:lms@127.0.0.1:15434/br45_bench
if [[ -n "${BR45_BENCH_COMPOSE_OVERLAY:-}" ]]; then
  compose+=(-f "$BR45_BENCH_COMPOSE_OVERLAY")
fi
export EDU_BR45_KAFKA="${BR45_BENCH_KAFKA:-localhost:9092}"
connect_url="${BR45_BENCH_CONNECT_URL:-http://127.0.0.1:8083}"
export BR45_BENCH_API=http://127.0.0.1:18001
mkdir -p "$work"
exec 9>"$work/benchmark.lock"
flock -n 9 || { echo "Another engine benchmark is running" >&2; exit 1; }

prepare() {
  install -d -m 0777 "$work/flink" "$work/runs"
  local maven=https://repo.maven.apache.org/maven2
  local name path
  while read -r name path; do
    if [[ ! -s "$work/flink/$name.jar" ]]; then
      if [[ -s "data/br45-v2/flink/$name.jar" ]]; then
        cp "data/br45-v2/flink/$name.jar" "$work/flink/$name.jar"
      else
        curl --fail --location --retry 2 "$maven/$path" -o "$work/flink/$name.jar.part"
        mv "$work/flink/$name.jar.part" "$work/flink/$name.jar"
      fi
    fi
  done <<'JARS'
ecj org/eclipse/jdt/ecj/3.33.0/ecj-3.33.0.jar
kafka org/apache/flink/flink-sql-connector-kafka/3.2.0-1.19/flink-sql-connector-kafka-3.2.0-1.19.jar
jdbc org/apache/flink/flink-connector-jdbc/3.2.0-1.19/flink-connector-jdbc-3.2.0-1.19.jar
postgresql org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar
JARS
  "${compose[@]}" build br45-bench-init br45-bench-spark
  "${compose[@]}" run --rm --no-deps --entrypoint sh br45-bench-flink -ec '
    classpath=$(printf "%s:" /opt/flink/lib/*.jar /work/flink/kafka.jar /work/flink/jdbc.jar /work/flink/postgresql.jar)
    build=$(mktemp -d /work/flink/classes.XXXXXXXX)
    java -jar /work/flink/ecj.jar -source 11 -target 11 -proc:none -cp "${classpath%:}" -d "$build" /source/RiskWindows.java
    chmod -R a+rX "$build"
    printf "%s\n" "${build##*/}" >/work/flink/latest-classes
  '
  "$python" - "$work/flink" <<'PY'
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

work = Path(sys.argv[1])
classes = work / (work / "latest-classes").read_text().strip()
with ZipFile(work / "risk-windows.jar", "w", ZIP_DEFLATED) as jar:
    for compiled in classes.rglob("*.class"):
        jar.write(compiled, compiled.relative_to(classes))
PY
  "${compose[@]}" up -d br45-bench-cdc br45-bench-api
  curl -fsS -X PUT "$connect_url/connectors/br45-engine-benchmark/resume"
  for _ in $(seq 1 30); do
    if curl -fsS "$BR45_BENCH_API/api/health" >/dev/null; then return; fi
    sleep 2
  done
  echo "Benchmark API did not start" >&2
  return 1
}

if [[ "$engine" == prepare ]]; then
  prepare
  exit
fi

[[ "$run" =~ ^[a-z0-9][a-z0-9-]{0,35}$ ]] || { echo "Supply a fresh lowercase run ID" >&2; exit 2; }
shift 2
mkdir -p "$work/runs"
if [[ "$engine" == br4 ]]; then
  [[ ! -e "$work/runs/$run-br4-postgres.json" && ! -e "$work/runs/$run-br4-spark.json" ]]
  "$python" -m edu_platform.br45.engine_benchmark postgres --run-id "$run" \
    --output "$work/runs/$run-br4-postgres.json" "$@"
  "${compose[@]}" run --rm --no-deps --pull never --entrypoint spark-submit \
    -e BR45_BENCH_API=http://br45-bench-api:8000 br45-bench-spark \
    --master 'local[2]' --driver-memory 1g --jars /work/flink/postgresql.jar \
    /app/src/edu_platform/br45/engine_benchmark.py spark --run-id "$run" \
    --output "/work/runs/$run-br4-spark.json" "$@"
  exit
fi

[[ "$engine" == spark || "$engine" == flink ]] || { echo "Unknown engine $engine" >&2; exit 2; }
stream_run="$run-$engine"
container="br45-engine-bench-$stream_run"
journal="$work/runs/$run-br5-$engine.json"
checkpoint="$work/runs/$stream_run-checkpoint"
[[ ! -e "$journal" && ! -e "$checkpoint" ]]
export BR45_BENCH_TOPIC="br45.engbench.activity.$stream_run"
export EDU_BR45_ACTIVITY_TOPIC=$BR45_BENCH_TOPIC

# Retire old benchmark learners before switching topics so both E2E workloads
# start from the same active cohort. Preserve source rows and alert evidence.
"$python" - <<'PY'
from edu_platform.br45.db import connect
from edu_platform.br45.engine_benchmark import require_isolation, wait

require_isolation()
with connect() as conn:
    retired = [
        row["id"] for row in conn.execute(
            "UPDATE br45.enrollments SET status='withdrawn' WHERE status='active' "
            "AND id ~ '-(spark|flink)-e2e-[0-9]+-enrollment$' RETURNING id"
        )
    ]

def landed():
    with connect() as conn:
        return not conn.execute(
            "SELECT 1 FROM analytics.clean_rows WHERE table_name='enrollments' "
            "AND row_key=ANY(%s) AND data->>'status'='active' LIMIT 1", (retired,)
        ).fetchone()

if retired:
    wait(landed, "Prior benchmark enrollments did not retire through CDC")
PY
"${compose[@]}" stop br45-bench-cdc
"$python" - <<'PY'
from confluent_kafka.admin import AdminClient, NewTopic
from edu_platform.br45.config import settings
from edu_platform.br45.db import connect, state

cfg = settings()
admin = AdminClient({"bootstrap.servers": cfg.kafka})
admin.create_topics([NewTopic(cfg.activity_topic, 1, 1)])[cfg.activity_topic].result(timeout=30)
with connect() as conn:
    state(conn, "published_offsets", {})
PY
"${compose[@]}" up -d --no-deps --no-build --pull never br45-bench-cdc

start_spark() {
  "${compose[@]}" run -d --no-deps --pull never --name "$container" \
    -e "EDU_BR45_BENCHMARK_WINDOW_RUN=$stream_run" \
    -e "EDU_BR45_CHECKPOINT=/work/runs/$stream_run-checkpoint" br45-bench-spark
}

start_flink() {
  "${compose[@]}" run -d --no-deps --pull never --name "$container" --entrypoint /opt/flink/bin/flink \
    -e "BR45_TOPIC=$BR45_BENCH_TOPIC" -e "BR45_RUN_ID=$stream_run" \
    -e "BR45_CHECKPOINT=file:///work/runs/$stream_run-checkpoint" \
    -e JVM_ARGS=-Xmx1g br45-bench-flink run -t local -p 2 -Dtaskmanager.numberOfTaskSlots=2 \
    -C file:///work/flink/kafka.jar -C file:///work/flink/jdbc.jar -C file:///work/flink/postgresql.jar \
    "$@" -c edu.br45.RiskWindows /work/flink/risk-windows.jar
}

stop_engine() {
  docker stop -t 15 "$container" >/dev/null 2>&1 || true
  if [[ "$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true)" == true ]]; then
    echo "Could not stop $container" >&2
    return 1
  fi
  docker logs "$container" >>"$work/runs/$stream_run.log" 2>&1 || true
  if [[ "$engine" == flink ]]; then
    mkdir -p "$work/runs/$stream_run-flink-logs"
    docker cp "$container:/opt/flink/log/." "$work/runs/$stream_run-flink-logs" 2>/dev/null || true
  fi
  docker inspect --format '{{json .State}}' "$container" >>"$work/runs/$stream_run-state.jsonl" 2>/dev/null || true
  docker rm "$container" >/dev/null 2>&1 || true
}
trap stop_engine EXIT

"start_$engine"
"$python" -m edu_platform.br45.engine_stream_benchmark "$engine" --run-id "$stream_run" \
  --output "$journal" "$@"

if "$python" -c 'import json,sys; rows=json.load(open(sys.argv[1]))["trials"]; sys.exit(not any(r["phase"]=="correctness" and r["status"]=="PASS" for r in rows))' "$journal"; then
  stop_engine
  container="$container-restore"
  if [[ "$engine" == spark ]]; then
    start_spark
  else
    snapshot=$(find "$checkpoint" -name _metadata -printf '%T@ %h\n' | sort -nr | sed -n '1{s/^[^ ]* //;p;}')
    [[ -n "$snapshot" ]]
    start_flink -s "file:///work/${snapshot#"$work/"}"
  fi
  "$python" -m edu_platform.br45.engine_stream_benchmark "$engine" --run-id "$stream_run" \
    --output "$journal" --restore-only
fi
