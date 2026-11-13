# So sánh engine cho BR4 và BR5

| Yêu cầu | Cùng chặng xử lý | Đầu cuối |
| --- | --- | --- |
| BR4 | PostgreSQL SQL và Spark SQL batch đọc snapshot kết quả chấm đã làm sạch, tính theo câu hỏi và test case rồi commit vào cùng cấu trúc mart PostgreSQL. Spark lấy dữ liệu bằng JDBC. | Một lần sửa điểm được commit ở PostgreSQL nguồn, đi qua Debezium và Kafka đến bảng clean. Bộ chạy kích hoạt một lần refresh bằng engine đang đo. Kết thúc khi API Instructor đọc được tỷ lệ mới từ mart. |
| BR5 | Spark Structured Streaming và Flink đọc cùng kiểu luồng Kafka. Bắt đầu khi bộ chạy gửi lô sự kiện, kết thúc khi hai cửa sổ 7 ngày có số đếm đúng trên PostgreSQL và engine xác nhận đã đọc hết lô. | Commit hoạt động học vào PostgreSQL nguồn. Debezium và bộ chuẩn hóa đưa sự kiện vào Kafka. Bộ chạy đọc cửa sổ đã ghi và gọi cùng bộ chấm điểm rủi ro cho hai engine. Kết thúc khi API Advisor trả về điểm và trạng thái cảnh báo mong đợi. |

BR4 sửa một kết quả chấm trên bộ dữ liệu 27 học viên có 106 dòng chấm. Câu hỏi chuyển từ 2/24 lên 3/24. BR5 mở cảnh báo sau bốn hoạt động ở tuần trước và một bài bắt buộc đã quá hạn. Thêm bốn hoạt động ở tuần gần nhất làm điểm giảm từ 100 xuống 50 và chuyển cùng cảnh báo sang `RESOLVED`.

Mỗi quy mô có một lượt làm nóng và ba lượt đo ở 1.000, 10.000 và 100.000 dòng chấm hoặc sự kiện duy nhất. Mỗi kịch bản đầu cuối có năm lượt đo. BR5 gửi thêm bản trùng và các tick trọng số bằng 0. Thông lượng dùng số sự kiện duy nhất theo quy mô công bố. Cả hai bảng ghi trung vị và min–max của các lượt `PASS`. Các lượt lỗi, hết giờ và chưa chạy có trạng thái riêng.

Phép tính Python độc lập kiểm tra số đếm và mẫu số BR4, bao gồm bài làm lại, thiếu kết quả và sửa điểm. BR5 kiểm tra sự kiện trùng, đến lệch thứ tự, biên cửa sổ nửa mở và đính chính bằng delta âm. Kiểm tra sau khi khởi động lại gửi lại một ID cũ cùng một ID mới để xác minh cả tổng cửa sổ lẫn trạng thái loại trùng.

Spark Streaming đặt nhịp micro-batch 5 giây, tối đa 50.000 Kafka offsets mỗi lần. Flink đặt nhịp phát cửa sổ 5 giây, flush JDBC tối đa 1 giây khi có dữ liệu và checkpoint 10 giây. Với Flink, phép đo chờ Kafka offsets đã commit sau checkpoint. Poll kết quả và API theo nhịp 250 ms. Hai cửa sổ được kiểm tra ở cùng mốc UTC theo giờ, với độ trễ sự kiện cho phép 21 ngày.

## Chạy lại

Chạy tại thư mục gốc với Python trong `.venv`, Docker Compose, Kafka và Connect của stack. Bước chuẩn bị build image từ checkout hiện tại và có thể dùng cache của Docker. Bước chuẩn bị lấy các JAR cố định từ bộ nhớ đệm hoặc Maven Central và biên dịch job Flink trong container. Cơ sở dữ liệu benchmark ở cổng 15434, API đo ở cổng 18001. Mỗi lượt BR5 có Kafka topic, Kafka group hoặc offset log và checkpoint riêng.

```bash
bash infra/br45/run-engine-benchmark.sh prepare
run=$(date -u +%Y%m%d-%H%M%S)
bash infra/br45/run-engine-benchmark.sh br4 "$run"
bash infra/br45/run-engine-benchmark.sh spark "$run"
bash infra/br45/run-engine-benchmark.sh flink "$run"

archive="docs/evidence/br45-v2/engine-comparison/$run"
mkdir -p "$archive"
cp data/br45-engine-benchmark/runs/"$run"-br4-{postgres,spark}.json "$archive/"
cp data/br45-engine-benchmark/runs/"$run"-br5-{spark,flink}.json "$archive/"
{
  uname -srmo
  lscpu | sed -n '/^CPU(s):/p; /^Model name:/p'
  docker image inspect postgres:16 de261/demo:local de261/spark:local \
    flink:1.19-scala_2.12-java11 confluentinc/cp-kafka:7.6.1 debezium/connect:2.6 \
    --format '{{join .RepoTags ", "}} {{.Id}}'
} > "$archive/host.txt"
.venv/bin/python -m edu_platform.br45.engine_comparison \
  --output docs/evidence/br45/engine_comparison.json \
  "$archive/"*.json
```

Chạy các lệnh theo thứ tự. Mỗi engine có giới hạn 2 CPU và 2 GiB cho container xử lý. PostgreSQL benchmark có cùng giới hạn và làm đích ghi cho cả bốn engine. Kafka và Connect dùng chung tiến trình với stack lớp học, còn topic, connector, replication slot và database benchmark được tách riêng. Có thể dùng `--sizes 1000 --repeats 1 --e2e-repeats 1` để kiểm tra nhanh. Dùng run ID mới khi đo lại.

Lưu các journal theo run ID cùng cấu hình máy và image ID. Nếu container dừng giữa chừng, kiểm tra log và trạng thái `OOMKilled` trong thư mục `data/br45-engine-benchmark/runs`. Dừng các dịch vụ benchmark sau khi lưu số đo.

```bash
curl -fsS -X PUT http://127.0.0.1:8083/connectors/br45-engine-benchmark/pause
docker compose -f docker-compose.yml -f docker-compose.br45-benchmark.yml \
  stop br45-bench-api br45-bench-cdc br45-bench-postgres
```

## Xem trên lớp học

Mở [lớp học cổng 8000](http://127.0.0.1:8000), vào **Instructor → Assessment health** hoặc **Advisor → Learners to support**, rồi cuộn xuống **Measured benchmarks**. Hai bảng đầu dùng kết quả đối chiếu engine. **Python reference baseline** lưu số liệu theo giao thức trước đó.

Khi cập nhật JSON số đo, khởi động lại dịch vụ web để tải dữ liệu mới. Nếu đổi frontend, biên dịch tài nguyên web trước. Compose dùng lại image đang chạy.

```bash
(cd apps/web && npm run build)  # khi có thay đổi frontend
docker compose -f docker-compose.yml -f docker-compose.br45-classroom.yml restart demo
```

Kết quả phản ánh cấu hình trên một máy và nhịp ghi, checkpoint đã chọn. Phép đo BR4 bao gồm chi phí JDBC và khởi chạy tác vụ Spark sau warmup. Phép đo BR5 bao gồm chi phí Kafka, chờ lưu cửa sổ và chờ xác nhận offsets.

Đợt đo lịch sử ngày 9 tháng 11 năm 2026 có [số liệu hiển thị trên web](evidence/br45/engine_comparison.json) và [journal cùng cấu hình máy](evidence/br45-v2/engine-comparison/).


Đợt chạy khôi phục trên revision `3cfd70d` đạt 36 lượt đo và 30 lượt đầu cuối. Spark và Flink đều đạt kiểm tra khởi động lại. [Bảng tổng hợp mới](evidence/br45-restoration/engine-comparison/summary.json), [journal từng lượt](evidence/br45-restoration/engine-comparison/) và [cấu hình máy, image ID](evidence/br45-restoration/compose-build.json).
