# Runbook: đo lại toàn bộ benchmark BR1–BR8 + Debezium vs polling

Tài liệu cho agent thực thi trên một máy khác. Mục tiêu: đo lại toàn bộ số liệu hiệu năng trên
**full stack Docker Compose** của repo, rồi cập nhật đúng chỗ trong báo cáo `report/`.

- Mọi lệnh chạy từ **thư mục gốc của repo**.
- Báo cáo đích: `report/main.tex` → `report/main.pdf`. Chỉ sửa trong `report/`; không sửa mã nguồn
  trừ khi cần sửa bug chặn phép đo (khi đó ghi lại).
- Không commit gì trừ khi được yêu cầu.

---

## 0.0 Phạm vi: toàn bộ BR1–BR8 + so sánh Debezium/polling

Runbook này **không chỉ BR1–BR3**. Mỗi BR có phép đo riêng, và mọi số đều phải được cập nhật:

| BR | Phép đo | Mục | Nguồn số |
|---|---|---|---|
| BR1 | sự kiện LMS → thông báo đọc được qua API | 4.1 | `br123_latency.csv` |
| BR2 | API gợi ý có feature store | 4.1 | `br123_latency.csv` |
| BR3 | nộp bài → 202 và nộp → `graded` | 4.1 | `br123_latency.csv` |
| BR4 | tổng hợp SQL vs Python theo quy mô | 4.2 | `br4_benchmark.csv` |
| BR5 | Kafka → Spark → cửa sổ đã lưu, thông lượng | 4.3 | `br5_stream_benchmark.csv` |
| BR6 | mart tiến độ tổ chức: Trino vs API cache | 4.4 | `serving_latency.csv` |
| BR7 | mart heatmap video: Trino vs API cache | 4.4 + 4.6 | `serving_latency.csv`, `live_overlay.csv` |
| BR8 | mart tương tác: Trino vs API cache; xuất bản → tìm kiếm được; lớp phủ trực tiếp | 4.4 + 4.5 + 4.6 | `serving_latency.csv`, `content_sync_latency.csv`, `live_overlay.csv` |
| BR6–BR8 | thời gian build kho (43 model) | 4.7 | `mart_build.csv` |
| CDC | Debezium vs polling trên 100k dòng | 4.8 | `cdc_100k_indexed.json` |

---

## 0. Nguyên tắc bắt buộc

1. **Full stack**: đo khi toàn bộ stack của compose đang sống (gồm cả Airflow), không tắt bớt dịch
   vụ để "cho nhanh", trừ khi troubleshooting và phải ghi rõ trong báo cáo.
2. **Không bịa số**: mọi con số trong báo cáo phải lấy từ CSV/JSON do các lệnh dưới sinh ra.
3. **Cô lập trạng thái**: `benchmarks/br123_latency.py` xoá hộp thư + dedup trước mỗi mẫu BR1 và xoá
   `edu:grading:*` trước mỗi mẫu BR3. Không được bỏ — nếu bỏ, BR1/BR3 sẽ trôi dần (xem mục 8).
4. **Ghi lại cách chạy**: số lượt, cờ đã dùng, phép đo nào fail và vì sao. Nếu không chạy lại được
   một phép đo, giữ số cũ và ghi chú "(không đo lại)".

---

## 1. Chuẩn bị

Yêu cầu: Docker + Docker Compose, môi trường Python 3.11 của repo (venv hoặc `uv`), và một
compiler LaTeX (XeLaTeX/`latexmk`, hoặc `tectonic`).

```bash
# kiểm tra môi trường Python của repo
python -V
python -c "import httpx, redis, psycopg, confluent_kafka, trino"

# nếu thiếu client Trino cho benchmark serving
uv pip install trino        # hoặc: pip install trino

# kiểm tra Docker
docker compose version
docker ps
```

Các cổng dùng trong repo: API `8000`, Trino `8091`, OpenSearch `9200`, Kafka `9092`, Debezium
Connect `8083`, Airflow `8088`, MinIO `9000/9001`, PostgreSQL `5433`.

---

## 2. Dựng full stack

```bash
docker compose \
  -f docker-compose.yml -f docker-compose.br13.yml \
  --profile br45 --profile br678 --profile airflow --profile pipelines \
  up -d --build
```

Kiểm tra:

```bash
docker ps
curl -sf localhost:8000/api/health && echo demo-ok
curl -sf localhost:8088/health && echo airflow-ok
curl -sf localhost:9200 >/dev/null && echo opensearch-ok
curl -sf localhost:8091/v1/info >/dev/null && echo trino-ok

# Airflow phải parse đủ 6 DAG, tất cả đang paused
docker compose -f docker-compose.yml -f docker-compose.br13.yml exec -T airflow-scheduler \
  airflow dags list
```

Điều kiện dữ liệu (thiếu thì benchmark sẽ sai/không chạy):

```bash
# lakehouse đã build: phải thấy features, gold, mart, ops, silver
docker compose -f docker-compose.yml -f docker-compose.br13.yml exec -T trino \
  trino --user analyst --execute "SHOW SCHEMAS FROM lakehouse"

# feature store online cho BR2
docker compose -f docker-compose.yml -f docker-compose.br13.yml exec -T redis \
  redis-cli --scan --pattern 'edu:features:longterm:*' | head
```

Full stack chạy đồng thời nhiều JVM (Spark, Trino, OpenSearch, Airflow, Kafka) nên rất sát trần bộ
nhớ. Nếu thấy container bị OOM-kill hoặc restart:

```bash
docker inspect -f '{{.RestartCount}} {{.State.OOMKilled}}' <container>
```

Khi đó tạm dừng các job streaming không cần cho phép đo hiện tại (`br45-stream`, `br45-cdc`,
`lakehouse-streaming`), đo xong bật lại, và ghi rõ trong báo cáo nếu số đo lấy trên cấu hình thiếu.

---

## 3. Thứ tự chạy khuyến nghị

| # | Nhóm | Lý do |
|---|------|-------|
| 1 | BR1–BR3 | nhẹ, không phụ thuộc profile nào thêm |
| 2 | BR4 + BR5 | cần profile `br45` |
| 3 | BR6–BR8 serving | cần Trino + API |
| 4 | BR8 content | cần OpenSearch + content-sync |
| 5 | BR7/BR8 live | cần `telemetry-live` rảnh; dễ fail nếu chạy song song |
| 6 | Marts build | rất nặng (CPU + I/O), chạy một mình |
| 7 | Debezium vs polling | tạo bảng riêng 100k dòng, chạy cuối |

---

## 4. Các lệnh benchmark

### 4.1 BR1–BR3 — độ trễ đầu cuối

```bash
for i in 1 2 3 4 5; do
  python benchmarks/br123_latency.py \
    --samples 20 --br2-samples 30 \
    --out "report/data/br123_latency_run$i.csv"
done
```

Gộp 5 lượt thành `report/data/br123_latency.csv` (n = 100 cho BR1/BR3, 150 cho BR2) và tính
median/p90/min/max:

```bash
python - <<'PY'
import csv, statistics
def pct(v,q):
    s=sorted(v); return s[round(q*(len(s)-1))]
pool={}
for i in range(1,6):
    for r in csv.DictReader(open(f"report/data/br123_latency_run{i}.csv",encoding="utf-8")):
        pool.setdefault(f"{r['path']} {r['metric']}",[]).append(float(r['latency_ms']))
for k,v in pool.items():
    print(f"{k:26} n={len(v):3} med={statistics.median(v):6.1f} p90={pct(v,.9):6.1f} min={min(v):6.1f} max={max(v):7.1f}")
PY
```

Kiểm tra hợp lệ: trung vị của 5 lượt phải tương đối ổn định. Nếu BR1 tăng dần qua các lượt, hoặc
BR3 tăng dần, nghĩa là cơ chế cô lập trạng thái không còn tác dụng — xem mục 8.

### 4.2 BR4 — SQL vs Python

```bash
docker compose -f docker-compose.yml -f docker-compose.br13.yml --profile br45 \
  up -d br45-init br45-cdc br45-stream

docker compose -f docker-compose.yml -f docker-compose.br13.yml --profile br45 \
  exec -T br45-cdc python -m edu_platform.br45.cli seed

# vài phút; ghi docs/evidence/br45/br4_benchmark.csv
python -m edu_platform.br45.cli benchmark
cp docs/evidence/br45/br4_benchmark.csv "report/data/br4_benchmark.csv"
```

Cột CSV: `sql_ms, python_ms, persisted_refresh_ms, query_ms, correction_refresh_ms`; mỗi kích thước
(1.000 / 10.000 / 100.000) có 3 repeat → lấy **trung bình 3 repeat**.
Lần chạy 100k đầu tiên có thể rất chậm do cold cache/JIT. Vẫn giữ cả 3 repeat như script làm; nếu
mean lệch nhiều so với median thì phải nói rõ trong báo cáo (ví dụ "trung bình 3 lần; lần đầu 100k
gồm cold cache") và chỉnh câu "tăng gần tuyến tính" ở đoạn BR4 cho khớp.

### 4.3 BR5 — Kafka → Spark → cửa sổ

```bash
# br45-cdc và br45-stream phải đang chạy (bước 4.2)
python -m edu_platform.br45.stream_benchmark
cp docs/evidence/br45/br5_stream_benchmark.csv "report/data/br5_stream_benchmark.csv"
```

Cột: `kafka_to_persisted_windows_ms, unique_events_per_second, python_batch_ms`; lấy trung bình 3
repeat theo `unique_events`.
Hai số acceptance trong báo cáo (`10.164 ms` và `20.142 ms`) đến từ kịch bản e2e khác, không phải
lệnh này — giữ nguyên trừ khi chạy lại kịch bản acceptance tương ứng.

### 4.4 BR6–BR8 — phục vụ mart

```bash
edu benchmark serving --requests 30 --out docs/evidence/br678/serving_latency.csv
cp docs/evidence/br678/serving_latency.csv "report/data/serving_latency.csv"
```

Cột: `br, mode (trino_uncached|api_cached), ms` → lấy **median theo (br, mode)**.

### 4.5 BR8 — xuất bản → tìm kiếm được

```bash
edu benchmark content --out docs/evidence/br678/content_sync_latency.csv
cp docs/evidence/br678/content_sync_latency.csv "report/data/content_sync_latency.csv"
```

Cột: `api_accept_ms, publish_to_searchable_ms` (20 lần) → median/p90/max của
`publish_to_searchable_ms`, median `api_accept_ms`.
Hình `fig:sync-latency` đọc trực tiếp file CSV này bằng pgfplots, nên chỉ cần copy CSV là hình tự
đổi; riêng đường kẻ trung vị thì hardcode trong .tex (xem mục 7).

### 4.6 BR7/BR8 — lớp phủ thời gian thực (dễ fail nhất)

```bash
edu benchmark live --out docs/evidence/br678/live_overlay.csv
```

- Mặc định 25/100/400 sessions × 3 repeat. Script chờ tối đa 180 s mỗi đợt; nếu `telemetry-live`
  tụt lại sẽ ném `TimeoutError: condition not reached`.
- Trước khi chạy: dừng `br45-stream`/`br45-cdc`/`lakehouse-streaming` nếu đang bật; đợi
  `docker compose logs --tail=5 telemetry-live` hết cảnh báo "falling behind".
- Nếu vẫn timeout, chạy từng mức rồi nối kết quả (giữ header một lần):
  ```bash
  edu benchmark live --sessions 25  --repeat 3 --out /tmp/live_25.csv
  edu benchmark live --sessions 100 --repeat 3 --out /tmp/live_100.csv
  edu benchmark live --sessions 400 --repeat 3 --out /tmp/live_400.csv
  ```
  sau đó ghi thành `report/data/live_overlay.csv`.
- Nếu mức 400 vẫn không chạy được trên full stack: giữ nguyên hàng 400 trong bảng cũ, ghi rõ là
  không đo lại được. Không tự suy diễn số.

### 4.7 Marts — thời gian build kho dữ liệu

```bash
edu benchmark marts --days 35 --days 70 --days 140 \
  --out docs/evidence/br678/mart_build.csv
cp docs/evidence/br678/mart_build.csv "report/data/mart_build.csv"
```

Cột: `days, repeat, total_s, silver_s, gold_s, mart_s, ...` → trung bình 2 repeat theo `days`.
Mỗi lần build mất vài phút; chạy một process cho mỗi lần (như production), đừng build lặp trong
cùng driver.

### 4.8 Debezium vs polling (negative-control)

```bash
# 1) bảng nguồn 100.000 dòng, có index updated_at
python -m benchmarks.cdc.setup_source benchmarks/cdc/data/org-facts-1m.csv --rows 100000

# 2) đăng ký connector (xoá trước nếu đã có)
curl -sS -X DELETE localhost:8083/connectors/bench-cdc >/dev/null 2>&1 || true
curl -sS -X POST -H 'Content-Type: application/json' \
  --data @benchmarks/cdc/connector.json localhost:8083/connectors

# 3) đợi snapshot: offset topic bench.bench.cdc_source đạt 100000
docker compose -f docker-compose.yml -f docker-compose.br13.yml exec -T kafka \
  kafka-run-class kafka.tools.GetOffsetShell --broker-list localhost:9092 \
  --topic bench.bench.cdc_source

# 4) đo: 8 s, 100 UPDATE + 10 DELETE
python -m benchmarks.cdc.run_benchmark --duration 8 --updates 100 --deletes 10 \
  --out benchmarks/cdc/results/cdc_100k_indexed.json
cp benchmarks/cdc/results/cdc_100k_indexed.json "report/data/cdc_100k_indexed.json"
```

JSON có `polling.latency_ms.{p50,p95}`, `polling.query_count`, `polling.tuples_returned` và phần
Debezium tương ứng. Kỳ vọng về mặt logic: Debezium nhận đủ 100 UPDATE + 10 DELETE, polling nhận
100 UPDATE + 0 DELETE.

---

## 5. Script tính số cho báo cáo

Chạy sau khi đã copy đủ CSV vào `report/data/`:

```bash
python - <<'PY'
import csv, json, statistics
from pathlib import Path
D = Path("report/data")
def rows(name):
    with open(D / name, encoding="utf-8") as fh: return list(csv.DictReader(fh))
def pct(v,q):
    s=sorted(v); return s[round(q*(len(s)-1))]
def stat(label,v):
    print(f"{label:30} n={len(v):3} med={statistics.median(v):8.1f} p90={pct(v,.9):8.1f} min={min(v):8.1f} max={max(v):8.1f}")

print("== BR1-BR3"); g={}
for r in rows("br123_latency.csv"): g.setdefault(f"{r['path']} {r['metric']}",[]).append(float(r["latency_ms"]))
for k,v in g.items(): stat(k,v)

print("== BR4 (mean 3 repeat)"); g={}
for r in rows("br4_benchmark.csv"):
    for c in ("sql_ms","python_ms","persisted_refresh_ms","query_ms"):
        g.setdefault((r["evaluation_rows"],c),[]).append(float(r[c]))
for (size,c),v in sorted(g.items(), key=lambda x:(int(x[0][0]),x[0][1])):
    print(f"{size:>7} {c:22} mean={statistics.mean(v):9.1f}")

print("== BR5 (mean 3 repeat)"); g={}
for r in rows("br5_stream_benchmark.csv"):
    for c in ("kafka_to_persisted_windows_ms","unique_events_per_second","python_batch_ms"):
        g.setdefault((r["unique_events"],c),[]).append(float(r[c]))
for (size,c),v in sorted(g.items(), key=lambda x:int(x[0][0])):
    print(f"{size:>7} {c:30} mean={statistics.mean(v):10.1f}")

print("== serving (median)"); g={}
for r in rows("serving_latency.csv"): g.setdefault((r["br"],r["mode"]),[]).append(float(r["ms"]))
for k,v in sorted(g.items()): print(f"{k[0]} {k[1]:16} median={statistics.median(v):7.1f}")

print("== content")
v=[float(r["publish_to_searchable_ms"]) for r in rows("content_sync_latency.csv")]
a=[float(r["api_accept_ms"]) for r in rows("content_sync_latency.csv")]
stat("publish->searchable",v); print(f"api_accept median={statistics.median(a):.1f}")

if (D/"live_overlay.csv").exists():
    print("== live"); g={}
    for r in rows("live_overlay.csv"): g.setdefault(r["sessions"],[]).append((float(r["event_to_api_ms"]),int(r["raw_events"])))
    for s,vals in sorted(g.items(), key=lambda x:int(x[0])):
        t=[x for x,_ in vals]
        print(f"{s:>4} sess mean={statistics.mean(t):7.0f} min={min(t):7.0f} max={max(t):7.0f} raw={statistics.mean([n for _,n in vals]):.0f}")

if (D/"mart_build.csv").exists():
    print("== marts"); g={}
    for r in rows("mart_build.csv"):
        for c in ("total_s","silver_s","gold_s","mart_s"):
            g.setdefault((r["days"],c),[]).append(float(r[c]))
    for (d,c),v in sorted(g.items(), key=lambda x:(int(x[0][0]),x[0][1])):
        print(f"{d:>4}d {c:9} mean={statistics.mean(v):7.1f}")

if (D/"cdc_100k_indexed.json").exists():
    print("== cdc"); d=json.load(open(D/"cdc_100k_indexed.json"))
    for eng in ("debezium","polling"):
        b=d.get(eng,{})
        print(eng,{k:b.get(k) for k in ("events","updates","deletes","query_count","tuples_returned")},
              "p50/p95",b.get("latency_ms",{}).get("p50"),b.get("latency_ms",{}).get("p95"))
PY
```

---

## 6. Copy CSV vào báo cáo

Bảng tổng hợp nguồn → đích:

| Sinh ra từ | Copy tới |
|---|---|
| 5 lượt `br123_latency_run*.csv` | gộp thành `report/data/br123_latency.csv` |
| `docs/evidence/br45/br4_benchmark.csv` | `report/data/br4_benchmark.csv` |
| `docs/evidence/br45/br5_stream_benchmark.csv` | `report/data/br5_stream_benchmark.csv` |
| `docs/evidence/br678/serving_latency.csv` | `report/data/serving_latency.csv` |
| `docs/evidence/br678/content_sync_latency.csv` | `report/data/content_sync_latency.csv` (pgfplots đọc trực tiếp) |
| `docs/evidence/br678/live_overlay.csv` | `report/data/live_overlay.csv` |
| `docs/evidence/br678/mart_build.csv` | `report/data/mart_build.csv` |
| `benchmarks/cdc/results/cdc_100k_indexed.json` | `report/data/cdc_100k_indexed.json` |

---

## 7. Bản đồ sửa số trong báo cáo

Số dòng là theo bản hiện tại và có thể dịch khi sửa; luôn tìm theo **anchor text**.

| # | File:dòng | Anchor / nội dung | Thay bằng |
|---|---|---|---|
| 1 | `report/chapters/05-danh-gia.tex:95-98` | 4 hàng bảng `tab:br123-latency` | n, median, p90, min, max từ `br123_latency.csv` gộp 5 lượt |
| 2 | `05-danh-gia.tex:86` | "Mỗi mẫu BR1/BR3 lặp 20 lần … lặp năm lượt" | số lượt/n nếu khác; giữ câu giải thích cô lập trạng thái |
| 3 | `05-danh-gia.tex:103` | "BR1 đạt trung vị khoảng 16 ms …" | trung vị + khoảng p90 mới |
| 4 | `05-danh-gia.tex:120-126` | 4 dòng `\addplot … coordinates` của `fig:br4` | SQL = mean `sql_ms`; Python = mean `python_ms`; refresh = mean `persisted_refresh_ms`; query = mean `query_ms` |
| 5 | `05-danh-gia.tex:107` | "Python nhanh hơn khoảng hai lần …" | kiểm tra tỉ lệ Python/SQL từ CSV rồi sửa câu |
| 6 | `05-danh-gia.tex:130` | caption `fig:br4` "(trung bình 3 lần…)" | giữ nếu vẫn 3 repeat |
| 7 | `05-danh-gia.tex:145-147` | 3 hàng bảng `tab:br5` | mean 3 repeat: `kafka_to_persisted_windows_ms`, `unique_events_per_second`, `python_batch_ms` |
| 8 | `05-danh-gia.tex:136` | "10.164 ms … 20.142 ms" | chỉ đổi nếu chạy lại kịch bản acceptance |
| 9 | `05-danh-gia.tex:170,172` | 2 dòng `\addplot` của `fig:serving` | median `trino_uncached` và `api_cached` cho BR6/BR7/BR8 |
| 10 | `05-danh-gia.tex:176` | caption `fig:serving` | giữ "30 request mỗi trường hợp" nếu `--requests 30` |
| 11 | `05-danh-gia.tex:195-196` | `\draw … 535` + label "trung vị 535 ms" | median mới từ `content_sync_latency.csv` (cả toạ độ và nhãn) |
| 12 | `05-danh-gia.tex:203` | "API nhận … 16,9 ms … trung vị 535 ms, p90 992 ms …" | median `api_accept_ms`; median/p90/max `publish_to_searchable_ms` |
| 13 | `05-danh-gia.tex:214-216` | 3 hàng bảng `tab:live` | mean raw_events, mean (min–max) `event_to_api_ms`, cột "Chính xác" |
| 14 | `05-danh-gia.tex:221` | "Độ trễ gần như không đổi khi tải tăng 15 lần …" | kiểm tra lại theo số mới |
| 15 | `05-danh-gia.tex:236-242` | 4 dòng `\addplot` của `fig:build` | mean theo `days`: `silver_s`, `gold_s`, `mart_s`, phần còn lại = `total_s − silver_s − gold_s − mart_s` |
| 16 | `05-danh-gia.tex:250` | "143,7; 128,6 và 135,8 giây …" | mean `total_s` cho 35/70/140 ngày |
| 17 | `05-danh-gia.tex:271-278` | 8 hàng bảng `tab:cdc` | từ JSON: events/updates/deletes, `latency_ms.p50/p95`, `query_count`, `query_ms.p50`, tuples returned |
| 18 | `05-danh-gia.tex:280-285` | đoạn giải thích polling/Debezium | sửa nếu số đổi nghĩa |
| 19 | `05-danh-gia.tex:65` | đoạn môi trường đo | mô tả đúng máy/stack đã dùng khi chạy |
| 20 | `05-danh-gia.tex:72-78` | bảng `tab:env` | ngày đo, Máy, Engine (Spark 3.5.5, Trino 478, OpenSearch 2.17.1, PostgreSQL 16.15) |
| 21 | `00-tom-tat.tex:10-15` | 6 bullet số liệu tóm tắt | BR1–3, BR5, BR8, BR7–8, BR6–8, kho dữ liệu |
| 22 | `06-ket-luan.tex:9` | "Cảnh báo BR5 sau khoảng 10 giây và lớp phủ sau khoảng 7 giây" | nếu số tương ứng đổi |
| 23 | `06-ket-luan.tex:13` | "với 100.000 lượt chấm, một lần sửa tốn khoảng 4 giây" | mean `persisted_refresh_ms` ở 100k |
| 24 | `06-ket-luan.tex:39` | "… khoảng 10 giây … nửa giây … vài mili-giây …" | khớp số mới |
| 25 | `02-kien-truc.tex:159` | "độ trễ đo được khoảng 7 giây đủ cho lớp phủ" | nếu số live đổi |
| 26 | `05-danh-gia.tex:308` | bullet thảo luận "BR5 khoảng 10 giây … nửa giây … 7 giây" | khớp số mới |
| 27 | `appendices/A-huong-dan-chay.tex` | mục "Đo hiệu năng" | cập nhật lệnh/cờ nếu khác |

Ghi chú:

- **`report/data/content_sync_latency.csv`** được pgfplots đọc trực tiếp (`fig:sync-latency`).
- Các hình BR4/BR5/serving/live/marts/CDC dùng số **hardcode trong .tex** — phải sửa tay.
- Nếu một phép đo không chạy lại được: giữ số cũ + ghi chú "(không đo lại)".

---

## 8. Build lại PDF và kiểm tra

```bash
# 1) dựng PDF (dùng một trong hai)
cd report
latexmk -xelatex main.tex          # hoặc: tectonic -X compile main.tex
cd ..

# 2) đọc log LaTeX: hộp tràn lề và tham chiếu/trích dẫn chưa phân giải
grep -c "Overfull" report/main.log                         # nên = 0
grep -nE "Undefined (reference|citation)" report/main.log   # nên rỗng

# 3) kiểm tra PDF thực sự chứa nội dung mới (so khớp theo CHỮ HIỂN THỊ)
python - <<'PY'
import pypdf
r = pypdf.PdfReader("report/main.pdf")
t = "\n".join((p.extract_text() or "") for p in r.pages)
print("pages:", len(r.pages))
must_have = [
    "Môi trường đo",                    # mục 5.3
    "Độ trễ BR1",                       # BR1--BR3
    "tổng hợp SQL so với Python",       # BR4
    "thông lượng cửa sổ",               # BR5
    "phục vụ mart",                     # BR6--BR8 serving
    "xuất bản đến khi tìm kiếm",        # BR8 content
    "negative-control",                 # Debezium vs polling
    "Thời gian build kho",              # marts
]
print("thiếu mục:", [s for s in must_have if s not in t] or "không")
print("số chỗ còn '??':", t.count("??"))   # dấu hiệu tham chiếu chưa phân giải
PY
```

Ba bước này trả lời ba câu hỏi khác nhau: (1) PDF có dựng được không, (2) LaTeX có cảnh báo bố cục
hay tham chiếu hỏng không, (3) file PDF có thật sự chứa nội dung mới (không phải bản cũ còn sót).
Khi so khớp, chỉ dùng **chữ hiển thị** (tiêu đề mục, caption, một con số); đừng kiểm tra
`tab:...`, `fig:...` hay `\label` — các nhãn này không bao giờ xuất hiện trong PDF.

Sau khi build: mở PDF kiểm tra nhanh các hình BR4, serving, sync, live, marts và bảng CDC — không
tràn, nhãn số khớp bảng.

---

## 9. Pitfalls (lỗi đã gặp, không phụ thuộc máy)

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `ModuleNotFoundError: trino` khi chạy `edu benchmark serving` | môi trường Python thiếu client Trino | `uv pip install trino` (hoặc `pip install trino`) |
| Container bị OOM-kill / restart khi full stack | nhiều JVM chạy cùng lúc | tạm dừng `lakehouse-streaming`, `br45-*` khi đo nhóm khác; bật lại sau; ghi rõ nếu số đo trên cấu hình thiếu |
| `TimeoutError: condition not reached` ở `benchmark live` | `telemetry-live` tụt lại so với burst | dừng job streaming khác, đợi log hết "falling behind", chạy từng mức sessions |
| BR1 tăng dần qua các lượt | hộp thư tích luỹ (API trả cả danh sách) | giữ nguyên dòng xoá `edu:notif:inbox:<learner>` mỗi mẫu trong `benchmarks/br123_latency.py` |
| BR3 "nộp → 202" tăng dần | `attempt_number` quét toàn bộ bài nộp trong Redis | giữ nguyên dòng xoá `edu:grading:*` mỗi mẫu trong `benchmarks/br123_latency.py` |
| Số serving/BR4 chậm hơn nhiều so với lần đo trước | full stack đang tranh CPU/RAM hoặc cold cache | chấp nhận số full-stack và ghi rõ môi trường; không so trực tiếp với lần đo trên máy/stack khác |
| Debezium không thấy event | connector chưa đăng ký hoặc snapshot chưa xong | kiểm tra `curl localhost:8083/connectors/bench-cdc/status`, đợi offset đủ 100k |

---

## 10. Checklist trước khi báo xong

- [ ] Full stack sống, health-check đạt, không restart/OOM trong lúc đo.
- [ ] BR1–BR3: 5 lượt, CSV gộp, trung vị ổn định (không trôi).
- [ ] BR4, BR5: CSV mới + đã tính trung bình 3 repeat.
- [ ] Serving, content: CSV mới + median đúng.
- [ ] Live: đo được 25/100/400 hoặc ghi rõ lý do không đo lại.
- [ ] Marts: `mart_build.csv` mới cho 35/70/140 ngày.
- [ ] CDC: JSON mới, bảng `tab:cdc` khớp (đặc biệt DELETE: Debezium 10, polling 0).
- [ ] Toàn bộ mục 7 đã cập nhật; không còn số cũ trong tóm tắt/kết luận.
- [ ] PDF build lại, 0 Overfull, không undefined reference/citation.
