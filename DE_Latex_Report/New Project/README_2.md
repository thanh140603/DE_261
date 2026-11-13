# Báo cáo DE_261 (LaTeX)

Báo cáo bài tập lớn môn Kỹ thuật dữ liệu: *Nền tảng kỹ thuật dữ liệu cho hệ thống giáo dục trực tuyến quy mô lớn*.

## Biên dịch

Cần XeLaTeX (tiếng Việt, phông OpenType TeX Gyre) và BibTeX để dựng PDF.

```bash
cd "DE_Latex_Report/New Project"
latexmk -xelatex main.tex
# Hoặc dùng Tectonic với đủ lượt để cập nhật mục lục và tài liệu tham khảo
tectonic --reruns 4 main.tex
```

Khi đưa lên Prism hoặc Overleaf, dùng toàn bộ nội dung thư mục `DE_Latex_Report/New Project/`
với `main.tex` làm tệp chính. Giữ nguyên cấu trúc thư mục để LaTeX tìm được
logo, hình, dữ liệu biểu đồ và tài liệu tham khảo. Trên Overleaf, chọn
**Menu → Compiler → XeLaTeX**.

## Cần điền trước khi nộp

Điền lớp, nhóm, họ tên, MSHV và phần việc của từng thành viên trong
`config/info.tex`.

## Cấu trúc

```
main.tex                 tệp chính
config/info.tex          thông tin trang bìa (sửa ở đây)
config/preamble.tex      gói, phông, màu, kiểu tiêu đề, bảng, biểu đồ
config/cover.tex         trang bìa theo mẫu HCMUT
chapters/                tóm tắt, thuật ngữ và nội dung sáu mục chính
appendices/              hướng dẫn chạy, tóm tắt API
figures/hcmut-logo.png   logo từ mẫu HCMUT, dùng ở bìa và đầu trang
figures/mockup/          ảnh chụp mockup (docs/ui-mockup)
figures/ui/              ảnh giao diện trước khi cập nhật
figures/current/         ảnh Playwright của ứng dụng hiện tại
EVIDENCE.md              ánh xạ ảnh cũ, ảnh mới và nguồn số đo
data/                    CSV đo đạc gốc (chép từ docs/evidence)
references.bib           tài liệu tham khảo (BibTeX)
```

Mục 5 dùng nhật ký BR4/BR5 tháng 11, phép đo worker triển khai và đánh giá OULAD trong `data/br45-restoration/`. Các CSV BR4/BR5 tháng 10 và BR6–BR8 được giữ làm bằng chứng theo từng đợt.

## Tái lập phép đo BR4 từ commit nguồn đến API

Dùng một Docker Compose project riêng cho mỗi engine. Lấy
`infra/br45/compose.verify.yml` ở gốc repo làm cấu hình cô lập. Chạy lần lượt
với `EDU_BR45_ASSESSMENT_ENGINE=postgres` và `spark`. Khi chạy hai project
cùng lúc, cấp các cổng host khác nhau cho từng project. Giữ cấu hình CDC,
giới hạn tài nguyên và mốc UTC giống nhau. Giữ URL MinIO của đường Spark và
volume checkpoint riêng theo project. Cấp Instructor Bearer token có quyền
trên `c-py-201` qua `EDU_BR45_AUTH`, rồi lưu token vào tệp JSON riêng có
khóa `token`. Cấu hình `EDU_BR45_CLOCK_MODE=manual` trước khi khởi động.

Sau khi Compose báo dịch vụ sẵn sàng, chạy trong container `br45-cdc` của
project tương ứng:

```bash
python -m edu_platform.br45.cli seed --students 24 --at 2026-11-12T16:00:00Z
python -m edu_platform.br45.cli diagnostics --connect-url http://connect:8083
```

Từ thư mục chứa `main.tex`, chạy với Python đã cài `httpx` và `psycopg`:

```bash
python data/measure_deployed_br4.py \
  --engine "$BR4_ENGINE" --project "$BR4_PROJECT" \
  --api "$BR4_API" --dsn "$BR4_FIXTURE_DSN" \
  --token-file "$BR4_TOKEN_FILE" --source-manifest "$BR4_SOURCE_MANIFEST" \
  --output "data/br45-restoration/deployed-br4-$BR4_ENGINE-rerun.json"
```

`BR4_SOURCE_MANIFEST` là JSON định danh mã đã build cho lượt tái lập. Mẫu
nằm trong `data/br45-restoration/source.json`. Nếu API dùng tên container
riêng, truyền `--api-container`. Script thay đổi điểm trong cơ sở dữ liệu
fixture, ghi từng lượt vào nhật ký và trả fixture về 2/24 sau khi đo.
Nếu tiến trình đo dừng giữa chừng, dùng lại cùng lệnh với `--resume` để
giữ các lượt đã ghi. Tham số này kiểm tra project, mã nguồn và image ID
trước khi tiếp tục.
