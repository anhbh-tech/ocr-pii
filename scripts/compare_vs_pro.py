"""So các engine CPU với ADE Pro làm GROUND TRUTH cho toàn dự án.

VÌ SAO ADE PRO LÀ GROUND TRUTH
──────────────────────────────
Người dùng đã xác nhận Pro cho kết quả ngang bản chép tay của luật sư. Nó
đắt (0,9 credits/trang) nên không dùng thường xuyên, nhưng chính vì đắt mà
nó hợp làm mốc: chạy một lần, so mọi engine rẻ vào đó mãi mãi.

Điều này thay cho `data/gold/truth/` vốn vẫn rỗng — và tốt hơn, vì nó phủ
toàn bộ tài liệu đã chạy Pro thay vì 23 tệp người phải gõ tay.

BỐN THƯỚC ĐO, MỖI CÁI TRẢ LỜI MỘT CÂU KHÁC
──────────────────────────────────────────
  CER                đọc sai bao nhiêu ký tự
  tỉ lệ dấu          có đọc ra tiếng Việt không (chỉ tính DÒNG tiếng Việt)
  giữ mã số          cổng QUYẾT ĐỊNH — số hợp đồng, CCCD, ngày tháng
  giây/trang         có chạy nổi trên máy đích không

Cổng quyết định là mã số, không phải CER. Đây là hồ sơ pháp lý/SHTT: một
mã số sai nguy hiểm hơn một dấu thiếu, vì người soát không có cách nào
phát hiện lại.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ocr_lab.language import is_vietnamese_syllable, vietnamese_syllable_share  # noqa: E402
from ocr_lab.metrics import accent_share  # noqa: E402

STORE = Path.home() / ".private" / "ade_out"

#: Mã số: số hợp đồng, CCCD, ngày, mã đơn USPTO. Thứ SAI LÀ NGUY HIỂM.
_MA_SO = re.compile(r"[A-Z]{0,3}\d{4,}(?:/\d+)*(?:/[A-Z-]+)?")


def loc_dong_viet(t: str) -> str:
    """Giữ lại các dòng TIẾNG VIỆT.

    Lọc bằng cấu trúc âm tiết chứ không bằng dấu: phép lọc phải sống sót
    đúng cái lỗi mà OCR vừa gây ra (mất dấu). Dùng dấu để lọc là vòng vo —
    engine mất dấu sẽ bị loại hết dòng rồi chấm trên tập rỗng.
    """
    ra = []
    for dong in t.split("\n"):
        tu = [w for w in dong.split() if w.isalpha()]
        if len(tu) >= 3 and sum(map(is_vietnamese_syllable, tu)) / len(tu) >= 0.45:
            ra.append(dong)
    return "\n".join(ra)


def cer(chuan: str, doc: str) -> float:
    """Tỉ lệ lỗi ký tự (Levenshtein / độ dài chuẩn)."""
    a, b = chuan.split(), doc.split()
    # So theo TỪ chứ không theo ký tự thô: khác biệt về khoảng trắng và
    # ngắt dòng giữa hai engine không phải lỗi đọc, mà so ký tự thô thì
    # chúng lấn át mọi thứ khác.
    m, n = len(a), len(b)
    if not m:
        return 0.0 if not n else 1.0
    truoc = list(range(n + 1))
    for i in range(1, m + 1):
        nay = [i] + [0] * n
        for j in range(1, n + 1):
            nay[j] = min(truoc[j] + 1, nay[j - 1] + 1,
                         truoc[j - 1] + (a[i - 1] != b[j - 1]))
        truoc = nay
    return truoc[n] / m


def giu_ma_so(chuan: str, doc: str) -> tuple[int, int]:
    c = set(_MA_SO.findall(chuan))
    return len(c & set(_MA_SO.findall(doc))), len(c)


def chon_tai_lieu(gioi_han: int) -> list[tuple[Path, list[Path], str]]:
    """Tài liệu có ADE Pro VÀ là tiếng Việt — mốc phải có thì mới so được."""
    ra = []
    for d in sorted(STORE.iterdir()):
        pro = d / "parse_pro.json"
        if not pro.is_file():
            continue
        md = json.loads(pro.read_text("utf-8")).get("markdown", "")
        if accent_share(md) < 0.15:      # tài liệu tiếng Anh — không so được
            continue
        pages = sorted(
            [p for p in (d / "pages").glob("p*.*")
             if p.suffix.lower() in (".jpg", ".jpeg", ".png")],
            key=lambda p: int("".join(c for c in p.stem if c.isdigit()) or 0))
        if pages:
            ra.append((d, pages, md))
        if len(ra) >= gioi_han:
            break
    return ra


def chay_tesseract(imgs: list[Path]) -> str:
    return "\n".join(
        subprocess.run(["tesseract", str(p), "stdout", "-l", "vie"],
                       capture_output=True, text=True).stdout for p in imgs)


def chay_vietocr(imgs: list[Path], eng) -> str:
    return "\n".join(eng.doc_van_ban(p) for p in imgs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--so-tai-lieu", type=int, default=6)
    ap.add_argument("--so-trang", type=int, default=0,
                    help="""số trang đầu mỗi tài liệu (0 = TẤT CẢ, mặc định).

Cắt bớt trang làm hỏng phép đo: `markdown` của ADE Pro là của CẢ tài liệu,
nên chạy 3/8 trang rồi so với toàn bộ sẽ tính 5 trang thiếu thành lỗi đọc.
Đã đo nhầm một lần như vậy và ra CER 0,63 cho cả hai engine — con số đó nói
về phép cắt, không nói gì về engine.""")
    ap.add_argument("--ra", type=Path, default=Path("reports/engine_vs_pro.json"))
    a = ap.parse_args()

    tl = chon_tai_lieu(a.so_tai_lieu)
    print(f"{len(tl)} tài liệu tiếng Việt có ADE Pro làm mốc\n")

    from ocr_lab.engines.vietocr_engine import VietOcrEngine
    t0 = time.perf_counter()
    viet = VietOcrEngine()
    print(f"nạp VietOCR: {time.perf_counter() - t0:.1f}s\n")

    gom = {k: {"text": [], "giay": 0.0} for k in ("tesseract", "vietocr")}
    chuan_all, so_trang = [], 0

    for d, pages, pro_md in tl:
        imgs = pages[:a.so_trang] if a.so_trang else pages
        so_trang += len(imgs)
        chuan_all.append(pro_md)

        t0 = time.perf_counter()
        gom["tesseract"]["text"].append(chay_tesseract(imgs))
        gom["tesseract"]["giay"] += time.perf_counter() - t0

        t0 = time.perf_counter()
        gom["vietocr"]["text"].append(chay_vietocr(imgs, viet))
        gom["vietocr"]["giay"] += time.perf_counter() - t0
        print(f"  {d.name[:16]}  {len(imgs)} trang")

    chuan = "\n".join(chuan_all)
    chuan_v = loc_dong_viet(chuan)

    print(f"\nGROUND TRUTH = ADE Pro · {len(chuan)} ký tự · "
          f"dấu {accent_share(chuan_v):.3f}\n")
    print(f"{'engine':<14} {'CER':>6} {'dấu':>7} {'âm tiết':>8} "
          f"{'giữ mã số':>11} {'giây/trang':>11}")
    print("-" * 62)

    bao = {"ground_truth": "ADE Pro", "so_tai_lieu": len(tl),
           "so_trang": so_trang, "engine": {}}
    for ten, g in gom.items():
        t = "\n".join(g["text"])
        tv = loc_dong_viet(t)
        gm, tong = giu_ma_so(chuan, t)
        r = {
            "cer": round(cer(chuan, t), 3),
            "accent": round(accent_share(tv), 3),
            "syllable": round(vietnamese_syllable_share(t), 2),
            "ma_so": f"{gm}/{tong}",
            "ma_so_pct": round(gm / tong * 100, 1) if tong else None,
            "giay_tren_trang": round(g["giay"] / max(1, so_trang), 2),
            "ky_tu": len(t),
        }
        bao["engine"][ten] = r
        print(f"{ten:<14} {r['cer']:>6.3f} {r['accent']:>7.3f} "
              f"{r['syllable']:>8.2f} {r['ma_so']:>11} "
              f"{r['giay_tren_trang']:>11.2f}")

    a.ra.parent.mkdir(parents=True, exist_ok=True)
    a.ra.write_text(json.dumps(bao, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n→ {a.ra}")


if __name__ == "__main__":
    main()
