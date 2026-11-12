# Báo cáo Project (LaTeX)

Báo cáo bài tập lớn môn Kỹ thuật dữ liệu: *Nền tảng kỹ thuật dữ liệu cho hệ thống giáo dục trực tuyến quy mô lớn*.

## Biên dịch

Cần XeLaTeX (tiếng Việt, phông OpenType TeX Gyre) và BibTeX để dựng PDF.

```bash
cd report
latexmk -xelatex main.tex
# Hoặc dùng Tectonic
tectonic -X compile main.tex
```

Khi đưa lên Prism hoặc Overleaf, dùng toàn bộ nội dung thư mục này
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
chapters/                tóm tắt, thuật ngữ và nội dung sáu chương
appendices/              hướng dẫn chạy, tóm tắt API
figures/hcmut-logo.png   logo từ mẫu HCMUT, dùng ở bìa và đầu trang
figures/mockup/          ảnh chụp mockup (docs/ui-mockup)
figures/ui/              ảnh chụp giao diện thật (apps/web) với dữ liệu thật
data/                    CSV đo đạc gốc (chép từ docs/evidence)
references.bib           tài liệu tham khảo (BibTeX)
```

Biểu đồ trong Chương 5 vẽ bằng pgfplots từ số đo trong `docs/BR4_BR5_IMPLEMENTATION.md`,
`docs/BR6_BR7_BR8_IMPLEMENTATION.md` và các file CSV trong `data/`.

## Chạy BR1--BR3 ở chế độ service

```bash
docker compose -f docker-compose.yml -f docker-compose.br13.yml up -d --build
```

Chế độ `demo` vẫn là mặc định cho giao diện; overlay `br13` bật Kafka, Redis và PostgreSQL thật cho dịch vụ thông báo và dịch vụ chấm bài.
