"""Đọc chữ nằm trong ẢNH NHÚNG của trang đã gắn nhãn digital.

VÌ SAO KHÔNG DÙNG ADE CHO VIỆC NÀY
──────────────────────────────────
Trang digital đã có lớp text đầy đủ; thứ thiếu chỉ là chữ trong vài ảnh chụp
chèn vào. Gửi cả trang cho ADE Pro (0,9 credits) để lấy về mấy trăm ký tự
trong ảnh là trả tiền cho phần đã có sẵn.

Đo trên `NH9001.US_Filing Receipt` tr5 — trang duy nhất trong kho thực sự cần:

    lớp text        175 ký tự (đã có, miễn phí)
    2 ảnh nhúng   1.123 ký tự (đang thiếu)
    Apple Vision   1,37 giây · 0 đồng
    ADE Pro        0,9 credits/trang, và vẫn phải đọc lại cả phần đã có

Apple Vision chạy trên Neural Engine của máy, không gửi tệp đi đâu — điều này
quan trọng gấp đôi với hồ sơ khách hàng.

VÌ SAO KHÔNG GHÉP THẲNG VÀO `markdown`
──────────────────────────────────────
Bản chép của lớp text và bản chép từ ảnh là hai nguồn khác nhau, độ tin cậy
khác nhau. Trộn vào một chuỗi thì người soát không còn phân biệt được chữ nào
đọc thẳng từ PDF (chắc chắn đúng) và chữ nào do OCR đoán (có thể sai).

Nên ghi ra `image_text.json` riêng, kèm toạ độ ảnh trên trang để soi lại được.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path.home() / "ocr-lab-gpu" / "src"))

from ocr_lab.ade_store import DEFAULT_STORE, doc_id_for            # noqa: E402
from ocr_lab.classify import PageKind, classify_pdf                # noqa: E402
from ocr_lab.image_text import (                                   # noqa: E402
    ImageTextFinding, danh_gia_lai, loc_chan_trang,
    tim_khung_trang_toan_kho,
)

SOURCE_ROOT = Path.home() / ".private" / "refiny_data"

#: Ảnh nhỏ hơn mức này không chứa chữ đọc được (icon, đường kẻ).
MIN_W, MIN_H = 60, 20


def doc_anh_trang(doc, page, eng, tmp: Path) -> list[dict]:
    """Đọc mọi ảnh nhúng đủ lớn của một trang."""
    import pymupdf

    ra = []
    for im in page.get_images(full=True):
        try:
            rects = page.get_image_rects(im[0]) or []
        except Exception:
            continue
        lon = [r for r in rects if r.width >= MIN_W and r.height >= MIN_H]
        if not lon:
            continue
        try:
            pix = pymupdf.Pixmap(doc, im[0])
            if pix.n - pix.alpha >= 4:          # CMYK → RGB
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            f = tmp / f"x{im[0]}.png"
            pix.save(f)
        except Exception:
            continue
        try:
            got = eng.read_page(f)
        except Exception:
            f.unlink(missing_ok=True)
            continue
        f.unlink(missing_ok=True)
        if not got.text.strip():
            continue
        r = lon[0]
        ra.append({
            "xref": im[0],
            # Toạ độ ảnh TRÊN TRANG, để soi lại được chữ này đến từ đâu.
            "box": [round(r.x0, 1), round(r.y0, 1),
                    round(r.x1, 1), round(r.y1, 1)],
            "text": got.text,
            "lines": [{"text": s.text, "confidence": s.confidence}
                      for s in got.lines],
        })
    return ra


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=SOURCE_ROOT)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--max-files", type=int, default=120)
    ap.add_argument("--pattern", default="")
    ap.add_argument("--write", action="store_true",
                    help="ghi image_text.json vào kho (mặc định chỉ đo)")
    args = ap.parse_args()

    import pymupdf
    from ocr_gpu.engines.vision import VisionEngine
    eng = VisionEngine()

    pdfs = [p for p in sorted(args.root.rglob("*.pdf"))
            if args.pattern in str(p)][:args.max_files]
    print(f"Quét {len(pdfs)} PDF · Apple Vision (cục bộ, miễn phí)")
    print(f"Chế độ: {'GHI vào kho' if args.write else 'chỉ đo'}\n")

    # Vòng 1: thu thập để biết đâu là khung trang dùng chung toàn kho.
    tho = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for pdf in pdfs:
            try:
                res = classify_pdf(pdf)
                doc = pymupdf.open(pdf)
            except Exception:
                continue
            for p in res.pages:
                if p.kind is not PageKind.BORN_DIGITAL:
                    continue
                anh = doc_anh_trang(doc, doc[p.index], eng, tmp)
                if not anh:
                    continue
                from ocr_lab.image_text import chuan_hoa
                tu_text = chuan_hoa(str(doc[p.index].get_text("text") or ""))
                tu_anh: set[str] = set()
                for a in anh:
                    tu_anh |= chuan_hoa(a["text"])
                moi = sorted(tu_anh - tu_text)
                if moi:
                    tho.append({"pdf": pdf, "page": p.index, "anh": anh,
                                "tu_moi": moi, "n_text": max(len(tu_text), 1)})
            doc.close()

    if not tho:
        print("Không trang nào có chữ trong ảnh.")
        return 0

    # Vòng 2: lọc khung trang (letterhead) rồi mới kết luận.
    khung = tim_khung_trang_toan_kho([x["tu_moi"] for x in tho])
    import collections
    theo_tep = collections.defaultdict(list)
    for x in tho:
        theo_tep[x["pdf"]].append(
            ImageTextFinding(x["page"], len(x["tu_moi"]), x["n_text"],
                             x["tu_moi"], True, ""))

    giu = set()
    for tep, fs in theo_tep.items():
        for f in loc_chan_trang(fs):
            if danh_gia_lai(f, khung).dang_ocr:
                giu.add((tep, f.page))

    print(f"{len(tho)} trang có chữ trong ảnh · {len(khung)} từ khung trang "
          f"dùng chung · {len(giu)} trang ĐÁNG ghi\n")
    print(f"{'tài liệu':<46} {'tr':>3} {'ảnh':>4} {'ký tự':>7}")
    print("─" * 64)

    n_ghi = 0
    for x in tho:
        if (x["pdf"], x["page"]) not in giu:
            continue
        ky_tu = sum(len(a["text"]) for a in x["anh"])
        print(f"{x['pdf'].name[:44]:<46} {x['page'] + 1:>3} "
              f"{len(x['anh']):>4} {ky_tu:>7}")
        if not args.write:
            continue
        rel = str(x["pdf"].relative_to(args.root))
        d = args.store / doc_id_for(rel)
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o700)
        f = d / "image_text.json"
        cu = json.loads(f.read_text("utf-8")) if f.is_file() else {"pages": []}
        cu["source"] = rel
        cu["engine"] = "apple-vision"
        cu["pages"] = [p for p in cu["pages"] if p["page"] != x["page"] + 1]
        cu["pages"].append({"page": x["page"] + 1, "images": x["anh"]})
        cu["pages"].sort(key=lambda p: p["page"])
        f.write_text(json.dumps(cu, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        f.chmod(0o600)
        n_ghi += 1

    print("─" * 64)
    if args.write:
        print(f"Đã ghi image_text.json cho {n_ghi} trang.")
    else:
        print("Chưa ghi gì. Thêm --write để lưu vào kho.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
