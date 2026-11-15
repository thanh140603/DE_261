# Phương án 1: đọc toàn bộ inbox bằng ZSET chứa JSON (bàn giao cho máy khác)

Tài liệu này là phương án thay thế sau khi **phương án 2 (Redis Hash) không đạt**.

Số dưới đây đo trên Redis thật (`redis:7.4.11`, container `de261-redis`, client chạy từ host qua
`localhost:6379`), payload 681 B, 300 lần lặp mỗi mức. Đây là **cận trên** so với app chạy trong
cùng Docker network (RTT container–container thấp hơn host → port mapping). Key test dùng prefix
`bench:` và đã được xoá sau khi đo.

## 1. Vì sao loại phương án 2 (Hash)

Prototype `fakeredis`, payload 512 B, đọc 200 item (median 300 lần):

p50 / p90 (ms):

| Cách đọc | n=10 | n=50 | n=100 | n=200 |
|---|---|---|---|---|
| Hiện tại: `LRANGE` + `MGET` | 1,11 / 1,60 | 1,87 / 2,42 | 2,70 / 3,82 | 3,40 / 4,51 |
| Hash: `HGETALL` + sort client | 0,71 / 0,99 | 1,20 / 1,58 | 1,87 / 2,46 | 2,96 / 3,93 |
| ZSET JSON: `ZREVRANGE` full | 0,73 / 0,98 | 1,09 / 1,45 | 1,48 / 2,04 | 2,66 / 3,65 |
| ZSET JSON: `ZREVRANGE 0 19` | 0,67 / 0,85 | 0,78 / 1,01 | 0,81 / 1,11 | 0,83 / 1,08 |

Đọc xong: Hash chỉ nhanh hơn hiện tại ~0,45 ms ở n=200 nhưng **không hơn ZSET JSON** (2,96 so với
2,66 ms), và có 3 nhược điểm trong thiết kế hiện tại:

1. Hash không có thứ tự → mỗi lần đọc phải parse toàn bộ rồi `sort` theo `created_at` (O(N log N)).
2. `count_since` (badge unread) phải parse toàn bộ hash, trong khi ZSET có `ZCOUNT` O(log N).
3. Cap 200 phải quét hash tìm item cũ nhất mỗi lần vượt cap; ZSET trim bằng `ZREMRANGEBYRANK`.

Vì ZSET JSON cho cùng 1 round trip, lại có sẵn thứ tự + đếm + trim, nên Hash bị loại.

Quan trọng hơn: **cả ba cách full-load đều tăng theo n**; chỉ `limit=20` là phẳng (0,67 → 0,83 ms
từ n=10 đến n=200). Nếu mục tiêu là "thời gian không đổi" thì phân trang mới giải quyết, còn đổi
schema sang Hash/ZSET JSON chỉ tiết kiệm ~0,5–0,7 ms ở n=200. Vì vậy trước khi đổi schema, hãy đo
qua HTTP API trên stack thật; nếu full-load 200 item vẫn dưới ngưỡng chấp nhận thì **giữ nguyên
`LRANGE + MGET`** và chỉ dùng `?limit=` cho UI.

## 2. Mục tiêu

- Đọc full inbox hoặc một trang chỉ **1 round trip Redis** (thay vì `LRANGE` + `MGET` = 2).
- Giữ nguyên API hiện tại (`?limit=`, `/notifications/unread?since=`).
- Không làm mất/khôi phục dữ liệu demo; có thể rollback.
- Không phá cơ chế idempotent `save()` (route + dispatch cùng gọi).

## 3. Thiết kế

### 3.1 Key layout

```
edu:notif:feed:<recipient>        ZSET  score = created_at (microsecond epoch)
                                        member = JSON projection của notification
edu:notif:item:<id>               STRING JSON đầy đủ (giữ nguyên, cho get()/dispatch)
edu:notif:event:<event_id>        SET id (giữ nguyên, cho for_source_event)
edu:notif:count                   counter toàn cục (giữ nguyên)
edu:notif:inbox:<recipient>       LIST id (chỉ dùng trong giai đoạn chuyển tiếp/rollback)
edu:notif:time:<recipient>        ZSET id (bản cũ, chỉ dùng rollback)
```

Projection JSON chứa đúng các field API trả về:

```json
{
  "id": "...", "recipient_id": "l-002",
  "dedup_key": {"recipient_id": "...", "event_type": "...", "subject_id": "..."},
  "channels": ["in_app"], "priority": "high",
  "content": {"title": "...", "body": "...", "deep_link": "..."},
  "source_event_id": "...", "source_event_type": "...",
  "created_at": "2026-11-15T00:00:00+00:00",
  "dispatched": {"in_app": "2026-11-15T00:00:01+00:00"}
}
```

`dispatched` trong feed có thể **cũ** sau khi DispatchNotification cập nhật item; API hiện không trả
field này nên chấp nhận được. `get()` vẫn đọc item nên luôn mới. Nếu sau này API trả `dispatched`,
phải chuyển sang đọc item hoặc cập nhật lại feed.

### 3.2 Ghi

Trong `save()`, nhánh `created` (SET NX thành công):

```python
feed = key("notif", "feed", notification.recipient_id)
self._client.zadd(feed, {json.dumps(_to_dict(notification)): _score(notification.created_at)})
self._client.zremrangebyrank(feed, 0, -(_INBOX_MAX + 1))   # giữ 200 mới nhất
self._client.expire(feed, _ITEM_TTL_SECONDS)
```

Nhánh update (dispatch): chỉ `SET item`, **không** đụng feed (tránh ZREM/ZADD và tránh sai thứ tự).

Lưu ý: member là JSON nên hai notification khác id nhưng trùng toàn bộ JSON sẽ bị ZSET gộp; trong
thực tế id là UUID nên không xảy ra. Nếu muốn chắc chắn, thêm `id` vào đầu chuỗi hoặc dùng member
`f"{id}\x00{json}"`.

### 3.3 Đọc

```python
def for_recipient(self, recipient_id, limit=None):
    feed = key("notif", "feed", recipient_id)
    stop = -1 if limit is None else limit - 1
    raws = self._client.zrevrange(feed, 0, stop)
    return [_from_dict(json.loads(raw)) for raw in raws]
```

- Full inbox: `limit=None` → 1 `ZREVRANGE` (toàn bộ, tối đa 200).
- Page: `limit=20` → 1 `ZREVRANGE 0 19`.
- Không cần `MGET`; thứ tự newest-first do score đảm bảo.

`count_since`:

```python
return int(self._client.zcount(feed, f"({_score(since)}", "+inf"))
```

`for_source_event` giữ nguyên (SET id + `MGET` item), vì nó không phải đường đọc inbox.

### 3.4 Backfill / migration

Chạy một lần trên mỗi recipient có dữ liệu cũ:

```python
ids = redis.lrange(f"edu:notif:inbox:{recipient}", 0, -1)
raws = redis.mget([f"edu:notif:item:{i}" for i in ids])
for raw in filter(None, raws):
    n = json.loads(raw)
    redis.zadd(feed, {json.dumps(n): int(datetime.fromisoformat(n["created_at"]).timestamp() * 1_000_000)})
redis.zremrangebyrank(feed, 0, -201)
redis.expire(feed, 30 * 24 * 3600)
```

Có thể lặp qua các recipient bằng `SCAN edu:notif:inbox:*` (không dùng `KEYS`).

### 3.5 Feature flag + cutover

Thêm `EDU_NOTIF_READ` (`list` mặc định, `feed` để bật):

- `list`: hành vi hiện tại (`LRANGE` + `MGET`), dùng để rollback.
- `feed`: đọc ZSET JSON.

Trình tự:

1. Deploy code có **dual-write** (vừa ghi list/time/item, vừa ghi feed).
2. Chạy backfill cho toàn bộ recipient.
3. So sánh số lượng/ids giữa 2 đường đọc trên vài tài khoản (`l-002`, tài khoản test).
4. Bật `EDU_NOTIF_READ=feed`, theo dõi 1–2 ngày.
5. Khi ổn: bỏ dual-write list/time, giữ item (cho `get`/dispatch) và event index.
6. Rollback: đổi flag về `list`; list/time vẫn còn trong giai đoạn chuyển tiếp.

## 4. Vì sao chọn cách này thay vì Hash

| Tiêu chí | Hash | ZSET JSON |
|---|---|---|
| Số RTT khi đọc full | 1 | 1 |
| Thứ tự newest-first | phải sort client | có sẵn |
| Unread count | parse toàn bộ | `ZCOUNT` O(log N) |
| Cap 200 | quét tìm cũ nhất | `ZREMRANGEBYRANK` |
| Update dispatch | `HSET` (nhưng feed vẫn cũ) | không đụng feed |
| Migration | đổi key, khó rollback | thêm key song song, rollback dễ |

## 5. Test cần thêm

- `save()` tạo feed đúng 1 member; save lần 2 (dispatch) không tạo member thứ hai.
- `for_recipient()` full và `limit` trả đúng thứ tự, đúng số lượng; `limit=0`, `limit>N`.
- Cap: thêm 205 item → feed còn 200, item cũ nhất bị loại khỏi feed nhưng item key còn TTL.
- `count_since` tại biên `>` (item đúng bằng mốc không tính).
- Backfill: list 100 item + feed rỗng → đọc full thấy đủ 100; chạy backfill 2 lần không nhân đôi.
- `for_source_event` vẫn hoạt động.
- Test với `FakeRedis`: cần `zadd`, `zrevrange`, `zcount`, `zremrangebyrank`, `expire` (đã có).

## 6. Đo trên máy có stack thật

### 6.1 Điều kiện

- Stack BR1/BR3 đang chạy, `EDU_BR13_MODE=service`.
- Python env của repo (`.venv`), có package `redis`.
- **Không dùng `l-002`** cho seed test nếu đang chuẩn bị quay demo; dùng recipient riêng
  `l-bench-inbox` (repo không validate recipient khi đọc Redis trực tiếp).

### 6.2 Script đo tầng Redis (chạy trên máy có Redis)

```python
import json, statistics, time
from datetime import UTC, datetime, timedelta
import redis

R = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
RECIPIENT = "l-bench-inbox"
ITEMS = "bench:item:"
INBOX = f"bench:inbox:{RECIPIENT}"
FEED = f"bench:feed:{RECIPIENT}"

def payload(i):
    return json.dumps({
        "id": f"n-{i}", "recipient_id": RECIPIENT,
        "channels": ["in_app"], "priority": "high",
        "content": {"title": f"Due {i}", "body": "x" * 300, "deep_link": "/learner"},
        "source_event_type": "lms.deadline_approaching.v1",
        "created_at": (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=i)).isoformat(),
        "dispatched": {},
    }, separators=(",", ":"))

def seed(n):
    R.delete(INBOX, FEED)
    for i in range(n):
        raw = payload(i)
        R.set(ITEMS + str(i), raw)
        R.lpush(INBOX, str(i))
        R.zadd(FEED, {raw: i})
    R.ltrim(INBOX, 0, 199)
    R.zremrangebyrank(FEED, 0, -201)

def read_list_mget():
    ids = R.lrange(INBOX, 0, -1)
    raws = R.mget([ITEMS + i for i in ids])
    return [json.loads(r) for r in raws if r]

def read_feed(limit=None):
    stop = -1 if limit is None else limit - 1
    return [json.loads(r) for r in R.zrevrange(FEED, 0, stop)]

def timeit(fn, n=200):
    fn()
    samples = []
    for _ in range(n):
        t = time.perf_counter(); fn(); samples.append((time.perf_counter() - t) * 1000)
    return statistics.median(samples), sorted(samples)[round(0.9 * (n - 1))]

for n in (10, 50, 100, 200):
    seed(n)
    full_list = timeit(read_list_mget)
    full_feed = timeit(read_feed)
    page_feed = timeit(lambda: read_feed(20))
    print(f"n={n:3d} list+MGET p50={full_list[0]:6.3f} p90={full_list[1]:6.3f} | "
          f"feed p50={full_feed[0]:6.3f} p90={full_feed[1]:6.3f} | "
          f"feed?limit=20 p50={page_feed[0]:6.3f} p90={page_feed[1]:6.3f}")

R.delete(INBOX, FEED)
```

Kỳ vọng trên Redis thật:

- `list+MGET` và `feed` chênh nhau khoảng **1 RTT** (LAN thường 0,1–0,5 ms; WSL/Docker Desktop có thể cao hơn).
- `feed?limit=20` gần như không đổi từ n=10 đến n=200.
- Nếu `feed` không nhanh hơn đáng kể (< 0,5 ms) hoặc p90 tệ hơn, **không đáng đổi schema** — giữ
  `MGET` hiện tại và chỉ dùng `?limit=` cho UI.

### 6.3 Đo qua HTTP API (sau khi bật `feed`)

```bash
# seed bằng script trên với recipient l-002 nếu chấp nhận dữ liệu test, hoặc dùng endpoint test
for q in "" "?limit=20"; do
  for i in 1 2 3 4 5; do
    curl -s -o /dev/null -w "%{time_total}\n" "localhost:8000/api/learners/l-002/notifications$q"
  done
done
```

Ghi lại p50/p90, so với baseline trước khi đổi. Tiêu chí chấp nhận đề xuất:

- full 200 item: p50 ≤ 5 ms (LAN), p90 ≤ 10 ms;
- `?limit=20`: p50 ≤ 3 ms và không tăng quá 1 ms so với n=10;
- không sai thứ tự, không mất item, unread count khớp.

## 7. Rủi ro / lưu ý

- **Nhân đôi dữ liệu**: mỗi notification nằm ở item + feed (≈ 2× dung lượng Redis) cho đến khi bỏ
  list/time. Chấp nhận được với cap 200/user.
- **Member ZSET lớn**: 200 × ~800 B ≈ 160 KB/recipient; ZSET operations vẫn ổn.
- **JSON trùng**: thêm tiền tố id vào member nếu muốn tuyệt đối không gộp.
- **Stale `dispatched`** trong feed: API hiện không trả; nếu tương lai trả thì phải cập nhật feed.
- **Migration chậm**: chạy `SCAN` theo batch, không `KEYS`; đo thời gian trên copy Redis trước.
- **Rollback**: giữ `EDU_NOTIF_READ=list` và list/time đến khi feed ổn định.

## 8. File dự kiến sửa (khi triển khai)

- `src/edu_platform/contexts/notification/infrastructure/redis_notification_repository.py`
  - thêm `_feed_key`, `_score` (đã có), `save()` dual-write, `for_recipient`, `count_since`.
- `src/edu_platform/platform/config.py`: thêm `EDU_NOTIF_READ` (nếu dùng flag).
- `tests/unit/contexts/test_redis_adapters.py`: test feed/backfill/cap.
- `docs/api.md`: không đổi contract.
- `benchmarks/` (tuỳ chọn): script đo như mục 6.

## 9. Kết luận

- Phương án 2 (Hash) bị loại vì không có thứ tự/đếm/trim, không nhanh hơn ZSET JSON.
- Phương án 1 (ZSET JSON) là cách “load hết inbox trong 1 lần” gọn nhất: 1 `ZREVRANGE`, giữ nguyên
  `?limit`, `ZCOUNT` cho unread, rollback được.
- Đo thật cho thấy lợi ích của việc đổi schema chỉ ~0,5–0,7 ms ở 200 item; lợi ích lớn nằm ở
  `?limit=20` (phẳng ~0,8 ms). Vì vậy khuyến nghị mặc định: **không đổi schema**, giữ
  `LRANGE + MGET`, dùng `?limit=` cho UI. Chỉ triển khai phương án 1 nếu đo qua HTTP API cho thấy
  full-load vượt ngưỡng (ví dụ p90 > 10 ms) trên máy đích.
