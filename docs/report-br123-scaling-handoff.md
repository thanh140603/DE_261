# Handoff cho agent: giữ bảng BR1–BR3 + thêm biểu đồ latency theo độ dài inbox

Tài liệu này dành cho agent chạy trên **máy khác** có Docker + stack BR1/BR3. Mục tiêu:

1. Giữ **một bảng** `tab:br123-latency` trong báo cáo (không tách thành 3 bảng). BR2 giữ nguyên số
   cũ; BR1/BR3 để trống (`--`) chờ chạy lại, rồi điền số mới.
2. Thêm một subsection + **biểu đồ latency tăng theo số thông báo trong inbox**, kết luận mức tăng
   rất ít và vẫn phù hợp cho production.
3. **Không so sánh với số cũ**, không nhắc "trước đây/đã sửa"; coi kiến trúc hiện tại là baseline
   ban đầu. Không bịa số; mọi số lấy từ CSV do script sinh ra.

> Tài liệu này thay thế mục 5 (ba bảng) của `docs/benchmark-br13-rerun.md`. Nếu mâu thuẫn, làm theo
> file này.

## 0. Trạng thái repo & nguyên tắc

- Code trong repo đã có: `for_recipient` dùng `MGET` + timeline ZSET, API nhận `?limit=`, endpoint
  `/notifications/unread?since=`, frontend tải trang; BR3 dùng counter attempt O(1).
- **Không sửa code ứng dụng** trừ khi có bug chặn đo. Chỉ rebuild image để container dùng code mới.
- Không đổi schema Redis sang Hash/ZSET JSON: đã đo, lợi ích < 1 ms và không làm latency phẳng.
- Không đụng `l-002` (learner demo) khi seed dữ liệu test; dùng `l-004` và dọn sạch sau khi đo.
- Báo cáo chỉ sửa trong `report/`; không commit nếu không được yêu cầu.

## 1. Chuẩn bị máy đích

```bash
cd <repo>
docker compose version
.venv/bin/python -V
.venv/bin/python -c "import httpx, redis; print('ok')"
```

Dựng/khôi phục stack BR1/BR3 (theo runbook):

```bash
docker compose \
  -f docker-compose.yml -f docker-compose.br13.yml \
  --profile br45 --profile br678 --profile airflow --profile pipelines \
  up -d --build

curl -sf localhost:8000/api/health && echo api-ok
docker compose -f docker-compose.yml -f docker-compose.br13.yml exec -T demo \
  printenv EDU_BR13_MODE        # phải là: service
```

**Bắt buộc rebuild image app** vì container có thể đang chạy image cũ:

```bash
# Nếu buildx báo lỗi read-only với ~/.docker, trỏ config vào repo:
mkdir -p .docker-buildx
BUILDX_CONFIG=$PWD/.docker-buildx \
docker compose -f docker-compose.yml -f docker-compose.br13.yml build demo

BUILDX_CONFIG=$PWD/.docker-buildx \
docker compose -f docker-compose.yml -f docker-compose.br13.yml \
  up -d --no-deps --force-recreate demo notification \
  grading-ingest grading-worker grading-normalizer
```

Kiểm tra nhanh code mới đã vào container:

```bash
curl -s "localhost:8000/api/learners/l-004/notifications?limit=1"
curl -s "localhost:8000/api/learners/l-004/notifications/unread?since=1970-01-01T00:00:00Z"
# cả hai phải trả 200, không phải 404/422
```

Nếu thiếu Kafka/Postgres/Redis, start theo runbook trước khi đo:

```bash
docker start de261-redis de261-kafka de261-postgres de261-schema-registry
docker ps --format '{{.Names}}\t{{.Status}}'
```

## 2. Phase 1 — chạy lại BR1/BR3 và điền bảng

Làm theo `docs/benchmark-br13-rerun.md` mục 1–4 (5 lượt, gộp CSV, kiểm tra không trôi). Tóm tắt:

```bash
for i in 1 2 3 4 5; do
  .venv/bin/python benchmarks/br123_latency.py \
    --samples 20 --br2-samples 30 \
    --out "report/data/br123_latency_run$i.csv"
done
```

Gộp 5 lượt thành `report/data/br123_latency.csv` bằng script trong guide đó; kiểm tra:

- BR1/BR3 median ổn định qua 5 lượt (không tăng dần).
- `curl .../l-002/notifications | wc -c` và số submission trước/sau mỗi lượt không đổi (harness
  snapshot/restore).
- BR2 **không thay** số trong báo cáo dù loop có đo BR2.

Số cần điền (dùng dấu phẩy thập phân):

| Hàng | Nguồn |
|---|---|
| BR1 | `BR1/event_to_inbox` trong `br123_latency.csv` |
| BR2 | **giữ nguyên** n=150, 2,2 / 4,2 / 1,4 / 12,2 |
| BR3 202 | `BR3/submit_ack` |
| BR3 graded | `BR3/submit_to_graded` |

Nếu BR1/BR3 chưa chạy xong: giữ `--` trong bảng, không lấy số cũ.

## 3. Phase 2 — đo latency theo độ dài inbox

### 3.1 Tạo script

File `benchmarks/inbox_read_scaling.py` **đã có trong repo** (đã smoke-test với n=0/10/50).
Nếu bản clone thiếu file, tạo lại với nội dung dưới; chạy trên máy đích, không cần sửa app:

```python
"""BR1: latency đọc inbox theo số thông báo, cho báo cáo.

Seed N notification tổng hợp cho một learner thử (mặc định l-004), đo API full inbox và
?limit=20, ghi CSV, rồi dọn sạch. Không dùng l-002 để tránh phá dữ liệu demo.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import redis

from edu_platform.contexts.notification.domain.model import (
    Channel,
    DedupKey,
    Notification,
    NotificationContent,
    Priority,
)
from edu_platform.contexts.notification.infrastructure.redis_notification_repository import (
    _to_dict,
)

LEARNER = "l-004"


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[round(q * (len(ordered) - 1))]


def seed(store: redis.Redis, learner: str, n: int) -> None:
    inbox = f"edu:notif:inbox:{learner}"
    timeline = f"edu:notif:time:{learner}"
    store.delete(inbox, timeline)
    base = datetime.now(tz=UTC) - timedelta(minutes=10)
    pipe = store.pipeline(transaction=False)
    for i in range(n):
        nid = f"bench-{i:03d}"
        notification = Notification(
            id=nid,
            recipient_id=learner,
            dedup_key=DedupKey(learner, "lms.deadline_approaching.v1", f"bench-{i}"),
            channels=(Channel.IN_APP,),
            priority=Priority.NORMAL,
            content=NotificationContent(
                f"Due in {i} h: ML Engineering",
                "Submit before the deadline to keep your streak. " * 5,
                "/learner",
            ),
            source_event_id=f"bench-event-{i}",
            source_event_type="lms.deadline_approaching.v1",
            created_at=base + timedelta(seconds=i),
        )
        raw = json.dumps(_to_dict(notification), separators=(",", ":"))
        pipe.set(f"edu:notif:item:{nid}", raw, ex=3600)
        pipe.zadd(timeline, {nid: int(notification.created_at.timestamp() * 1_000_000)})
        pipe.lpush(inbox, nid)  # created_at tăng dần -> mới nhất ở đầu list
    pipe.execute()
    store.expire(inbox, 3600)
    store.expire(timeline, 3600)


def cleanup(store: redis.Redis, learner: str, n: int) -> None:
    pipe = store.pipeline(transaction=False)
    for i in range(n):
        pipe.delete(f"edu:notif:item:bench-{i:03d}")
    pipe.delete(f"edu:notif:inbox:{learner}", f"edu:notif:time:{learner}")
    pipe.execute()


def measure(client: httpx.Client, learner: str, reps: int) -> tuple[float, float, float, float]:
    full_url = f"/api/learners/{learner}/notifications"
    page_url = f"/api/learners/{learner}/notifications?limit=20"
    for _ in range(5):
        client.get(full_url)
        client.get(page_url)

    full: list[float] = []
    page: list[float] = []
    for _ in range(reps):
        for url, bucket in ((full_url, full), (page_url, page)):
            started = time.perf_counter()
            response = client.get(url)
            response.raise_for_status()
            bucket.append((time.perf_counter() - started) * 1000)
    return (
        statistics.median(full), percentile(full, 0.9),
        statistics.median(page), percentile(page, 0.9),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--learner", default=LEARNER)
    parser.add_argument("--sizes", default="0,10,25,50,100,150,200")
    parser.add_argument("--reps", type=int, default=200)
    parser.add_argument("--out", type=Path, default=Path("report/data/br1_inbox_scaling.csv"))
    args = parser.parse_args()

    sizes = [int(part) for part in args.sizes.split(",") if part.strip()]
    store = redis.Redis.from_url(args.redis_url, decode_responses=True)
    inbox = f"edu:notif:inbox:{args.learner}"
    if store.llen(inbox):
        depth = store.llen(inbox)
        raise SystemExit(f"{args.learner} đang có {depth} thông báo; chọn learner trống")

    rows: list[tuple[int, str, float, float]] = []
    try:
        with httpx.Client(base_url=args.base_url, timeout=30) as client:
            for n in sizes:
                seed(store, args.learner, n)
                try:
                    full = client.get(f"/api/learners/{args.learner}/notifications").json()
                    page = client.get(
                        f"/api/learners/{args.learner}/notifications?limit=20"
                    ).json()
                    if len(full) != n or len(page) != min(20, n):
                        raise SystemExit(f"n={n}: full={len(full)} page={len(page)}, expected")
                    full_p50, full_p90, page_p50, page_p90 = measure(
                        client, args.learner, args.reps
                    )
                    rows.append((n, "full", full_p50, full_p90))
                    rows.append((n, "limit20", page_p50, page_p90))
                    print(
                        f"n={n:3d} full {full_p50:6.2f}/{full_p90:6.2f} ms  "
                        f"limit20 {page_p50:6.2f}/{page_p90:6.2f} ms"
                    )
                finally:
                    cleanup(store, args.learner, n)
    finally:
        cleanup(store, args.learner, max(sizes))
        print(f"{args.learner} inbox còn:", store.llen(inbox))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        handle.write("inbox_size,path,p50_ms,p90_ms\n")
        for n, path, p50, p90 in rows:
            handle.write(f"{n},{path},{p50:.3f},{p90:.3f}\n")
    print("wrote", args.out)

    # In tọa độ cho pgfplots (dùng p50 trong hình; p90 dùng cho câu văn)
    for path in ("full", "limit20"):
        points = [f"({n},{p50:.2f})" for n, p, p50, _ in rows if p == path]
        print(path, " ".join(points))


if __name__ == "__main__":
    main()
```

### 3.2 Chạy và kiểm tra

```bash
.venv/bin/python benchmarks/inbox_read_scaling.py \
  --reps 200 --sizes 0,10,25,50,100,150,200 \
  --out report/data/br1_inbox_scaling.csv
```

Kiểm tra:

- Output có đủ 7 mức × 2 đường; `len(full) == n`, `len(page) == min(20, n)`.
- Sau khi script xong: `edu:notif:inbox:l-004` = 0; `l-002` không đổi.
- Nếu p50 không đơn điệu do nhiễu: tăng `--reps` lên 300–500 và chạy lại; không sửa số bằng tay.
- Nếu full p50 tăng > ~8 ms từ 0 → 200 hoặc p90 > 20 ms: ghi nhận đúng số, **không** viết "tăng rất ít";
  kiểm tra stack có đang chạy việc khác không rồi đo lại.

## 4. Phase 3 — sửa báo cáo

### 4.1 Bảng BR1–BR3 (giữ nguyên một bảng)

File `report/chapters/05-danh-gia.tex`, block hiện tại khoảng dòng 113–124. **Không tách bảng.**
Giữ cấu trúc 4 hàng; BR2 giữ nguyên; BR1/BR3 để `--` cho đến khi có số mới:

```latex
\begin{table}[H]
\centering\small
\caption{Latency BR1--BR3 (ms)}\label{tab:br123-latency}
\begin{tabular}{@{}L{5.4cm}rrrrr@{}}
\toprule
\textbf{Đường đo} & \textbf{n} & \textbf{Median} & \textbf{p90} & \textbf{Nhỏ nhất} & \textbf{Lớn nhất} \\
\midrule
BR1: sự kiện $\rightarrow$ thông báo đọc được qua API & -- & -- & -- & -- & -- \\
BR2: API gợi ý có feature store & 150 & 2,2 & 4,2 & 1,4 & 12,2 \\
BR3: nộp bài $\rightarrow$ 202 & -- & -- & -- & -- & -- \\
BR3: nộp bài $\rightarrow$ \code{graded} & -- & -- & -- & -- & -- \\
\bottomrule
\end{tabular}
\end{table}
```

- Chỉ điền BR1/BR3 sau khi Phase 1 xong; dùng `n=100` nếu đủ 5 lượt × 20 mẫu.
- BR2 **không đổi** (n=150, 2,2 / 4,2 / 1,4 / 12,2).
- Không thêm bảng phụ cho BR1/BR2/BR3; biểu đồ latency nằm ở subsection mới.

### 4.2 Thêm subsection + biểu đồ

Chèn ngay sau đoạn phân tích bảng (khoảng dòng 127), trước `\subsection{BR4...}`:

```latex
\subsection{Độ nhạy của BR1 theo độ dài inbox}

Để lượng hoá chi phí đọc inbox, một thí nghiệm riêng được chạy trên cùng stack: seed $n$ thông báo
tổng hợp cho một người học thử rồi đo latency của hai đường đọc --- toàn bộ inbox và trang đầu
(\code{?limit=20}) --- với $n \in \{0, 10, 25, 50, 100, 150, 200\}$. Mỗi mức được đo lặp lại
\textbf{R} lần; Hình~\ref{fig:br1-inbox-scaling} vẽ median, còn p90 dùng cho phần nhận xét.

\begin{figure}[H]
\centering
\begin{tikzpicture}
\begin{axis}[
  width=0.82\textwidth, height=6.4cm,
  xlabel={Số thông báo trong inbox}, ylabel={Latency đọc (ms)},
  xtick={0,10,25,50,100,150,200},
  ymajorgrids,
  legend style={at={(0.5,-0.3)}, anchor=north, legend columns=2},
  legend cell align=left, mark size=2.2pt, line width=1pt,
]
\addplot[color=sone, mark=*] coordinates {
  % FULL_COORDINATES
};
\addlegendentry{Toàn bộ inbox}
\addplot[color=stwo, mark=square*] coordinates {
  % PAGE_COORDINATES
};
\addlegendentry{Trang đầu (\code{?limit=20})}
\end{axis}
\end{tikzpicture}
\caption{BR1: latency đọc inbox theo số thông báo (median; $n$ lần mỗi mức)}
\label{fig:br1-inbox-scaling}
\end{figure}

Kết quả cho thấy latency đọc toàn bộ inbox tăng gần tuyến tính theo số thông báo, nhưng tổng mức
tăng từ 0 đến 200 thông báo chỉ khoảng \textbf{X ms} (p90 dưới \textbf{Y ms}), trong khi đường đọc
trang đầu gần như không đổi. Vì inbox được giới hạn ở 200 thông báo và giao diện chỉ tải trang mới
nhất, chi phí đọc vẫn nằm trong ngưỡng phù hợp cho notification UI production; không cần thay đổi
cấu trúc lưu trữ.
```

Điền:

- `FULL_COORDINATES`, `PAGE_COORDINATES`: lấy từ dòng cuối output script (p50).
- `R`: số `--reps` đã dùng (ví dụ 200).
- `X`: `full_p50(200) - full_p50(0)`, làm tròn 0,1 ms.
- `Y`: `full_p90(200)`, làm tròn 0,1 ms.
- Nếu Δ nhỏ (≤ ~8 ms) và p90 ≤ ~20 ms, giữ câu "tăng rất ít / phù hợp production"; nếu lớn hơn,
  sửa câu theo số thật và ghi rõ giới hạn, không giữ khẳng định cũ.

### 4.3 Các chỗ phải đồng bộ

| Vị trí | Việc cần làm |
|---|---|
| `05-danh-gia.tex:110` (đoạn dẫn) | Bỏ câu "Bảng tổng hợp cả năm lượt" nếu bảng có ô `--`; mô tả BR1/BR3 đang chờ/chạy lại; không nhắc số cũ |
| `05-danh-gia.tex:127` (phân tích) | Giữ nguyên đoạn BR2 (2,2 ms, 4,2 ms, 148/150 ≤10 ms, outlier 10,5/12,2); thay toàn bộ số BR1/BR3 bằng số mới hoặc "chờ kết quả" |
| `05-danh-gia.tex:68` | Cập nhật ngày/commit của lần đo BR1–BR3 nếu đã chạy lại |
| `05-danh-gia.tex:94,98` | Cập nhật ngày/commit ở cột BR1–BR3 nếu cần; số lượt 5 × 20 giữ nguyên |
| `report/chapters/00-tom-tat.tex:10` | Bullet BR1–BR3: giữ BR2 2,2 ms; BR1/BR3 điền số mới hoặc để "chờ đo lại"; không dùng số cũ |
| `05-danh-gia.tex:329` (giới hạn) | Nếu còn nhắc "cần phân trang/scan", đổi sang mô tả hiện trạng: API có `?limit=`, attempt dùng counter; không so sánh số cũ |
| `report/main.pdf` | Rebuild sau khi sửa |

**Không** sửa các mục BR4–BR8, không đổi `tab:br123-latency` thành 3 bảng, không thêm số cũ vào
phần giới hạn.

## 5. Phase 4 — build & QA

```bash
cd report
TECTONIC_CACHE_DIR=/home/minhle/WORK/DE_261/.tectonic/cache \
  ../.tectonic/tectonic -X compile main.tex --keep-logs
cd ..

grep -c "Overfull" report/main.log
grep -nE "Undefined (reference|citation)" report/main.log
```

- `Overfull` phải = 0; undefined refs rỗng.
- Mở PDF kiểm tra: bảng BR1–BR3 còn đủ 4 hàng; BR2 đúng số; hình mới có 2 đường, nhãn trục đúng,
  không tràn lề.
- Kiểm tra chữ trong PDF có caption "độ nhạy của BR1" và không còn số BR1/BR3 cũ.

## 6. Deliverables

- `report/data/br1_inbox_scaling.csv`
- `report/chapters/05-danh-gia.tex` đã sửa (bảng một khối + subsection/biểu đồ)
- `report/main.pdf` build lại
- Log ngắn: máy, ngày, commit, `--reps`, các số p50/p90 theo n, output 5 lượt BR1/BR3.

## 7. Troubleshooting

| Hiện tượng | Xử lý |
|---|---|
| `?limit=1` trả 422/404 | container demo chưa rebuild; build lại `de261/demo:local` và recreate `demo` |
| `l-004` đang có thông báo | chọn learner trống khác (`l-005`…`l-009`) qua `--learner`; script sẽ abort nếu không trống |
| API full 200 trả < 200 | seed thiếu item/`ltrim`; kiểm tra `LLEN` và item keys; chạy lại |
| p50 không đơn điệu | tăng `--reps`, đảm bảo không có benchmark khác chạy song song; đo lại |
| Hình lệch số CSV | copy đúng tọa độ p50 từ output script, không gõ tay |
| Build LaTeX lỗi `sone`/`stwo` | các màu đã có trong preamble report; không đổi tên |

## 8. Số tham khảo trên máy đã chạy (KHÔNG dùng để điền báo cáo)

Máy WSL, Redis 7.4.11 trong Docker, API qua `localhost:8000`, payload ~681 B, 60 lần/mức:

| n | full p50/p90 | limit=20 p50/p90 |
|---|---|---|
| 10 | 4,55 / 5,31 | 5,13 / 6,11 |
| 50 | 5,90 / 6,93 | 5,34 / 7,21 |
| 100 | 7,30 / 10,83 | 5,26 / 6,32 |
| 200 | 10,32 / 12,59 | 5,42 / 6,73 |

Chỉ dùng để sanity-check: nếu máy đích cho full 200 quanh 8–15 ms và trang đầu ~5–7 ms thì hợp lý.
Mọi số trong báo cáo phải lấy từ CSV của máy đích.
