# Minh chứng cập nhật báo cáo DE_261

Các màn hình hiện tại nằm trong `figures/current/`. Giữ hai thư mục ảnh cũ để truy vết phiên bản thiết kế. Mỗi dòng dưới đây ánh xạ ảnh cũ sang màn hình hiện tại.

| Ảnh cũ trong `figures/ui` | Ảnh cũ trong `figures/mockup` | Ảnh hiện tại | Nguồn |
| --- | --- | --- | --- |
| learner-home.jpg | learner-home.png | learner-home.png | Classroom, hồ sơ Chi |
| learner-mobile.jpg | learner-home.png | learner-mobile.png | Classroom, viewport 390 × 844 |
| code-lab.jpg | learner-lab.png | code-lab.png | Classroom, FizzBuzz đã chấm |
| assessment-health.jpg | instructor-assess.png | assessment-health.png, assessment-corrected.png | Persistent Spark/Delta qua CDC |
| advisor.jpg | advisor-risk.png | advisor.png, advisor-recovered.png | Persistent, từ cảnh báo mới đến phục hồi |
| video-insights.jpg | instructor-video.png | video-insights.png | Trino, phiên bản video Joins |
| engagement.jpg | instructor-engagement.png | engagement.png | Trino, cửa sổ tương tác |
| — | instructor-content.png | content-search.png | CDC học liệu, MinIO và OpenSearch |
| admin-acme.jpg | admin-progress.png | admin-acme.png, admin-scoped.png | Trino, báo cáo Acme và phạm vi Acme |
| admin-globex.jpg | admin-progress.png | admin-globex.png | Trino, nhóm nhỏ của Globex |
| pipeline.jpg | platform-health.png | pipeline.png | Luồng sự kiện demo của trang vận hành |
| signin.jpg | — | auth-student.png, auth-instructor.png, auth-advisor.png, auth-admin.png | Form hiện tại với ô mật khẩu trống |

Replay có một khung riêng với nhãn Simulated data. Các ảnh dùng tài khoản và dữ liệu thử nghiệm. Cặp ảnh BR4 hiện tại dùng cùng fixture tại Delta version 16 và 17. Lượt làm nóng Spark xác nhận cả hai publication qua API. Ảnh Content & Search được chụp khi Joins đã đồng bộ trong PostgreSQL, MinIO và OpenSearch. Trino đọc các mart từ bản sao fixture có mốc 17/10/2026. Kiểm tra từ phiên Admin chỉ được cấp Acme nhận 403 khi gọi báo cáo Globex. Xem `data/br45-restoration/ui-captures.json` để đối chiếu đường dẫn, chế độ và trạng thái.

## Đo đạc

- `data/br45-restoration/restoration-final-*.json` chứa từng lượt đo engine tháng 11. `summary.json` lưu trung vị, min–max, trạng thái và thông lượng. Phép đo BR4 của Spark dùng JDBC đến dữ liệu đã chuẩn hóa và ghi lại mart. Phép đo BR5 của cả hai engine dùng sink cửa sổ benchmark và bộ tính điểm chung.
- `data/br45-restoration/deployed-br4-postgres.json` và `deployed-br4-spark.json` ghi phép đo worker triển khai với fixture 24 người học. Máy đo bấm giờ sau commit của sửa điểm và poll API mỗi 250 ms. Điều kiện kết thúc là 3/24, job thành công, publication và source revision mới, cùng Delta version mới đối với Spark. Quá trình trả fixture về 2/24 nằm ngoài mẫu đo. Mỗi engine có một lượt làm nóng và năm lượt đo. `deployed-br4-postgres-overlap.json` lưu các lượt PostgreSQL bị chồng thao tác khi phục hồi Docker, ngoài bảng đối chiếu chính.
- `data/br45-restoration/source.json` và `source-checksums.txt` xác định bản mã dùng để build API. Nhật ký phép đo lưu image ID và giới hạn tài nguyên từng container. Đường Spark sử dụng MinIO và image Spark được build từ revision có cùng mã xử lý BR4. Lượt đo trên máy cá nhân chịu ảnh hưởng của tải nền.
- Hai lượt Spark đầu được lưu trước khi tiến trình đo dừng với mã 143 trong lần sửa fixture về 2/24. Phiên tiếp theo dùng cùng project, image và fixture, tiếp tục từ lượt 3. Thời điểm tiếp tục nằm trong `resumed_at_utc`.
- `data/br45-restoration/oulad_evaluation.json` và `oulad_metrics.csv` là đánh giá ngoại tuyến. Các CSV BR4/BR5 ngay dưới `data/` là phép đo lịch sử tháng 10. Giữ nguyên nguồn gốc của số đo BR6–BR8.

## Kiểm tra đường xử lý

- `native-spark.xml` ghi hai bài kiểm tra chạy trực tiếp, gồm snapshot BR4 và restart cửa sổ BR5. `compose-e2e.json` ghi luồng sửa điểm, giao lại CDC, UPDATE/DELETE và phục hồi cảnh báo trên Compose.
- `compose-v1-upgrade.json` ghi kiểm tra migration trên bản sao dữ liệu v1. `compose-publish-failure.json` ghi lỗi publish và lượt công bố lại. `published-facts.json` đối chiếu bài nộp Classroom với facts BR4.
- `cold-restore-mart-comparison.json`, `backfill-cutover.json`, `backfill-history.json` và `compose-retention.json` ghi các cổng khôi phục, dựng lại, đổi đích và bảo vệ dữ liệu còn cần.
