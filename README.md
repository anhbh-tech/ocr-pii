# ocr-lab

Phòng thí nghiệm OCR độc lập cho tài liệu tiếng Việt + tiếng Anh.

Tách khỏi `refiny_engine` có chủ đích: ở đó OCR, lược danh tính và cổng kiểm PII
nằm chung một đường, nên khi văn bản sai ta không tách được lỗi thuộc tầng nào.
Dự án này chỉ lo **một việc: raw text phải đúng đã**.

## Vấn đề đang giải

Đo trên kho thật (11/09/2026):

| Chỉ số | Giá trị |
|---|---|
| Tệp có nội dung | 566 |
| Tệp OCR ra rác | **51 (9,0%)** |
| Hồ sơ A | **6/6 ảnh rác** |
| Hồ sơ B | **7/7 ảnh rác** |
| PDF hỏng | **0** |

Hỏng tập trung **100% ở ảnh chụp**. Hai hồ sơ mất trắng phần ảnh — không phải
vài tệp lẻ. Vì vậy thứ tự ưu tiên là **ảnh chụp trước, tài liệu số sau**.

## Nguyên tắc không thương lượng

1. **Dữ liệu khách không rời máy.** Mọi engine chạy on-device. Không API đám mây,
   kể cả để thử nhanh.
2. **Định danh phải sống sót nguyên văn** — số hiệu, email, ngày, mã hồ sơ.
   Đây là cổng chặn (`identifier_preservation ≥ 99%`), không phải chỉ tiêu phụ.
3. **Dấu tiếng Việt mang thông tin định danh.** Engine làm mất dấu là loại, dù
   nhanh hơn.

## Cấu trúc

```
src/ocr_lab/
  classify.py      phân loại nguồn theo TỪNG TRANG (số/quét/lai)
  classify_api.py  hợp đồng JSON "đi đường nào" (docs/classify-api.md)
  language.py      nhận dạng vi / en / mixed
  metrics.py       CER, WER, accent_share, identifier_preservation
  postcorrect.py   hậu xử lý, chunk ≤ 130 từ
  pipeline.py      nối toàn bộ
  engines/         trình bao thống nhất cho từng engine

data/              quyền 700 · KHÔNG vào git
  gold/            tài liệu THẬT của khách + bản gõ tay
  benchmarks/      MDPBench (công khai, ~176 MB)

reports/           kết quả đo · KHÔNG vào git

pii-core/          pii-core: quyết định che PII (project uv riêng)
```

## Dữ liệu khách: vì sao chặn ở git từ đầu

`data/` bị chặn trong `.gitignore` **trước khi có tệp nào**. Một lần commit nhầm
là dữ liệu nằm vĩnh viễn trong lịch sử git, kể cả khi xoá ở commit sau. Chặn
trước là cách duy nhất chắc chắn.

Đã kiểm bằng `git check-ignore` trên tệp giả lập, không phải tin vào cấu hình.

## Chạy

```bash
uv sync                                   # dựng môi trường
uv run pytest -v                          # chạy test
uv run python -c "import pymupdf; print(pymupdf.__doc__)"
```

`make test` chạy cả hai bộ: `make test-ocr-lab` (`uv run python -m pytest
tests/`) và `make test-pii-core` (`cd pii-core && uv run --extra dev pytest`).

### pii-core

`pii-core/` là bản chép pii-core vào repo (không kèm lịch sử của nó), nên
ocr-lab chạy được mà không cần bản checkout riêng. `che.py` và
`serve_review.py` tìm pii-core theo thứ tự: `PII_CORE_URL` (HTTP) →
thư viện ở `PII_CORE_SRC`, vắng thì `pii-core/src` trong repo (cần khoá) →
`pii-core serve` ở `127.0.0.1:8813`.

```bash
export PII_CORE_KEY_FILE=~/.private/pii-core/key        # hoặc PII_CORE_KEY=...
export PII_CORE_ROSTER=~/.private/pii-core/roster.json  # tuỳ chọn
make pii-core-serve                                     # cd pii-core && uv run python -m pii_core serve
```

Khoá và roster không bao giờ nằm trong cây git. Hướng dẫn của chính pii-core:
`pii-core/README.md`, `pii-core/AGENTS.md`.

Dùng `import pymupdf`, **không** dùng `import fitz` — tên cũ đã lỗi thời và in
cảnh báo ở mọi lệnh gọi.

## Kế hoạch đầy đủ

`~/.hermes/plans/2026-09-11_110404-ocr-pipeline-research.md`
