# Kế hoạch slide thuyết trình kỹ thuật (theo cấu trúc báo cáo)

Bài trình bày kỹ thuật, bám cấu trúc báo cáo. Không kể chuyện; mỗi slide là một vấn đề kỹ thuật kèm hình/bảng/công thức/số đo. Mỗi nhóm BR có **2 slide: thiết kế → kết quả đo**, rồi demo ngay sau đó.

## 0. Ngân sách thời gian

| Phần | Thời lượng |
|---|---|
| Trước BR (chương 1–3: bài toán, kiến trúc, lakehouse) | 3 phút |
| BR1–BR3: thiết kế + kết quả đo + demo | 5–7,5 phút |
| BR4–BR5: thiết kế + kết quả đo + demo | 5–7,5 phút |
| BR6–BR8: thiết kế + kết quả đo + demo | 5–7,5 phút |
| Sau BR (test, CDC benchmark, hạn chế, kết luận) | 2 phút |
| **Tổng** | **20–27,5 phút** |

- **Mục tiêu 23 phút:** trước/sau 5 phút; mỗi nhóm 6 phút = 1 phút thiết kế + 1 phút kết quả đo + 4 phút demo.
- **Tối thiểu 20 phút:** mỗi nhóm 5 phút = 2 phút slide + 3 phút demo.
- **Tối đa 27,5 phút:** mỗi nhóm 7,5 phút = 2 phút slide + 5,5 phút demo.
- Nếu chỉ có 10 phút trên lớp: dùng 6 slide, bỏ demo live; không nằm trong plan này.

**Phạm vi demo:** chỉ demo ba nhóm BR. Bài toán, kiến trúc, lakehouse, test và benchmark chỉ trình bày bằng slide/số liệu; **không demo `edu warehouse run`, Trino hay warehouse build**. Warehouse build chỉ nêu trên slide 3 (43 model, 121–130 giây, 10 quality gate) và để backup/CSV cho Q&A.

## 1. Timeline mục tiêu 23 phút

| Thời gian | Nội dung | Slide |
|---|---|---|
| 0:00–1:00 | Bài toán, 4 nguồn, 8 BR, NFR | 1 |
| 1:00–2:00 | Kiến trúc 6 tầng, tech stack, ADR | 2 |
| 2:00–3:00 | Lakehouse, gold star schema, quality gate | 3 |
| 3:00–4:00 | BR1–BR3: thiết kế | 4 |
| 4:00–5:00 | **BR1–BR3: kết quả đo** | 5 |
| 5:00–9:00 | **Demo A: BR1, BR2, BR3** | — |
| 9:00–10:00 | BR4–BR5: thiết kế | 6 |
| 10:00–11:00 | **BR4–BR5: kết quả đo** | 7 |
| 11:00–15:00 | **Demo B: BR4, BR5** | — |
| 15:00–16:00 | BR6–BR8: thiết kế | 8 |
| 16:00–17:00 | **BR6–BR8: kết quả đo** | 9 |
| 17:00–21:00 | **Demo C: BR6, BR7, BR8** | — |
| 21:00–21:45 | Test strategy | 10 |
| 21:45–22:15 | CDC benchmark | 11 |
| 22:15–23:00 | Hạn chế, hướng phát triển, kết luận | 12 |

## 2. Chi tiết slide

### Slide 1 — Bài toán, nguồn dữ liệu, 8 BR (1 phút)

- Bảng 4 nguồn: telemetry (JSON xAPI), CDC (WAL), object storage (học liệu), sandbox log.
- Cột thách thức: late/out-of-order, duplicate, schema version, PII, clock skew, log không đồng nhất.
- 4 nhóm người dùng; 8 BR viết gọn một dòng mỗi BR.
- NFR định lượng: BR2 <10 ms; BR1/BR3 tính bằng giây; BR5 ~10 giây; BR8 ~500 ms; BR6/BR7 theo ngày + overlay.
- Artifact: bảng 1.2 và 1.3 rút gọn.

### Slide 2 — Kiến trúc, tech stack, ADR (1 phút)

- Hình 2.1; trace một event: client → Kafka → bronze → silver → gold → mart → Trino/Redis → API → React.
- Ba nguyên tắc: Kafka là biên giới bounded context; Spark là writer duy nhất của Delta; lakehouse là source of truth.
- Stack: Kafka, Debezium (pgoutput), Spark 3.5 + Structured Streaming, Delta 3.3, HMS 3.1.3, Trino, Redis, PostgreSQL 16, OpenSearch 2.17, Airflow, FastAPI/React.
- Ba điều chỉnh so với kiến trúc tham chiếu: Spark thay Flink (ADR 0009/0014); Trino + HMS (0010); feature store hai nhánh.
- Artifact: hình 2.1 + 3 dòng ADR.

### Slide 3 — Lakehouse, gold, quality gate (1 phút)

- Hình 3.1: bronze 4 / silver 20 / gold 9 + 11 / mart 4 / features 1 / ops 2; tổng 51 bảng, 44 model.
- Contract: append-only + PII ở bronze; typed, dedup, pseudonym, CDF ở silver; star schema ở gold; policy ở mart.
- Gold: SCD2 cho `dim_learner`/`dim_content`; surrogate key `xxhash64`; inferred member; key `-1`.
- 10 quality gate; `silver_no_raw_identifiers`, `mart_org_progress_k_anonymity`; time travel trong VACUUM 7 ngày.
- Warehouse build: 43 model, 121–130 giây, 10 gate (chỉ nêu số, không demo).
- Artifact: hình 3.1 + 4 số: 51 bảng, 44 model, 10 gate, 121–130 giây.

### Slide 4 — BR1–BR3: thiết kế (1 phút)

- BR1: 5 topic → rule YAML → audience resolver PostgreSQL → Redis/inbox/SSE; dedup 24h, rate limit 5/giờ; priority high bypass.
- BR2: batch 30 ngày (TTL 36h) + session 30 phút (`SET NX` 1h, TTL 2h); ranking tier 1,00/0,75/0,50/0,00.
- BR3: `POST /api/submissions` → 202 sau `publisher.flush()`; `queued→running→graded`; sandbox Python 3 giây, SQL SQLite read-only; `FeedbackPolicy` 8 dòng stderr.
- Artifact: 3 pipeline ngang + bảng tham số.

### Slide 5 — BR1–BR3: kết quả đo (1 phút)

- Bảng latency: BR1 n=100, median 12,4, p90 14,5, min 8,3, max 60,9; BR2 n=150, 2,2/4,2/1,4/12,2; BR3 ack 100, 14,2/17,4/12,2/25,5; BR3 graded 100, 71,0/77,3/65,4/90,2.
- 148/150 request BR2 dưới 10 ms; 5 lượt ổn định: 12,1–13,6; 1,8–4,1; 13,7–14,4; 70–72 ms.
- Điều kiện đo: 26/30 container; xoá inbox và trạng thái chấm trước mỗi mẫu.
- Test liên quan: 1 integration BR1/BR3, 2 Playwright BR1–BR3.
- Artifact: bảng 5.5 + một strip/box plot nếu có.

### Demo A — BR1–BR3

**Mục tiêu 4 phút; tối thiểu 3 phút; tối đa 5,5 phút.**

| Thời lượng mục tiêu | Thao tác | Kết quả phải thấy |
|---|---|---|
| 1:00 | Gửi `lms.deadline_approaching.v1` cho `l-002` | 1 notification trong inbox |
| 0:30 | Replay cùng event | `duplicate`; `notif:count` không tăng |
| 1:00 | Mở learner dashboard; thêm 2 event | chip “Live session”, “% recent pass”; session 5→7 |
| 1:30 | Nộp FizzBuzz; replay queue/raw result | 202 → graded; feedback diff; không có grade thứ hai |

- 3 phút: bỏ replay BR1, gộp BR2 vào lúc mở dashboard.
- 5,5 phút: thêm Redis key (`notif:dedup`, `notif:count`), PostgreSQL `grading.*`, SSE event.

### Slide 6 — BR4–BR5: thiết kế (1 phút)

- Debezium → `br45.cdc.br45.*` → `raw_changes` → contract/quarantine → `clean_rows` → outbox → `br45.clean.v2`; LSN chỉ MERGE khi mới hơn.
- BR4: `pass_rate = passes / valid evaluations`; job 30 ngày, mart 28 ngày; rule 20 người, 30%/20%, lệch 50 điểm, giảm 30 điểm; job bất đồng bộ Spark SQL → `publish()`.
- BR5: `window(event_time, '7 days', slide 1h)`, watermark 21 ngày; feature 35/30/20/15; eligible 7 ngày/14 ngày; alert 60, cooldown 72h.
- Artifact: hình 4.2 + công thức + bảng threshold.

### Slide 7 — BR4–BR5: kết quả đo (1 phút)

- BR4: SQL 27,96 / 266,68 / 2.765,54 ms; Python 13,36 / 119,23 / 1.531,00 ms; 100k một lần Python 1,79 giây; sửa một lần ~2,9 giây; truy vấn mart 0,68–0,76 ms.
- BR5: 6.161 / 4.843 / 14.707 ms cho 1k/10k/100k; throughput 170 / 2.088 / 6.800 sự kiện/s; batch Python 1,8 / 18,4 / 150,2 ms.
- Alert end-to-end: ~10.164 ms; restart + phục hồi ~20.142 ms, không alert trùng.
- Điều kiện: Spark 3.5.5 `local[2]`, 2 CPU/2.304 MiB, state store RocksDB; PostgreSQL là engine đối chứng.
- Test liên quan: 21 integration BR4/5, 2 Spark test.
- Artifact: hình 5.1 + bảng 5.6 + một dòng “alert 10,2 giây”.

### Demo B — BR4–BR5

**Mục tiêu 4 phút; tối thiểu 3 phút; tối đa 5,5 phút.**

| Thời lượng mục tiêu | Thao tác | Kết quả phải thấy |
|---|---|---|
| 2:00 | Assessment health 24 người, câu hỏi 8,33%; sửa 1 grade trong PostgreSQL | UI 8% → 13% không reload; mở `assessment_jobs`/mart |
| 2:00 | Advisor queue 100 điểm; thêm 4 activity | 35+30+20+15; điểm 50; alert resolve; risk history |

- 3 phút: mỗi BR 1,5 phút, bỏ phần mở bảng job.
- 5,5 phút: thêm LSN cũ không ghi đè, replay CDC, outbox, alert transition.

### Slide 8 — BR6–BR8: thiết kế (1 phút)

- BR6: `completion_rate = mean(lessons_completed/lessons_total)`; `avg_mastery = mean(avg pass rate, 0 nếu chưa chấm)`; k=5 ba lớp.
- BR7: `dim_content` SCD2; `fct_video_second_activity` grain version × second × day; `mart.video_heatmap` 28 ngày, distinct learners, clamp giây cuối; overlay 5 phút.
- BR8: `SyncContentChange` theo version đã index; Redis cache invalidation; OpenSearch BM25 + HNSW; RRF k=60; hash embedder sau port `Embedder`.
- Engagement: trọng số 1,0/1,0/2,0/1,5; 4 tuần; giảm khi `a>0, b≤0,7a, c≤0,7b`.
- Artifact: 3 sơ đồ nhỏ + công thức.

### Slide 9 — BR6–BR8: kết quả đo (1 phút)

- Serving: BR6 110,6 ms → 2,6 ms; BR7 172,4 → 6,0; BR8 81,0 → 3,9; p90 Trino 220/218/111, cache 3,4/7,4/5,5.
- BR8 sync: median 501 ms, p90 541, max 552; API nhận 31,6 ms; service 40–85 ms.
- Overlay: 5,71 / 5,95 / 6,13 giây ở 25/100/400 session; tải tăng 15 lần, latency gần như phẳng.
- Warehouse build: 121,6 / 126,5 / 123,6 giây cho 35/70/140 ngày; 43 model; mart 1,3–2,3 giây.
- Test liên quan: 11 Spark test, 12 Playwright, 4 browser test BR6–BR8.
- Artifact: hình 5.2 + bảng 5.7 + hình 5.5 (build).

### Demo C — BR6–BR8

**Mục tiêu 4 phút; tối thiểu 3 phút; tối đa 5,5 phút.**

| Thời lượng mục tiêu | Thao tác | Kết quả phải thấy |
|---|---|---|
| 1:00 | Acme → Globex; export CSV; org ngoài phạm vi | Acme có tỷ lệ; Globex “Fewer than 5”; 403 |
| 1:00 | Video “Joins” v1/v2; bật overlay | Hai heatmap: 420s và 390s; overlay hôm nay |
| 2:00 | Publish transcript mới; tìm chuỗi đánh dấu; engagement trend | cache miss → searchable; 4 tuần, flag giảm |

- 3 phút: mỗi BR 1 phút, bỏ export CSV và overlay.
- 5,5 phút: thêm sync policy stale/duplicate, RRF score, Redis cache key, version SCD2.

### Slide 10 — Test strategy (45 giây)

- Bảng tầng: 379 unit, 11 Spark, 21 integration BR4/5, 1 integration BR1/3, 1+6 e2e, 12 browser.
- 10 quality gate sau mỗi lần build; `ruff` + `mypy`; test kiến trúc kiểm tra ranh giới lớp.
- Nói rõ: số đếm trên mã đã gộp BR4/5; tầng unit chạy lại, các tầng khác giữ số hiện có.
- Artifact: bảng 5.1 rút gọn.

### Slide 11 — CDC benchmark (30 giây)

- 100.000 dòng; Debezium 110 event (100 UPDATE + 10 DELETE) vs polling 100 event (0 DELETE).
- p50 485,9 vs 14,4 ms; query bảng nguồn 0 vs 16; tuple 0 vs 4.061.
- Kết luận: polling nhanh hơn trong mẫu này nhưng sai dữ liệu; Debezium đúng hơn, không phải nhanh hơn.
- Giới hạn: một đợt thay đổi, một máy, chưa failure injection.
- Artifact: bảng 5.9.

### Slide 12 — Hạn chế, hướng phát triển, kết luận (45 giây)

- 4 hạn chế chính: single node/bảo mật cục bộ; synthetic data/không nhãn thật; hash embedding; streaming latency giây; BR4 chưa incremental.
- Hướng: Flink 2.x, sentence embedding, real labels, MERGE CDF, multi-node + TLS.
- Kết luận: event time + idempotent + quality gate là điều kiện để 8 BR dùng chung một lakehouse.

## 3. Phân vai

| Thành viên | Phụ trách | Thời lượng mục tiêu |
|---|---|---|
| A | Slide 1–3 (bài toán, kiến trúc, lakehouse) + slide 10–12 | 3 + 2 phút |
| B | Slide 4–5 + Demo A (BR1–BR3) | 6 phút |
| C | Slide 6–7 + Demo B (BR4–BR5) | 6 phút |
| D | Slide 8–9 + Demo C (BR6–BR8) | 6 phút |

Tổng 23 phút. Người trình bày nhóm BR nào tự demo nhóm đó; người A giữ nhịp và chuyển slide.

## 4. Chuẩn bị demo

- Stack chạy sẵn: `docker compose -f docker-compose.yml -f docker-compose.br13.yml up -d` + profile `br45`, `br678`.
- Mở trước 3 tab: learner, instructor, advisor; một terminal; một tab API docs.
- Chuẩn bị sẵn lệnh replay BR1, update grade BR4, thêm activity BR5; không gõ live.
- Quay clip dự phòng 4 phút/nhóm; nếu live lỗi, chuyển clip và nói “phần này đã được ghi lại”.
- Không đưa `edu warehouse run`, Trino hay dashboard pipeline vào demo; nếu bị hỏi, mở backup slide có số build (43 model, 121–130 giây, 10 gate) và CSV `report/data/mart_build.csv`.
- Che token/PII trên màn hình; dùng dữ liệu seed.

## 5. Nguyên tắc slide kỹ thuật

- Mỗi slide một câu hỏi kỹ thuật; tiêu đề là câu trả lời ngắn.
- Bắt buộc có artifact: hình, bảng schema, công thức, threshold hoặc số đo.
- Số liệu ghi đơn vị và nguồn ở chân slide (`report/data/...`).
- Bảng tối đa 5 cột; bảng gốc để backup.
- Hình TikZ xuất PDF/PNG, phóng to; không dán nguyên trang báo cáo.
- Màu `#0277BD`, `#0D1B2A`, `#F4F7FA`; body ≥20 pt; tối đa 6 dòng bullet.

## 6. Câu hỏi kỹ thuật và trả lời gợi ý

1. **Vì sao Spark thay Flink?** ADR 0009/0014; Spark đã chạy landing; một engine; latency 6–10 giây đủ; Flink mới là skeleton + benchmark riêng.
2. **Exactly-once ở đâu?** Checkpoint + Delta transactional sink; MERGE theo business key; Redis ghi tuyệt đối; replay không tạo grade/alert trùng.
3. **Late data xử lý thế nào?** Watermark 5 phút/10 giây/21 ngày; late data vẫn lưu và gắn cờ; `late_data` kéo window; bronze replay.
4. **CDC giữ thứ tự ra sao?** LSN; chỉ MERGE khi mới hơn; soft delete; outbox trong cùng transaction.
5. **Vì sao k=5?** `MinCohortPolicy`; ba lớp bảo vệ; UI/CSV chỉ hiện “Fewer than 5”.
6. **Polling nhanh hơn sao vẫn Debezium?** Negative control; polling mất DELETE, bỏ UPDATE trung gian, không state; Debezium đúng nghĩa dữ liệu.
7. **Scale?** Chưa chứng minh; một máy 8 GB; đã đo 100k dòng/100k lượt chấm/40k event; hướng partition/topic + multi-node.
8. **Vì sao hash embedding?** Không cần GPU/model; port `Embedder`; thay sentence-embedding chỉ cần adapter + reindex.
9. **Bảo mật?** Argon2id, HttpOnly, 8h, scope; nhưng tài khoản tĩnh, một nút, OpenSearch tắt security.
10. **Số test?** 379 unit tại thời điểm đếm trên mã đã gộp; 11 Spark, 21 integration BR4/5, 1 integration BR1/3, 1+6 e2e, 12 browser; nói rõ tầng nào chạy lại.
11. **Khác data lake?** Catalog HMS, Trino, star schema, gate, phân quyền schema, time travel, CDF.
12. **Nếu có thêm thời gian?** Flink 2.x, nhãn dropout thật, sentence embedding, incremental BR4, multi-node TLS.

## 7. Checklist

- [ ] 12 slide, 3 demo slot; tổng mục tiêu 23 phút, trần 27,5 phút.
- [ ] Mỗi nhóm BR có đủ 2 slide: thiết kế + kết quả đo, rồi demo.
- [ ] Không demo lakehouse/warehouse build.
- [ ] Demo chạy thử 2 lần; có clip dự phòng.
- [ ] Backup: 16 ADR, bảng 51/44, test breakdown, CDC benchmark, deployment.
- [ ] Xuất PDF 16:9; kiểm tra font tiếng Việt.
- [ ] Đặt tên file theo mã nhóm.
