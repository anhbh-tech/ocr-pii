"""Che thông tin nhạy cảm lên ảnh trang của kho ADE, theo quyết định của pii-core.

    uv run python scripts/che_pii.py --doc <doc_id>        # một tài liệu
    uv run python scripts/che_pii.py --all                 # cả kho
    uv run python scripts/che_pii.py --all --dry           # chỉ đếm, không ghi
    uv run python scripts/che_pii.py --ho-so --group <mã> --doc A --doc B
                                                           # một hồ sơ, hỏi pii-core một lần

pii-core: `PII_CORE_URL`, hoặc thư viện (`PII_CORE_SRC`, vắng thì `pii-core/src`
trong repo) + `PII_CORE_KEY`, hoặc `make pii-core-serve` — xem `nap_pii_core`. Token in trên ô đen do
khoá của pii-core sinh: dùng cùng khoá với lần che văn bản vào kho.

Ghi `~/.private/che/<doc_id>/che.pdf` (chỉ ảnh, không lớp text, không
metadata) và `che.json` (trang, box, hạng mục — không chữ gốc). Mỗi tệp ghi
xong được mở lại và kiểm (`chung_minh`); dòng in ra nói đạt hay không.
Không gọi API ngoài máy nào. Cách làm và vì sao: docstring `src/ocr_lab/che.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from ocr_lab.ade_store import DEFAULT_STORE
from ocr_lab.che import (DEFAULT_OUT, PiiCoreThieu, che_ho_so, che_tai_lieu,
                         nap_pii_core, tai_lieu_trong)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--doc", action="append", help="doc_id (lặp được)")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--dry", action="store_true", help="chỉ đếm vùng, không ghi tệp")
    ap.add_argument("--khong-nhan", action="store_true",
                    help="không in token pii-core lên ô đen")
    ap.add_argument("--group", default="", help="mã hồ sơ gửi pii-core (group)")
    ap.add_argument("--ho-so", action="store_true",
                    help="các --doc là MỘT hồ sơ: hỏi pii-core một lần cho cả nhóm")
    a = ap.parse_args(argv)
    if a.ho_so and a.all:
        ap.error("--ho-so đi với các --doc của một hồ sơ, không với --all")

    try:
        nguon = nap_pii_core()
    except PiiCoreThieu as e:
        print(f"không che: {e}", file=sys.stderr)
        return 2
    dirs = list(tai_lieu_trong(a.store)) if a.all else [a.store / d for d in a.doc]
    kw = {"ghi": not a.dry, "ghi_nhan": not a.khong_nhan, "group": a.group}
    ket = (che_ho_so(dirs, nguon, a.out, **kw) if a.ho_so
           else (che_tai_lieu(d, nguon, a.out, **kw) for d in dirs))
    tong: Counter[str] = Counter()
    bo_qua: Counter[str] = Counter()
    hong = khong_dinh_vi = 0
    for t in ket:
        khong_dinh_vi += t.get("khong_dinh_vi", 0)
        tong.update(t.get("theo_hang_muc", {}))
        if "bo_qua" in t:
            bo_qua[t["bo_qua"].split(" (")[0]] += 1
        cm = t.get("chung_minh")
        if cm not in (None, "đạt"):
            hong += 1
        if not a.all:
            print(json.dumps(t, ensure_ascii=False))
    print(f"{len(dirs)} tài liệu · {sum(tong.values())} vùng · "
          f"không định vị {khong_dinh_vi} field · chứng minh hỏng {hong}", file=sys.stderr)
    for k, v in tong.most_common():
        print(f"  {k:<12} {v}", file=sys.stderr)
    for k, v in bo_qua.most_common():
        print(f"  bỏ qua: {k} — {v}", file=sys.stderr)
    return 1 if hong else 0


if __name__ == "__main__":
    raise SystemExit(main())
