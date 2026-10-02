"""Dò chữ NẰM TRONG ẢNH trên trang đã gắn nhãn "digital".

VẤN ĐỀ NÀY ĐẾN TỪ ĐÂU
─────────────────────
`classify_page` chỉ hỏi một câu: "trang này có lớp text không". Trang nào có
≥300 ký tự là BORN_DIGITAL và không bao giờ được OCR.

Nhưng tài liệu xuất từ Word/Excel rất hay chèn ẢNH CHỤP vào giữa văn bản
thật: một ô bảng chụp màn hình, một biên lai dán vào, một con dấu quét. Trang
đó vừa có 1.600 ký tự thật vừa có 400 ký tự nằm trong ảnh — và 400 ký tự kia
biến mất hoàn toàn khỏi bản chép, KHÔNG có dấu hiệu gì.

Đây là kiểu hỏng tệ nhất trong cả pipeline: bản chép trông đầy đủ, đọc trôi
chảy, chỉ thiếu đúng phần quan trọng (số tiền trong biên lai, mã số trong ô
bảng), và không ai biết để mà kiểm.

CÁCH ĐO — VÌ SAO PHẢI SO VỚI LỚP TEXT
─────────────────────────────────────
Chỉ đếm "ảnh có chữ" thì sai: chữ ký có chữ, logo có chữ, watermark có chữ,
và nhiều ảnh đơn giản là ảnh chụp LẠI phần văn bản đã có trong lớp text.

Thứ đáng lo là chữ trong ảnh mà lớp text KHÔNG có. Nên phép đo là:

    1. Vision đọc từng ảnh nhúng  →  tập từ A
    2. Lấy lớp text của trang     →  tập từ B
    3. Phần A \\ B chính là chữ ĐANG BỊ MẤT

So theo TỪ chứ không theo chuỗi con: lớp text và Vision xuống dòng khác nhau,
đặt dấu cách khác nhau, nên so chuỗi sẽ báo "mất" cả những phần không mất.

KHÔNG GỌI API. Vision chạy cục bộ trên Neural Engine.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path.home() / "ocr-lab-gpu" / "src"))

from ocr_lab.classify import PageKind, classify_pdf                # noqa: E402
from ocr_lab.image_text import (                                   # noqa: E402
    ImageTextFinding, danh_gia_lai, loc_chan_trang,
    tim_khung_trang_toan_kho,
)

#: Ảnh nhỏ hơn mức này không thể chứa chữ đọc được. Đặt theo pixel thật chứ
#: không theo tỉ lệ trang: một icon 32×32 vẫn là icon dù trang khổ nào.
MIN_W, MIN_H = 60, 20

#: Số từ "mới" tối thiểu để coi là đáng OCR. Dưới mức này thường là nhiễu
#: nhận dạng từ logo hoặc chữ ký — Vision hay đọc ra vài ký tự vô nghĩa.
MIN_TU_MOI = 4


def chuan_hoa(s: str) -> set[str]:
    """Tập từ đã chuẩn hoá để so hai nguồn văn bản.

    Bỏ dấu câu và gộp chữ hoa/thường: lớp text và Vision khác nhau ở những
    chỗ đó một cách hệ thống, mà khác biệt đó không phải mất chữ.
    """
    return {w for w in re.split(r"[^\w]+", s.lower()) if len(w) >= 2}


def quet_trang(pdf: Path, index: int, eng, tmp: Path) -> dict:
    """Đọc mọi ảnh nhúng của một trang, trả thống kê chữ bị mất."""
    import pymupdf

    doc = pymupdf.open(pdf)
    page = doc[index]
    lop_text = chuan_hoa(str(page.get_text("text") or ""))

    tu_moi: set[str] = set()
    n_anh = 0
    for im in page.get_images(full=True):
        try:
            rects = page.get_image_rects(im[0]) or []
        except Exception:
            continue
        if not any(r.width >= MIN_W and r.height >= MIN_H for r in rects):
            continue
        try:
            pix = pymupdf.Pixmap(doc, im[0])
            if pix.n - pix.alpha >= 4:          # CMYK → RGB
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            f = tmp / f"im_{index}_{im[0]}.png"
            pix.save(f)
        except Exception:
            continue
        n_anh += 1
        try:
            got = eng.read_page(f)
        except Exception:
            continue
        tu_moi |= chuan_hoa(got.text) - lop_text
        f.unlink(missing_ok=True)

    doc.close()
    return {"page": index + 1, "n_anh": n_anh,
            "tu_moi": sorted(tu_moi), "n_tu_moi": len(tu_moi)}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path,
                    default=Path.home() / ".private" / "refiny_data")
    ap.add_argument("--max-files", type=int, default=40)
    ap.add_argument("--pattern", default="")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "reports" / "anh_co_chu.json")
    args = ap.parse_args()

    from ocr_gpu.engines.vision import VisionEngine
    eng = VisionEngine()

    pdfs = [p for p in sorted(args.root.rglob("*.pdf"))
            if args.pattern in str(p)][:args.max_files]
    if not pdfs:
        print("Không có PDF nào khớp.", file=sys.stderr)
        return 1

    print(f"Quét {len(pdfs)} PDF · engine Apple Vision (cục bộ, miễn phí)\n")
    print(f"{'tệp':<44} {'trang':>5} {'ảnh':>4} {'từ bị mất':>10}")
    print("─" * 68)

    ket = []
    n_trang_digital = n_trang_sot = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for pdf in pdfs:
            try:
                res = classify_pdf(pdf)
            except Exception:
                continue
            for p in res.pages:
                if p.kind is not PageKind.BORN_DIGITAL:
                    continue
                n_trang_digital += 1
                r = quet_trang(pdf, p.index, eng, tmp)
                if r["n_tu_moi"] < MIN_TU_MOI:
                    continue
                n_trang_sot += 1
                r["file"] = str(pdf.relative_to(args.root))
                r["chars_text"] = p.chars
                ket.append(r)
                print(f"{pdf.name[:42]:<44} {r['page']:>5} {r['n_anh']:>4} "
                      f"{r['n_tu_moi']:>10}")
                print(f"      ví dụ: {', '.join(r['tu_moi'][:10])}")

    print("─" * 68)
    print(f"{n_trang_digital} trang gắn nhãn digital · "
          f"{n_trang_sot} trang có chữ trong ảnh "
          f"({n_trang_sot / max(n_trang_digital, 1) * 100:.0f}%)")

    # ── lọc hai lớp ─────────────────────────────────────────────────────
    #
    # Con số thô ở trên CHƯA phải kết luận: phần lớn "chữ trong ảnh" là
    # letterhead và chân trang, OCR chúng tốn tiền để lấy về thứ đã biết.
    import collections

    fs = [ImageTextFinding(x["page"], x["n_tu_moi"], max(x["chars_text"] // 5, 1),
                           x["tu_moi"], True, "") for x in ket]
    khung = tim_khung_trang_toan_kho([f.tu_moi for f in fs])

    theo_tep = collections.defaultdict(list)
    for x, f in zip(ket, fs):
        theo_tep[x["file"]].append(f)

    dang_ocr = []
    for tep, g in theo_tep.items():
        for f in loc_chan_trang(g):          # lớp 1: chân trang trong tệp
            f2 = danh_gia_lai(f, khung)      # lớp 2: khung trang toàn kho
            if f2.dang_ocr:
                dang_ocr.append({"file": tep, "page": f2.page,
                                 "n_tu_moi": f2.n_tu_moi,
                                 "tu_moi": f2.tu_moi, "ly_do": f2.ly_do})

    print(f"\n{len(khung)} từ khung trang dùng chung toàn kho:")
    print("   " + ", ".join(sorted(khung)[:20]))
    print(f"\nSau khi lọc: {len(dang_ocr)} trang THỰC SỰ đáng OCR "
          f"(bỏ {len(ket) - len(dang_ocr)} trang chỉ có khung trang)")
    for x in dang_ocr:
        print(f"   {Path(x['file']).name[:46]:<48} tr{x['page']:<3} "
              f"{x['n_tu_moi']:>3} từ")

    args.out.parent.mkdir(exist_ok=True)
    args.out.write_text(json.dumps(
        {"tho": ket, "khung_trang": sorted(khung), "dang_ocr": dang_ocr},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGhi: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
