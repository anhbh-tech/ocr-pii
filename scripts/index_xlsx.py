#!/usr/bin/env python3
"""Đưa xlsx vào kho bằng bộ đọc CỤC BỘ, không qua ADE.

ADE từ chối xlsx: 422 "Unsupported format: application/zip" (đã kiểm bằng
một xlsx tự dựng, không suy đoán từ tệp hỏng). Nhưng xlsx là định dạng có
cấu trúc sẵn — không cần OCR để biết ô B7 chứa gì.

Nên chúng đi đường riêng: `extract.py` đọc thẳng, ghi vào CÙNG kho với
cùng khuôn (`parse.json` + `meta.json`), nên cây hồ sơ, khung đối chiếu và
trình đọc dùng lại nguyên vẹn, không cần biết tệp này chưa từng qua ADE.

Neo vị trí là `grounding.kind = "path"` (`Sheet1!B7`) thay vì toạ độ hộp:
bảng tính không có toạ độ trang, và bịa ra toạ độ ước lượng sẽ vẽ những ô
trông như thật mà lệch.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ocr_lab.ade_store import doc_id_for  # noqa: E402
from ocr_lab.extract import trich_xuat  # noqa: E402

NGUON = Path.home() / ".private" / "refiny_data"
KHO = Path.home() / ".private" / "ade_out"


def main() -> int:
    tep = sorted(NGUON.rglob("*.xlsx"))
    print(f"{len(tep)} tệp xlsx")
    xong = bo_qua = loi = 0
    t0 = time.perf_counter()

    for f in tep:
        rel = str(f.relative_to(NGUON))
        d = KHO / doc_id_for(rel)
        if (d / "parse.json").is_file():
            bo_qua += 1
            continue
        try:
            kq = trich_xuat(f)
        except Exception as e:      # noqa: BLE001
            loi += 1
            print(f"  LỖI {type(e).__name__}: {f.name[:44]}")
            continue

        d.mkdir(parents=True, exist_ok=True)
        (d / "parse.json").write_text(
            json.dumps(kq, ensure_ascii=False, indent=1), "utf-8")
        (d / "meta.json").write_text(json.dumps({
            "source": rel,
            "model": "doc-tep-cuc-bo",
            "credits": 0.0,
            "section": "xlsx",
            "parsed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            # Không có ảnh trang: bảng tính không phân trang. Trình đọc nhận
            # ra điều đó qua `preview` server gửi kèm, không qua số này.
            "pages": [{"page": 1}],
        }, ensure_ascii=False, indent=1), "utf-8")
        xong += 1
        # structure dùng `children`, không phải `chunks` — đếm sai khoá
        # in ra 0 cho mọi tệp trong khi dữ liệu vẫn đủ, đúng kiểu số liệu
        # trông như thất bại mà thực ra chỉ là đọc nhầm khoá.
        n = len((kq.get("structure") or {}).get("children") or [])
        print(f"  {n:>4} khối · {len(kq.get(chr(39)+chr(39)) or kq.get("markdown") or ""):>5} ký tự · {f.name[:46]}")

    print(f"\n{xong} xong · {bo_qua} đã có · {loi} lỗi · "
          f"{time.perf_counter() - t0:.1f}s · miễn phí")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
