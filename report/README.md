# Báo cáo DE_261 (LaTeX)

Báo cáo bài tập lớn môn Kỹ thuật dữ liệu: *Nền tảng kỹ thuật dữ liệu cho hệ thống giáo dục trực tuyến quy mô lớn*.

## Biên dịch

Cần XeLaTeX (tiếng Việt, phông OpenType TeX Gyre).

```bash
cd report
tectonic main.tex              # đã thử với Tectonic 0.15
# hoặc
latexmk -xelatex main.tex
```

Overleaf: tải cả thư mục `report/` lên, chọn **Menu → Compiler → XeLaTeX**.

## Cần điền trước khi nộp

- `config/info.tex`: mã môn, lớp, nhóm, giảng viên, họ tên, MSHV và phần việc của từng thành viên.
- Logo trường: đặt file `figures/hcmut-logo.png` (hoặc `.pdf`); trang bìa tự dùng nếu có, không thì hiện ô giữ chỗ.

## Cấu trúc

```
main.tex                 tệp chính
config/info.tex          thông tin trang bìa (sửa ở đây)
config/preamble.tex      gói, phông, màu, kiểu tiêu đề, bảng, biểu đồ
config/cover.tex         trang bìa kiểu Trường ĐH Bách Khoa
chapters/                tóm tắt, thuật ngữ, 6 phần chính (01-06)
chapters/legacy/         bản gốc 9 chương trước khi gộp, chỉ để tham chiếu
appendices/              hướng dẫn chạy, tóm tắt API
figures/mockup/          ảnh chụp mockup (docs/ui-mockup)
figures/ui/              ảnh chụp giao diện thật (apps/web) với dữ liệu thật
data/                    CSV đo đạc gốc (chép từ docs/evidence)
references.bib           tài liệu tham khảo (BibTeX)
```

Biểu đồ trong Chương 7 vẽ bằng pgfplots từ số đo trong `docs/BR4_BR5_IMPLEMENTATION.md`,
`docs/BR6_BR7_BR8_IMPLEMENTATION.md` và các file CSV trong `data/`.
