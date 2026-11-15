# Đo lại BR1 và BR3 (sau khi sửa pagination + attempt counter)

> **Cập nhật kế hoạch báo cáo:** không tách thành 3 bảng nữa. Giữ một bảng `tab:br123-latency`
> (BR2 giữ số cũ, BR1/BR3 điền sau khi đo) và thêm biểu đồ latency theo độ dài inbox. Xem
> `docs/report-br123-scaling-handoff.md`; mục 5 dưới đây chỉ là phương án cũ.

Tài liệu này hướng dẫn đo lại **BR1** và **BR3** để điền vào bảng `tab:br123-latency` trong báo
cáo. **BR2 giữ nguyên số cũ**, không cần đo lại; nếu có chạy kèm thì cũng không thay bảng BR2.
Kế hoạch báo cáo hiện hành (một bảng + biểu đồ scaling) nằm ở
`docs/report-br123-scaling-handoff.md`; mục 5 dưới đây là phương án cũ, không dùng nữa.

## 0. Code đã thay đổi gì (để đọc kết quả cho đúng)

- **BR1**: API `GET /api/learners/{id}/notifications` nhận `?limit=` và có thêm
  `GET .../notifications/unread?since=`. Harness đo vẫn đọc **toàn bộ inbox** để giữ điều kiện so
  sánh với số cũ, nhưng không xoá inbox thật nữa:
  - trước khi chạy: snapshot danh sách id trong inbox + dedup key;
  - trong lúc đo: làm trống inbox, mỗi mẫu chỉ xoá thông báo do chính mẫu đó tạo;
  - sau khi chạy (kể cả lỗi): khôi phục inbox + dedup.
- **BR3**: `attempt_number` do một bộ đếm O(1) theo `(learner, assignment)` cấp
  (`INCR edu:grading:attempts:<learner>:<assignment>`), không còn quét lịch sử bài nộp.
  Harness chỉ đặt counter về 0 trước mỗi mẫu, không xoá `edu:grading:*`; sau khi chạy, các
  submission do benchmark tạo được xoá khỏi Redis và counter được trả về giá trị trước khi đo.
  **Lưu ý**: projection PostgreSQL của các submission đó vẫn còn (giống mọi submission đã chấm),
  nên nếu cần sạch tuyệt đối thì phải dọn thêm ở Postgres/lakehouse.

## 1. Điều kiện trước khi chạy

Stack BR1/BR3 phải ở **service mode** (không phải demo mode), vì counter attempt nằm trong Redis
và API phải đọc Redis:

```bash
docker compose \
  -f docker-compose.yml -f docker-compose.br13.yml \
  --profile br45 --profile br678 --profile airflow --profile pipelines \
  up -d --build

curl -sf localhost:8000/api/health && echo api-ok
docker compose -f docker-compose.yml -f docker-compose.br13.yml exec -T demo \
  printenv EDU_BR13_MODE        # phải in ra: service
```

Ghi lại trạng thái demo trước khi đo (để đối chiếu sau):

```bash
curl -s localhost:8000/api/learners/l-002/notifications \
  | .venv/bin/python -c 'import json,sys; print("inbox:", len(json.load(sys.stdin)))'
curl -s localhost:8000/api/learners/l-002/submissions \
  | .venv/bin/python -c 'import json,sys; print("submissions:", len(json.load(sys.stdin)))'
```

Không chạy benchmark trong lúc đang quay clip demo: BR3 vẫn tạo submission thật (dù được dọn khỏi
Redis sau khi chạy) và có thể làm giao diện nhấp nháy.

## 2. Chạy 5 lượt

Từ thư mục gốc repo, chạy đúng 5 lượt (mỗi lượt 20 mẫu BR1/BR3, 30 mẫu BR2):

```bash
for i in 1 2 3 4 5; do
  .venv/bin/python benchmarks/br123_latency.py \
    --samples 20 --br2-samples 30 \
    --out "report/data/br123_latency_run$i.csv"
done
```

- Mỗi lượt in ra 4 dòng summary (BR1, BR2, BR3 ack, BR3 graded).
- Nếu một lượt fail giữa chừng, **xoá file `br123_latency_run$i.csv` cũ** rồi chạy lại lượt đó;
  file cũ còn lại sẽ bị script gộp đọc nhầm.
- Harness tự khôi phục inbox/dedup và counter sau mỗi lượt; không cần `redis-cli DEL` thủ công.

## 3. Gộp 5 lượt + tính thống kê

Script dưới đây ghi lại `report/data/br123_latency.csv` (đánh số `run` lại 1..N cho từng metric,
đúng format file hiện tại) và in bảng thống kê để điền báo cáo:

```bash
.venv/bin/python - <<'PY'
import csv, statistics
from pathlib import Path

rows = []
for i in range(1, 6):
    path = Path(f"report/data/br123_latency_run{i}.csv")
    with path.open(encoding="utf-8") as fh:
        rows.extend(csv.DictReader(fh))

out = Path("report/data/br123_latency.csv")
with out.open("w", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    writer.writerow(["path", "metric", "run", "latency_ms"])
    counters: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["path"], row["metric"])
        counters[key] = counters.get(key, 0) + 1
        writer.writerow([row["path"], row["metric"], counters[key], row["latency_ms"]])

groups: dict[str, list[float]] = {}
for row in rows:
    groups.setdefault(f"{row['path']}/{row['metric']}", []).append(float(row["latency_ms"]))

def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[round(q * (len(ordered) - 1))]

for key, values in groups.items():
    print(
        f"{key:28} n={len(values):3d} "
        f"median={statistics.median(values):6.1f} p90={pct(values, .9):6.1f} "
        f"min={min(values):6.1f} max={max(values):7.1f}"
    )
print(f"wrote {out}")
PY
```

Kỳ vọng số dòng:

| File | Số dòng dữ liệu |
|---|---|
| `br123_latency_run1..5.csv` | 90 mỗi file (20 BR1 + 30 BR2 + 20×2 BR3) |
| `br123_latency.csv` | 450 (n = 100 BR1, 150 BR2, 100 mỗi metric BR3) |

## 4. Kiểm tra trước khi điền số

1. **Không trôi**: tính median từng lượt cho BR1 và BR3; nếu tăng dần qua 5 lượt thì cơ chế cô lập
   có vấn đề (kiểm tra `EDU_BR13_MODE=service`, API có đọc Redis không).
2. **Inbox được khôi phục**: số notification sau khi chạy phải bằng số trước khi đo (mục 1).
3. **Submission được dọn**: số submission sau khi chạy phải bằng số trước khi đo.
4. **Counter được trả lại**: `redis-cli GET edu:grading:attempts:l-002:a-py-even` phải giống
   trước khi đo (thường là rỗng nếu demo chưa có attempt nào).

Lệnh kiểm tra nhanh xu hướng:

```bash
.venv/bin/python - <<'PY'
import csv, statistics
from collections import defaultdict
for i in range(1, 6):
    groups = defaultdict(list)
    for row in csv.DictReader(open(f"report/data/br123_latency_run{i}.csv", encoding="utf-8")):
        groups[f"{row['path']}/{row['metric']}"].append(float(row["latency_ms"]))
    print(f"run{i}", {k: round(statistics.median(v), 1) for k, v in groups.items()})
PY
```

## 5. Ba bảng trong báo cáo

Thay bảng `tab:br123-latency` hiện tại bằng **ba bảng riêng**. BR2 điền đúng số cũ; BR1/BR3 để
`--` trong lúc chờ kết quả đo lại.

### 5.1 BR1

```latex
\begin{table}[H]
\centering\small
\caption{Latency BR1 (ms)}\label{tab:br1-latency}
\begin{tabular}{@{}L{7.2cm}rrrrr@{}}
\toprule
\textbf{Đường đo} & \textbf{n} & \textbf{Median} & \textbf{p90} & \textbf{Nhỏ nhất} & \textbf{Lớn nhất} \\
\midrule
BR1: sự kiện $\rightarrow$ thông báo đọc được qua API & -- & -- & -- & -- & -- \\
\bottomrule
\end{tabular}
\end{table}
```

Điền từ nhóm `BR1/event_to_inbox` ở mục 3 (n = 100 nếu đủ 5 lượt). Dùng dấu phẩy thập phân
(ví dụ `12,4`) cho khớp văn phong báo cáo.

### 5.2 BR2 (giữ nguyên số cũ)

```latex
\begin{table}[H]
\centering\small
\caption{Latency BR2 (ms)}\label{tab:br2-latency}
\begin{tabular}{@{}L{7.2cm}rrrrr@{}}
\toprule
\textbf{Đường đo} & \textbf{n} & \textbf{Median} & \textbf{p90} & \textbf{Nhỏ nhất} & \textbf{Lớn nhất} \\
\midrule
BR2: API gợi ý có feature store & 150 & 2,2 & 4,2 & 1,4 & 12,2 \\
\bottomrule
\end{tabular}
\end{table}
```

Không thay các số này bằng kết quả lần chạy mới (kể cả khi loop có đo BR2).

### 5.3 BR3

```latex
\begin{table}[H]
\centering\small
\caption{Latency BR3 (ms)}\label{tab:br3-latency}
\begin{tabular}{@{}L{7.2cm}rrrrr@{}}
\toprule
\textbf{Đường đo} & \textbf{n} & \textbf{Median} & \textbf{p90} & \textbf{Nhỏ nhất} & \textbf{Lớn nhất} \\
\midrule
BR3: nộp bài $\rightarrow$ 202 & -- & -- & -- & -- & -- \\
BR3: nộp bài $\rightarrow$ \code{graded} & -- & -- & -- & -- & -- \\
\bottomrule
\end{tabular}
\end{table}
```

Điền từ `BR3/submit_ack` và `BR3/submit_to_graded` (mỗi nhóm n = 100).

## 6. Các chỗ cần sửa trong báo cáo sau khi có số

Chi tiết danh sách đã liệt kê riêng; tóm tắt:

- `report/chapters/05-danh-gia.tex`: thay block bảng dòng 113–124 bằng 3 bảng trên; sửa đoạn dẫn
  dòng 110 và đoạn phân tích dòng 127 (giữ phần BR2, thay phần BR1/BR3 bằng số mới).
- `report/chapters/00-tom-tat.tex` dòng 10: bullet tóm tắt BR1–BR3 — giữ BR2, cập nhật BR1/BR3.
- `report/chapters/05-danh-gia.tex` dòng 68 và bảng môi trường dòng 94/98: cập nhật ngày/commit
  của lần đo lại nếu chạy trên commit mới.
- `report/chapters/05-danh-gia.tex` dòng 329 (phần giới hạn): cập nhật mô tả "đã khắc phục" cho
  pagination và counter.
- Rebuild `report/main.pdf` sau khi sửa.

## 7. Xử lý sự cố

| Hiện tượng | Nguyên nhân / cách xử lý |
|---|---|
| BR1 `notification did not appear` | notification service chưa consume Kafka, hoặc dedup key còn; kiểm tra `docker compose ... logs notification`, chạy lại lượt đó |
| BR3 `submission ... did not finish grading` | worker/normalizer tắc; xem log `grading-worker`, `grading-normalizer`; chạy lại lượt |
| BR1/BR3 median tăng dần | kiểm tra `EDU_BR13_MODE=service`; harness phải dùng Redis repo, không phải in-memory |
| Sau khi chạy, inbox demo trống | script bị kill trước `finally`; chạy lại một lượt để restore, hoặc dựng lại từ `edu:notif:item:*` (TTL 30 ngày) |
| Counter attempt sai sau khi chạy | kiểm tra `GET edu:grading:attempts:l-002:a-py-even`; script restore giá trị trước khi đo, nếu file bị kill giữa chừng thì đặt lại thủ công |
| Submission benchmark còn trong Postgres | dọn theo `submission_id` trong bảng `grading.submissions`/`public.submissions` nếu cần môi trường demo sạch tuyệt đối |

## 8. Ghi chú

- Không cần xoá `report/data/br123_latency.csv` trước khi chạy: script gộp ở mục 3 ghi đè.
- Nếu chỉ muốn đo BR1/BR3 mà không tốn thời gian BR2, vẫn nên giữ `--br2-samples 30` để file CSV
  cùng format; bảng BR2 trong báo cáo không lấy từ lần chạy này.
- Số BR2 cũ trong báo cáo: n = 150, median 2,2 ms, p90 4,2 ms, min 1,4 ms, max 12,2 ms
  (nguồn: `report/data/br123_latency.csv`, lần đo 13/11/2026).
