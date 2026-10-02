"""So ba engine trên cùng tài liệu: ADE Verity · ADE Pro · Apple Vision.

CHỈ ĐỌC KHO, KHÔNG GỌI API. Mọi con số dưới đây rút từ tệp đã lưu.

VÌ SAO TÁCH THEO LOẠI TÀI LIỆU
──────────────────────────────
Gộp cả kho vào một con số đã từng cho kết luận sai: Vision ít hơn ADE 33% ký
tự nhìn như "Vision đọc kém", trong khi tách ra thì thấy chênh lệch nằm gần
hết ở ảnh sản phẩm — nơi ADE sinh cả đoạn MÔ TẢ ảnh bằng VLM, còn Vision chỉ
chép chữ. Đó là hai việc khác nhau, không phải hai mức chất lượng.

VÌ SAO TỈ LỆ DẤU TÍNH RIÊNG TRÊN DÒNG TIẾNG VIỆT
────────────────────────────────────────────────
Hợp đồng và CCCD ở đây in song ngữ Việt–Anh, lại nhiều chữ số. Tính tỉ lệ dấu
trên cả trang thì phần tiếng Anh kéo con số xuống và trông như engine làm mất
dấu. Lọc theo cấu trúc âm tiết (bất biến với việc mất dấu) rồi mới tính.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.ade_store import DEFAULT_STORE                       # noqa: E402
from ocr_lab.language import vietnamese_syllable_share            # noqa: E402
from ocr_lab.metrics import accent_share, identifiers             # noqa: E402

HOP_DONG = ("hddvpl", "hop dong", "bien ban", "bb ban", "de nghi",
            "agreement", "sevices", "services")


def loai(ten: str) -> str:
    t = ten.lower()
    if "cccd" in t:
        return "CCCD"
    if any(k in t for k in HOP_DONG):
        return "Hợp đồng / biên bản scan"
    return "Ảnh sản phẩm / màn hình"


def dau_viet(text: str) -> float | None:
    """Tỉ lệ dấu, chỉ trên dòng thực sự là tiếng Việt."""
    vi = [l for l in text.split("\n")
          if l.strip() and vietnamese_syllable_share(l) > 0.5]
    return accent_share("\n".join(vi)) if vi else None


def doc_engine(d: Path, eng: str) -> tuple[str, float] | None:
    """(văn bản, credits) của một engine, hoặc None nếu chưa chạy."""
    if eng == "vision":
        f = d / "vision.json"
        if not f.is_file():
            return None
        v = json.loads(f.read_text("utf-8"))
        return "\n".join(p["text"] for p in v["pages"]), 0.0

    f = d / ("parse_pro.json" if eng == "pro" else "parse.json")
    m = d / ("meta_pro.json" if eng == "pro" else "meta.json")
    if not f.is_file():
        return None
    md = json.loads(f.read_text("utf-8")).get("markdown", "")
    cr = json.loads(m.read_text("utf-8")).get("credits", 0.0) if m.is_file() else 0.0
    return md, float(cr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--chi-tiet", action="store_true",
                    help="in từng tài liệu thay vì gộp theo loại")
    args = ap.parse_args()

    ENGINES = [("verity", "ADE Verity"), ("pro", "ADE Pro"),
               ("vision", "Apple Vision")]
    nhom: dict[str, list] = {}

    for d in sorted(args.store.iterdir()):
        if not (d / "meta.json").is_file():
            continue
        ten = Path(json.loads((d / "meta.json").read_text("utf-8"))
                   .get("source", d.name)).name
        ket = {}
        for key, _ in ENGINES:
            got = doc_engine(d, key)
            if got:
                txt, cr = got
                ket[key] = {"chars": len(txt), "credits": cr,
                            "dau": dau_viet(txt),
                            "ids": len(set(identifiers(txt)))}
        # Chỉ so tài liệu có ĐỦ cả ba: thiếu một engine thì mọi so sánh
        # thành ra so hai tập khác nhau.
        if len(ket) == 3:
            nhom.setdefault(loai(ten), []).append((ten, ket))

    if not nhom:
        print("Chưa tài liệu nào có đủ cả 3 engine.", file=sys.stderr)
        print("Cần: make correct → make vision → make ade-pro", file=sys.stderr)
        return 1

    for ten_nhom, items in nhom.items():
        print(f"\n{'═' * 78}")
        print(f"{ten_nhom}   ({len(items)} tài liệu có đủ 3 engine)")
        print("═" * 78)

        if args.chi_tiet:
            print(f"{'tài liệu':<34} {'Verity':>8} {'Pro':>8} {'Vision':>8}")
            print("─" * 62)
            for ten, k in items:
                print(f"{ten[:32]:<34} {k['verity']['chars']:>8} "
                      f"{k['pro']['chars']:>8} {k['vision']['chars']:>8}")
            print()

        print(f"{'':16} {'ký tự':>9} {'dấu':>7} {'số hiệu':>8} {'credits':>9}")
        print("─" * 55)
        for key, nhan in ENGINES:
            ch = sum(x[1][key]["chars"] for x in items)
            cr = sum(x[1][key]["credits"] for x in items)
            ids = sum(x[1][key]["ids"] for x in items)
            ds = [x[1][key]["dau"] for x in items if x[1][key]["dau"] is not None]
            d_s = f"{sum(ds) / len(ds):.3f}" if ds else "  —  "
            gia = f"${cr / 100:.3f}" if cr else "miễn phí"
            print(f"{nhan:<16} {ch:>9} {d_s:>7} {ids:>8} {gia:>9}")

    print(f"\n{'═' * 78}")
    print("dấu     = tỉ lệ dấu trên các dòng THỰC SỰ tiếng Việt (mốc 0,217)")
    print("số hiệu = số định danh phân biệt đọc ra (số hợp đồng, ngày, mã số)")
    print("Vision chạy cục bộ — không tốn tiền, không gửi tệp đi đâu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
