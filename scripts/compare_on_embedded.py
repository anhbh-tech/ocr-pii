#!/usr/bin/env python3
"""So các engine NHẸ trên ẢNH NHÚNG, ADE Pro làm ground truth.

Đây là phép đo cho ĐÚNG bài toán: đọc chữ trong ảnh chèn vào PDF digital.
Khác hẳn phép đo trên trang hợp đồng scan — ở đó mọi engine đều đọc được
phần lớn và chênh lệch bị pha loãng trong hàng nghìn ký tự giống nhau.

Ở đây mỗi ảnh chỉ vài chục tới vài trăm ký tự, và chúng là mã số thuế, số
đơn, ngày tháng, số tiền. Đọc trượt một ảnh là mất trọn thông tin đó.

THƯỚC ĐO
────────
  giữ mã số     cổng QUYẾT ĐỊNH — số/mã/ngày có còn nguyên không
  CER theo từ   đọc sai bao nhiêu
  tỉ lệ đọc ra  bao nhiêu ảnh cho ra chữ (0 ký tự = trượt hoàn toàn)
  giây/ảnh      chạy nổi trên CPU không
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

from ocr_lab.metrics import accent_share  # noqa: E402
from ocr_lab.vlm_scoring import cham, gop  # noqa: E402

GT = Path.home() / ".private" / "anh_nhung_gt"
DANH_MUC = Path("reports/danh_muc_anh_nhung.json")

_MA_SO = re.compile(r"[A-Z]{0,3}\d{4,}(?:[/.-]\d+)*(?:/[A-Z-]+)?")


def lam_sach_gt(md: str) -> str:
    """Bỏ mọi thứ KHÔNG PHẢI chữ đọc được từ ảnh.

    ADE Pro trả về ba loại nội dung trộn lẫn, và chỉ một loại là thứ ta đo:

      * `<!-- doc_id=... -->`  siêu dữ liệu của lần chạy
      * `<description>…`       VLM MÔ TẢ bức ảnh bằng tiếng Anh — với ảnh
                               không có chữ thì đây là toàn bộ nội dung trả về
      * chữ thật               thứ duy nhất cần so

    Đo trên kho: 21.759 ký tự thô còn 4.389 sau lọc — **80% ground truth là
    văn xuôi mô tả**. Không lọc thì mọi engine chỉ-chép-chữ đều bị tính là
    sai trên toàn bộ phần đó, và CER ra 0,89-0,96 cho cả ba — một con số
    nói về phép đo, không nói gì về engine.
    """
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    md = re.sub(r"<description>.*?</description>", "", md, flags=re.S)
    md = re.sub(r"</?figure[^>]*>", "", md)
    return md.strip()


def cer_tu(chuan: str, doc: str) -> float:
    """Levenshtein theo TỪ, chuẩn hoá theo độ dài chuẩn.

    Theo từ chứ không theo ký tự: hai engine ngắt dòng và đặt khoảng trắng
    khác nhau, mà khác biệt đó không phải lỗi đọc — so ký tự thô thì chúng
    lấn át mọi thứ khác.
    """
    a, b = chuan.split(), doc.split()
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


def nap_gt() -> list[dict]:
    """Ground truth + đường dẫn ảnh, ghép theo băm nội dung."""
    dm = json.loads(DANH_MUC.read_text("utf-8"))
    duong: dict[str, str] = {}
    for a in dm["anh"]:
        if a.get("duong_dan_crop") and a["bam_anh"] not in duong:
            duong[a["bam_anh"]] = a["duong_dan_crop"]

    ra = []
    for f in sorted(GT.glob("*.json")):
        d = json.loads(f.read_text("utf-8"))
        p = duong.get(d["bam_anh"])
        if not (p and Path(p).is_file()):
            continue
        chuan = lam_sach_gt(d["markdown"])
        # ADE Pro không thấy chữ nào ⇒ ảnh này KHÔNG thuộc bài toán. Giữ lại
        # là chấm các engine trên một câu hỏi không có đáp án, và mọi thứ
        # chúng trả về đều bị tính là sai.
        if not chuan:
            continue
        ra.append({"bam": d["bam_anh"], "anh": Path(p),
                   "chuan": chuan, "tep": d["tep"]})
    return ra


def chay_tesseract(p: Path) -> str:
    return subprocess.run(["tesseract", str(p), "stdout", "-l", "vie+eng"],
                          capture_output=True, text=True).stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ra", type=Path,
                    default=Path("reports/anh_nhung_vs_pro.json"))
    a = ap.parse_args()

    viec = nap_gt()
    if not viec:
        raise SystemExit("chưa có ground truth — chạy scripts/gt_embedded_images.py")
    print(f"{len(viec)} ảnh có ground truth ADE Pro\n")

    from collections.abc import Callable
    engines: dict[str, Callable[[Path], str]] = {"tesseract": chay_tesseract}

    from ocr_lab.engines.vietocr_engine import VietOcrEngine
    t0 = time.perf_counter()
    viet = VietOcrEngine()
    print(f"nạp VietOCR: {time.perf_counter() - t0:.1f}s")
    engines["vietocr"] = viet.doc_van_ban

    from rapidocr_onnxruntime import RapidOCR
    rapid = RapidOCR()

    def chay_rapid(p: Path) -> str:
        kq, _ = rapid(str(p))
        return "\n".join(x[1] for x in kq) if kq else ""

    engines["rapidocr"] = chay_rapid
    print()

    ket: dict[str, dict] = {k: {"text": [], "giay": 0.0, "trat": 0}
                            for k in engines}
    for i, v in enumerate(viec, start=1):
        for ten, fn in engines.items():
            t0 = time.perf_counter()
            try:
                t = fn(v["anh"]) or ""
            except Exception:       # noqa: BLE001 — một ảnh hỏng không dừng cả mẻ
                t = ""
            ket[ten]["giay"] += time.perf_counter() - t0
            ket[ten]["text"].append(t)
            if not t.strip():
                ket[ten]["trat"] += 1
        if i % 10 == 0:
            print(f"  {i}/{len(viec)}")

    print(f"\nGROUND TRUTH = ADE Pro (VLM — KHÔNG phải OCR) · {len(viec)} ảnh\n")
    print("Chấm bằng THU HỒI / ĐỘ SẠCH trên từ có nghĩa, không phải CER:")
    print("Pro sinh ra emoji, [SEARCH_ICON], mô tả ảnh — thứ không bộ OCR nào")
    print("sinh ra được, và cũng không nên. CER phạt chúng vì điều đó.\n")
    print(f"{'engine':<12} {'thu hồi':>9} {'độ sạch':>9} {'giữ mã số':>11} "
          f"{'trượt':>7} {'giây/ảnh':>9}")
    print("-" * 62)

    bao = {
        "ground_truth": "ADE Pro (dpt-3-pro) — VLM, không phải OCR",
        "cach_cham": "thu hồi/độ sạch trên từ có nghĩa; CER không dùng được",
        "so_anh": len(viec),
        "engine": {},
    }
    for ten in engines:
        tung_anh = [cham(v["chuan"], t_) for v, t_ in zip(viec, ket[ten]["text"])]
        g = gop(tung_anh)
        g["trat"] = f"{ket[ten]['trat']}/{len(viec)}"
        g["giay_tren_anh"] = round(ket[ten]["giay"] / len(viec), 2)
        g["accent"] = round(accent_share("\n".join(ket[ten]["text"])), 3)
        bao["engine"][ten] = g
        print(f"{ten:<12} {g['thu_hoi']:>9.3f} {g['do_sach']:>9.3f} "
              f"{g['ma_so']:>11} {g['trat']:>7} {g['giay_tren_anh']:>9.2f}")

    # Ví dụ cụ thể: từ nào bị bỏ sót, từ nào bị bịa ra — con số tổng không
    # nói được engine hỏng ở đâu.
    mau = max(range(len(viec)), key=lambda i: len(viec[i]["chuan"]))
    print(f"\nVí dụ (ảnh nhiều chữ nhất, {Path(viec[mau]['tep']).name[:40]}):")
    for ten in engines:
        k = cham(viec[mau]["chuan"], ket[ten]["text"][mau])
        print(f"  {ten:<11} thiếu: {', '.join(k['thieu'][:6]) or '—'}")

    a.ra.parent.mkdir(parents=True, exist_ok=True)
    a.ra.write_text(json.dumps(bao, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n→ {a.ra}")


if __name__ == "__main__":
    main()
