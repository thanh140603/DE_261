# Runbook — alternative-stack benchmark

Hướng dẫn cho teammate chạy lại data generation và 3 cặp benchmark. Chạy từ
root repo (`/home/minhle/WORK/DE_261`), dùng `.venv` sẵn có.

---

## 0. Trạng thái và phạm vi

| Cặp | Stack hiện tại | Alternative | Trạng thái |
|---|---|---|---|
| A. Streaming | Spark Structured Streaming | Flink 1.19 SQL | đã đo filter 100k event |
| B. OLAP | PostgreSQL | ClickHouse (StarRocks fallback) | đã đo 1M/5M/10M |
| C. Feature store | Redis (cap 512 MiB) | ScyllaDB 6.2 + PostgreSQL reference | đã đo 1M; Redis/PG 5M |

Đây là benchmark local một máy. Không sửa pipeline BR1–BR8 mặc định, không
dùng số liệu trong runbook để tuyên bố production capacity.

---

## 1. Yêu cầu

- Docker Desktop + WSL2, còn ít nhất **8 GB RAM trống** khuyến nghị.
- Python 3.11, repo đã có `.venv`.
- Dependencies benchmark:

```bash
.venv/bin/uv pip install --python .venv/bin/python cassandra-driver
```

`confluent-kafka`, `redis`, `psycopg` đã có trong project dependencies.

- Port cần trống:

```text
5433  PostgreSQL
6379  Redis production
6380  Redis benchmark
9042  ScyllaDB
8123  ClickHouse HTTP
9002  ClickHouse native
8082  Flink UI
8000  demo API
9092  Kafka
```

---

## 2. Sinh data 5 GiB

Data nằm trong `benchmarks/alternatives/data/` và **đã gitignore**.
Cần khoảng **16 GB disk** cho cả 3 file.

```bash
mkdir -p benchmarks/alternatives/data

.venv/bin/python benchmarks/alternatives/feature_store/generate_features.py \
  --size-gb 5 \
  --output benchmarks/alternatives/data/features-5gb.jsonl

.venv/bin/python benchmarks/alternatives/streaming/generate_events.py \
  --size-gb 5 \
  --output benchmarks/alternatives/data/events-5gb.jsonl

.venv/bin/python benchmarks/alternatives/olap/generate_facts.py \
  --size-gb 5 \
  --output benchmarks/alternatives/data/org-facts-5gb.csv
```

Kỳ vọng:

| File | Rows | Bytes |
|---|---:|---:|
| `features-5gb.jsonl` | 14.375.660 | 5.368.709.338 |
| `events-5gb.jsonl` | 17.410.669 | 5.368.709.155 |
| `org-facts-5gb.csv` | 44.492.023 | 5.368.709.188 |

Mỗi file có sidecar `.manifest.json`. Kiểm tra:

```bash
wc -l benchmarks/alternatives/data/*-5gb.*
cat benchmarks/alternatives/data/features-5gb.jsonl.manifest.json
```

### Tạo subset

Không cần nạp 5 GiB cho mọi phép đo. Tạo tiền tố 1M/5M/10M:

```bash
head -n 1000001  benchmarks/alternatives/data/org-facts-5gb.csv > benchmarks/alternatives/data/org-facts-1m.csv
head -n 5000001  benchmarks/alternatives/data/org-facts-5gb.csv > benchmarks/alternatives/data/org-facts-5m.csv
head -n 10000001 benchmarks/alternatives/data/org-facts-5gb.csv > benchmarks/alternatives/data/org-facts-10m.csv

head -n 1000000 benchmarks/alternatives/data/features-5gb.jsonl > benchmarks/alternatives/data/features-1m.jsonl
head -n 5000000 benchmarks/alternatives/data/features-5gb.jsonl > benchmarks/alternatives/data/features-5m.jsonl

head -n 100000 benchmarks/alternatives/data/events-5gb.jsonl > benchmarks/alternatives/data/events-100k.jsonl
```

---

## 3. Pair B — PostgreSQL vs ClickHouse

### 3.1. Bật ClickHouse

```bash
docker compose -f docker-compose.yml -f docker-compose.bench.yml \
  --profile bench-olap up -d bench-clickhouse
curl -sS http://localhost:8123/ping   # Ok.
```

ClickHouse dùng port host `8123` và `9002` (9001 đã bị MinIO chiếm).

### 3.2. Load dữ liệu

```bash
for scale in 1m 5m 10m; do
  .venv/bin/python -m benchmarks.alternatives.olap.load_postgres \
    benchmarks/alternatives/data/org-facts-${scale}.csv \
    --out benchmarks/alternatives/results/olap/load_postgres_${scale}.json

  .venv/bin/python -m benchmarks.alternatives.olap.load_clickhouse \
    benchmarks/alternatives/data/org-facts-${scale}.csv \
    --out benchmarks/alternatives/results/olap/load_clickhouse_${scale}.json
done
```

Lưu ý: mỗi lần load sẽ `DROP/CREATE` bảng `bench.org_facts`; chạy tuần tự,
không song song.

### 3.3. Query

```bash
for scale in 1m 5m 10m; do
  .venv/bin/python -m benchmarks.alternatives.olap.query_olap \
    --engine both --repeat 3 --label "${scale}"
done
```

Kết quả: `benchmarks/alternatives/results/olap/query_latency_*.json`,
`summary.csv`.

Kỳ vọng:

| Rows | PG p50 | ClickHouse p50 |
|---:|---:|---:|
| 1M | 6.289 ms | 84,96 ms |
| 5M | 33.829 ms | 369,81 ms |
| 10M | 69.898 ms | 664,76 ms |

Correctness phải in `12 groups match`. Nếu lệch, dừng và kiểm tra CSV/schema.

---

## 4. Pair C — Redis vs ScyllaDB

### 4.1. Bật service

```bash
docker compose -f docker-compose.yml -f docker-compose.bench.yml \
  --profile bench-kv up -d bench-redis bench-scylla
```

- `bench-redis`: `maxmemory=512mb`, `allkeys-lru`, port `6380`.
- `bench-scylla`: ScyllaDB 6.2, 1 vCPU, 1 GB memory, cgroup 3 GB, port `9042`.

Nếu Scylla báo:

```text
insufficient physical memory: needed ..., available 500000000
```

thì cgroup quá nhỏ. Giải phóng RAM (`docker compose stop spark spark-worker trino hive-metastore`)
rồi thử lại. Cấu hình compose đã đặt `mem_limit: 3g`.

Kiểm tra CQL:

```bash
.venv/bin/python - <<'PY'
from cassandra.cluster import Cluster
c = Cluster(["127.0.0.1"], port=9042)
print(c.connect().execute("SELECT release_version FROM system.local").one())
c.shutdown()
PY
```

### 4.2. Load

```bash
for scale in 1m 5m; do
  .venv/bin/python -m benchmarks.alternatives.feature_store.load_redis \
    benchmarks/alternatives/data/features-${scale}.jsonl \
    --out benchmarks/alternatives/results/feature_store/load_redis_${scale}.json

  .venv/bin/python -m benchmarks.alternatives.feature_store.load_postgres \
    benchmarks/alternatives/data/features-${scale}.jsonl \
    --out benchmarks/alternatives/results/feature_store/load_postgres_${scale}.json
done

# Scylla chỉ cần mốc 1M (1 vCPU load 5M rất lâu)
.venv/bin/python -m benchmarks.alternatives.feature_store.load_scylla \
  benchmarks/alternatives/data/features-1m.jsonl \
  --out benchmarks/alternatives/results/feature_store/load_scylla_1m.json
```

### 4.3. Lookup

```bash
.venv/bin/python -m benchmarks.alternatives.feature_store.workload \
  --rows 1000000 --ops 10000 --repeat 3 --label 1m

.venv/bin/python -m benchmarks.alternatives.feature_store.workload \
  --rows 5000000 --ops 10000 --repeat 3 --label 5m

.venv/bin/python -m benchmarks.alternatives.feature_store.query_scylla \
  --rows 1000000 --ops 10000 --repeat 3 --label 1m
```

Kỳ vọng:

| Keys | Redis hit | Redis p50 | PG p50 | Scylla p50 |
|---:|---:|---:|---:|---:|
| 1M | 100% | 161,8 ms | 548,5 ms | 5.021,6 ms |
| 5M | 21,68% | 147,9 ms | 657,9 ms | chưa đo |

Redis 5M có p50 thấp nhưng chỉ giữ ~1,07M key; **luôn đọc kèm hit rate**.
Scylla 1M là single-node 1 GB/1 vCPU, không đại diện cho cluster scale-out.

---

## 5. Pair A — Spark vs Flink

Cần bật Flink cluster và dùng Kafka topic riêng. Không chạy đồng thời với
Pair B/C nếu máy thiếu RAM.

### 5.1. Chuẩn bị input

```bash
.venv/bin/python -m benchmarks.alternatives.streaming.prepare_ingest \
  --out benchmarks/alternatives/data/events-100k-ingest.jsonl
```

Kỳ vọng: `wrote 100000 rows ... expected matched=49913`.

Tạo topic:

```bash
for t in bench.events3 bench.flink.out3 bench.spark.out3; do
  docker exec de261-kafka kafka-topics --bootstrap-server localhost:9092 \
    --create --if-not-exists --topic "$t" --partitions 1 --replication-factor 1
done
```

Nạp event:

```bash
.venv/bin/python -m benchmarks.alternatives.streaming.produce_events \
  benchmarks/alternatives/data/events-100k-ingest.jsonl \
  --topic bench.events3
```

### 5.2. Flink

Tải connector (không commit JAR):

```bash
mkdir -p benchmarks/alternatives/streaming/jars
curl -L --fail \
  -o benchmarks/alternatives/streaming/jars/flink-sql-connector-kafka-3.3.0-1.19.jar \
  https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.3.0-1.19/flink-sql-connector-kafka-3.3.0-1.19.jar
```

Bật cluster:

```bash
docker compose up -d flink-jobmanager flink-taskmanager
```

Copy JAR vào cả hai container rồi restart:

```bash
for c in de261-flink-jobmanager de261-flink-taskmanager; do
  docker cp benchmarks/alternatives/streaming/jars/flink-sql-connector-kafka-3.3.0-1.19.jar \
    "$c:/opt/flink/lib/flink-sql-connector-kafka.jar"
done
docker restart de261-flink-jobmanager de261-flink-taskmanager
```

Đợi cluster:

```bash
curl -sS http://localhost:8082/overview
# taskmanagers=1, slots=4
```

Submit job:

```bash
docker run --rm --name de261-flink-sqlclient --network de261_default --memory=1g \
  -v "$PWD/benchmarks/alternatives/streaming/jars/flink-sql-connector-kafka-3.3.0-1.19.jar:/opt/flink/lib/flink-sql-connector-kafka.jar:ro" \
  -v "$PWD/benchmarks/alternatives/streaming/flink_filter.sql:/sql/flink_filter.sql:ro" \
  flink:1.19-scala_2.12-java11 /opt/flink/bin/sql-client.sh \
  -Drest.address=flink-jobmanager -Drest.port=8081 -f /sql/flink_filter.sql
```

Theo dõi output:

```bash
for i in $(seq 1 30); do
  docker exec de261-kafka kafka-run-class kafka.tools.GetOffsetShell \
    --broker-list localhost:9092 --topic bench.flink.out3
  sleep 2
done
```

Kỳ vọng offset `49913`. Dừng job Flink:

```bash
curl -sS http://localhost:8082/jobs/overview
# lấy jid, rồi:
curl -sS -X PATCH "http://localhost:8082/jobs/<jid>?mode=cancel"
```

### 5.3. Spark

Copy script và xoá checkpoint cũ:

```bash
docker cp benchmarks/alternatives/streaming/spark_filter.py \
  de261-spark:/tmp/spark_filter.py
docker exec de261-spark rm -rf /tmp/spark-bench-checkpoint
```

Chạy (blocking; mở terminal khác để poll):

```bash
docker exec de261-spark spark-submit \
  --master 'local[2]' --driver-memory 1g \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.5 \
  /tmp/spark_filter.py
```

Lần đầu `--packages` tải dependency, có thể mất 30–60 s. Poll:

```bash
docker exec de261-kafka kafka-run-class kafka.tools.GetOffsetShell \
  --broker-list localhost:9092 --topic bench.spark.out3
```

Kỳ vọng `49913`. Dừng Spark (kill cả driver JVM):

```bash
docker exec de261-spark pkill -f spark_filter.py || true
docker exec de261-spark pkill -f org.apache.spark.deploy.SparkSubmit || true
```

### 5.4. So correctness

```bash
.venv/bin/python -m benchmarks.alternatives.streaming.check_outputs --limit 49913
```

Kỳ vọng:

```json
{"spark_rows": 49913, "flink_rows": 49913, "match": true}
```

### 5.5. Kết quả Pair A

| Engine | Job runtime | Submit → output | Input ev/s |
|---|---:|---:|---:|
| Flink SQL | 9,16 s | 22 s | 10.917 |
| Spark Structured Streaming | 9,0 s | 44 s | 11.111 |

`submit → output` gồm startup/dependency; `job runtime` mới là so sánh xử lý.
Đây là filter, không phải cửa sổ 7 ngày BR5.

---

## 6. Kết quả và file cần giữ

```text
benchmarks/alternatives/results/
  environment.json
  summary.md
  olap/load_*.json
  olap/query_latency_*.json
  olap/summary.csv
  feature_store/load_*.json
  feature_store/lookup_*.json
  feature_store/lookup_scylla_*.json
  streaming/summary.json
```

Report dùng các số này trong mục `Alternative solutions`.

---

## 7. Troubleshooting

| Lỗi | Cách xử lý |
|---|---|
| ClickHouse bind 9001 | Dùng 9002; 9001 là MinIO |
| Redis 5M hit rate thấp | Đúng thiết kế cap 512 MiB; ghi kèm hit rate, không so p50 trực tiếp |
| Scylla `insufficient physical memory` | Tăng cgroup lên 3 GB, stop Spark/Trino để giải phóng RAM |
| Flink `UnsupportedFileSystemSchemeException: s3` | SQL đã set checkpoint local; kiểm tra `SET 'state.checkpoints.dir'` |
| Flink `Connection refused` | Đợi taskmanager register; `curl :8082/overview` phải có slot |
| Spark tải package chậm | Chờ lần đầu; các lần sau dùng cache Ivy |
| Output offset không đủ 49.913 | Kiểm tra topic input, checkpoint cũ, filter `score > 0.5` |
| Hết disk | 3 file 5 GiB chiếm ~16 GB; xoá subset không dùng |

---

## 8. Dọn dẹp

```bash
docker compose -f docker-compose.yml -f docker-compose.bench.yml \
  --profile bench-olap --profile bench-kv stop bench-clickhouse bench-redis bench-scylla
docker compose stop flink-jobmanager flink-taskmanager
```

Không dùng `docker compose down -v` vì sẽ xoá volume production.
