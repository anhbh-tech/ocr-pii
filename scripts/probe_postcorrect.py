"""Đo model sửa lỗi protonX — trọng tâm là CỔNG ĐỊNH DANH, không phải tỉ lệ dấu.

VÌ SAO CỔNG ĐỊNH DANH QUAN TRỌNG HƠN Ở ĐÂY
──────────────────────────────────────────
Model này rất giỏi phục hồi dấu — đó là điều nó được thiết kế cho, và phép thử
nhanh xác nhận: "can cu bo luat lao dong 2019" → "căn cứ bộ luật lao động
2019", đúng hoàn toàn.

Nhưng nó là model SINH CHỮ, và ca hỏng đầu tiên tìm thấy ngay trong 4 phép thử
tay:

    VÀO: Lien he thongtinchinhphu@chinhphu.vn hoac goi 0243.123.456
    RA : Liên hệ thống tin chính phủchinhphu.vn hoặc gọi 0243.123.456
                                   ↑ mất ký tự @, email vỡ

Nó đọc `thongtinchinhphu` như tiếng Việt không dấu và "sửa" thành "thống tin
chính phủ". Đúng loại lỗi đã loại mBART ở mức 86%.

Nên script này KHÔNG đo "dấu có tăng không" (câu trả lời gần như chắc là có).
Nó đo: **tăng dấu có đáng cái giá về định danh không.**

Chạy:
    uv run python scripts/probe_postcorrect.py
    uv run python scripts/probe_postcorrect.py --model protonx-legal-tc
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.metrics import (                                     # noqa: E402
    accent_share, cer, identifier_preservation, identifiers,
)
from ocr_lab.postcorrect import PostCorrector                     # noqa: E402

#: Ca thử có ĐÁP ÁN BIẾT TRƯỚC, gồm cả ca đối kháng.
#:
#: Mỗi ca là (tên, văn bản OCR sai, bản đúng). Ba nhóm:
#:   * nhóm 1 — model phải sửa được (phục hồi dấu)
#:   * nhóm 2 — model phải GIỮ NGUYÊN (định danh)
#:   * nhóm 3 — ca thật lấy từ đầu ra tesseract trên kho
CASES = [
    # ── nhóm 1: phục hồi dấu, đây là điểm mạnh ──────────────────────────
    ("dấu: luật lao động",
     "can cu bo luat lao dong 2019 va cac van ban huong dan thuc hien",
     "căn cứ bộ luật lao động 2019 và các văn bản hướng dẫn thực hiện"),
    ("dấu: ví dụ tác giả",
     "2.Trong Lut này các tù ng dui day dugc hiéu nhur sau",
     "2. Trong Luật này các từ ngữ dưới đây được hiểu như sau"),
    ("dấu: uỷ ban",
     "Uy ban nhan dan Thanh pho Ha Noi quyet dinh",
     "Ủy ban nhân dân Thành phố Hà Nội quyết định"),

    # ── nhóm 2: ĐỐI KHÁNG — định danh phải sống nguyên văn ──────────────
    ("đdanh: số hiệu văn bản",
     "Can cu Nghi dinh so 56/2026/ND-CP ngay 12/03/2026 cua Chinh phu",
     "Căn cứ Nghị định số 56/2026/NĐ-CP ngày 12/03/2026 của Chính phủ"),
    ("đdanh: EMAIL",
     "Lien he thongtinchinhphu@chinhphu.vn hoac goi 0243.123.456",
     "Liên hệ thongtinchinhphu@chinhphu.vn hoặc gọi 0243.123.456"),
    ("đdanh: email công ty",
     "Gui ho so den info@congty.com.vn truoc ngay 15/04/2026",
     "Gửi hồ sơ đến info@congty.com.vn trước ngày 15/04/2026"),
    ("đdanh: mã hồ sơ",
     "Ho so BQ96.US va NQ9001 da duoc tiep nhan",
     "Hồ sơ BQ96.US và NQ9001 đã được tiếp nhận"),
    ("đdanh: số tiền",
     "Tong gia tri hop dong la 1.234.567.890 dong",
     "Tổng giá trị hợp đồng là 1.234.567.890 đồng"),
    ("đdanh: nhiều số hiệu",
     "Theo QD 1656/QD-TTg va TT 03/2025/TT-BTC ngay 01/01/2025",
     "Theo QĐ 1656/QĐ-TTg và TT 03/2025/TT-BTC ngày 01/01/2025"),

    # ── nhóm 3: ca thật, tesseract đọc sai lẻ chứ không mất dấu ─────────
    ("thật: sai lẻ",
     "Tap 61, So 4B (2025): 128-138",
     "Tập 61, Số 4B (2025): 128-138"),
    ("thật: tên riêng nước ngoài",
     "Benzie, I. F., & Strain, J. J. (1996). The ferric reducing ability",
     "Benzie, I. F., & Strain, J. J. (1996). The ferric reducing ability"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="protonx-legal-tc",
                    help="tên thư mục trong models/")
    ap.add_argument("--num-beams", type=int, default=10)
    ap.add_argument("--out", default="reports/postcorrect_probe.json")
    args = ap.parse_args()

    model_dir = ROOT / "models" / args.model
    if not model_dir.exists():
        sys.exit(f"thiếu {model_dir}")

    pc = PostCorrector(model_dir, num_beams=args.num_beams, device="cpu")
    t0 = time.perf_counter()
    pc.ensure_ready()
    print(f"{args.model}: nạp {time.perf_counter() - t0:.1f}s, "
          f"num_beams={args.num_beams}, thiết bị CPU")
    if getattr(pc, "_tokenizer_fallback_reason", None):
        print(f"  (tokenizer dùng đường lui: "
              f"{pc._tokenizer_fallback_reason[:60]})")

    rows = []
    print(f"\n{'ca':<28}{'giây':>6}{'CER↓':>17}{'dấu↑':>17}{'đdanh':>7}")
    print(f"{'':<28}{'':>6}{'trước → sau':>17}{'trước → sau':>17}")
    print("─" * 78)

    for name, bad, good in CASES:
        t0 = time.perf_counter()
        fixed = pc.correct_chunk(bad)
        secs = time.perf_counter() - t0

        # So với BẢN ĐÚNG, không so với bản sai. Đây là điểm dễ nhầm: nếu so
        # sau/trước thì một model viết lại tuỳ ý cũng "thay đổi nhiều" và
        # trông như đang làm việc.
        cer_before, cer_after = cer(good, bad), cer(good, fixed)
        acc_before, acc_after = accent_share(bad), accent_share(fixed)
        # Định danh đo theo BẢN ĐÚNG → BẢN SỬA: câu hỏi là model có giữ được
        # định danh thật hay không.
        ident = identifier_preservation(good, fixed)
        # Và riêng phần model làm hỏng so với đầu vào của nó.
        ident_vs_input = identifier_preservation(bad, fixed)

        rows.append({
            "case": name, "input": bad, "output": fixed, "expected": good,
            "seconds": round(secs, 2),
            "cer_before": round(cer_before, 3),
            "cer_after": round(cer_after, 3),
            "accent_before": round(acc_before, 3),
            "accent_after": round(acc_after, 3),
            "identifier_vs_truth": round(ident, 3),
            "identifier_vs_input": round(ident_vs_input, 3),
            "identifiers_lost": sorted(
                set(identifiers(bad)) - set(identifiers(fixed))),
        })

        # CHỈ SỐ QUYẾT ĐỊNH LÀ `ident` (so với BẢN ĐÚNG), không phải
        # `ident_vs_input`. So với đầu vào sẽ phạt cả việc model làm ĐÚNG:
        # `56/2026/ND-CP` → `56/2026/NĐ-CP` là phục hồi chữ Đ, đúng việc nó
        # phải làm, nhưng so với đầu vào thì trông như "mất định danh".
        # Đo thật: 2/4 ca "hỏng" ban đầu thực ra là model sửa đúng.
        flag = "" if ident >= 0.99 else "  ⚠ LÀM HỎNG ĐỊNH DANH"
        if ident >= 0.99 > ident_vs_input:
            flag = "  (sửa dấu trong định danh — đúng)"
        print(f"{name:<28}{secs:>6.1f}"
              f"{cer_before:>8.3f} →{cer_after:>7.3f}"
              f"{acc_before:>8.3f} →{acc_after:>7.3f}"
              f"{ident:>7.3f}{flag}")

    # ── tổng kết ────────────────────────────────────────────────────────
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    n = len(rows)
    cer_b = sum(r["cer_before"] for r in rows) / n
    cer_a = sum(r["cer_after"] for r in rows) / n
    acc_b = sum(r["accent_before"] for r in rows) / n
    acc_a = sum(r["accent_after"] for r in rows) / n
    broke = [r for r in rows if r["identifier_vs_truth"] < 0.99]
    ident_pooled = sum(r["identifier_vs_truth"] for r in rows) / n
    fixed_accents_in_ids = sum(1 for r in rows
                               if r["identifier_vs_truth"] >= 0.99
                               > r["identifier_vs_input"])

    print("\n" + "=" * 78)
    print(f"CER    {cer_b:.3f} → {cer_a:.3f}   "
          f"({'giảm' if cer_a < cer_b else 'TĂNG'} "
          f"{abs(cer_a - cer_b) / max(cer_b, 1e-9):.0%})")
    print(f"dấu    {acc_b:.3f} → {acc_a:.3f}   (tiếng Việt thật ≈ 0,217)")
    print(f"định danh giữ được: {ident_pooled:.1%}   "
          f"— cổng chặn là 99%  (so với BẢN ĐÚNG)")
    if fixed_accents_in_ids:
        print(f"           trong đó {fixed_accents_in_ids} ca model PHỤC HỒI "
              f"dấu bên trong định danh (ND-CP → NĐ-CP) — tính là đúng")
    print(f"số lần phải lui về nguyên bản: {pc._fallbacks}/{n}")
    print("=" * 78)

    if broke:
        print(f"\n{len(broke)}/{n} ca BỊ LÀM HỎNG ĐỊNH DANH:")
        for r in broke:
            print(f"\n  [{r['case']}]  mất: {r['identifiers_lost']}")
            print(f"    vào: {r['input']}")
            print(f"    ra : {r['output']}")

    print(f"\nKẾT LUẬN: ", end="")
    if ident_pooled >= 0.99:
        print(f"QUA cổng định danh ({ident_pooled:.1%}) — đáng đo tiếp trên "
              f"corpus thật")
    else:
        print(f"TRƯỢT cổng định danh ({ident_pooled:.1%} < 99%).\n"
              f"  Giống hệt ca mBART đã bị loại ở 86%. Tỉ lệ dấu tăng không "
              f"bù được\n  việc làm vỡ định danh, vì đường lược danh tính "
              f"phía sau phụ thuộc vào chúng.")
    print(f"\nGhi: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
