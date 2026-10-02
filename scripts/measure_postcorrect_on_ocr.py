"""Đo hậu xử lý trên ĐẦU RA OCR THẬT, không phải trên câu tự soạn.

VÌ SAO PHẢI CÓ SCRIPT RIÊNG
───────────────────────────
`probe_postcorrect.py` chạy trên 11 câu tự soạn và cho kết quả rất đẹp: CER
0,163 → 0,000, định danh 100%. Nhưng những câu đó do chính ta viết ra, và ta
vô thức viết chúng giống dữ liệu huấn luyện của model — văn phong hành chính,
lỗi kiểu "mất dấu đều".

Đầu ra OCR thật hỏng theo cách khác hẳn: chữ dính nhau, ký tự lạ, dòng lộn
xộn, mất nguyên đoạn. Câu hỏi thật là: **model có cứu được loại hỏng đó
không**, hay nó chỉ giỏi trên loại lỗi sạch sẽ mà ta tự nghĩ ra.

Dùng đầu ra tesseract và VLM đã lưu trong `reports/pages_*.json`? KHÔNG —
những tệp đó chỉ lưu điểm số, không lưu văn bản. Nên script này chạy lại OCR,
rồi đo trước/sau hậu xử lý trên cùng trang.

Chạy:
    uv run python scripts/measure_postcorrect_on_ocr.py --engine tesseract --limit 8
    uv run python scripts/measure_postcorrect_on_ocr.py --engine paddleocr-vl --limit 4
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.engines import EngineUnavailable, build_engine        # noqa: E402
from ocr_lab.metrics import (                                      # noqa: E402
    accent_share, cer, identifier_preservation, identifiers, levenshtein,
    normalize_for_compare,
)
from ocr_lab.postcorrect import PostCorrector                      # noqa: E402

BENCH = ROOT / "data" / "benchmarks" / "mdpbench"


def _ground_truth(page: dict) -> str:
    """Header lên đầu, footer xuống cuối — xem `scripts/benchmark.py`."""
    header, body, footer = [], [], []
    for det in page.get("layout_dets", []):
        if not det.get("text"):
            continue
        if det.get("order") is None:
            (footer if det.get("category_type") == "footer"
             else header).append(det["text"])
        else:
            body.append((det["order"], det["text"]))
    return "\n".join(header + [t for _, t in sorted(body)] + footer)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", default="tesseract")
    ap.add_argument("--model", default="protonx-legal-tc")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--num-beams", type=int, default=10)
    ap.add_argument("--out", default="reports/postcorrect_on_ocr.json")
    args = ap.parse_args()

    pages = json.loads(
        (BENCH / "vietnamese_pages.json").read_text("utf-8"))[:args.limit]

    try:
        engine = build_engine(args.engine)
        engine.ensure_ready()
    except EngineUnavailable as exc:
        sys.exit(f"{args.engine} không dùng được: {exc}")

    pc = PostCorrector(ROOT / "models" / args.model,
                       num_beams=args.num_beams, device="cpu")
    t0 = time.perf_counter()
    pc.ensure_ready()
    print(f"engine {args.engine} · hậu xử lý {args.model} "
          f"(nạp {time.perf_counter() - t0:.1f}s) · CPU\n")

    print(f"{'trang':<38}{'CER':>15}{'dấu':>15}{'đdanh':>15}{'giây':>7}")
    print(f"{'':<38}{'trước → sau':>15}{'trước → sau':>15}"
          f"{'trước → sau':>15}")
    print("─" * 92)

    rows = []
    # Cộng dồn theo trọng số — trung bình các tỉ lệ cho một trang 5 ký tự
    # cùng sức nặng với trang 2 000 ký tự.
    agg = {"edits_before": 0, "edits_after": 0, "ref_chars": 0,
           "ids_total": 0, "ids_before": 0, "ids_after": 0}

    for page in pages:
        name = page["page_info"]["image_path"]
        img = BENCH / "images" / name
        if not img.exists():
            continue

        ref = _ground_truth(page)
        res = engine.read_page(img)
        if any("CHẠM TRẦN" in w for w in res.warnings):
            print(f"{name[:36]:<38}  BỎ — OCR bị cắt, không đo được")
            continue

        raw = res.text
        t0 = time.perf_counter()
        fixed = pc.correct(raw)
        pc_secs = time.perf_counter() - t0

        cer_b, cer_a = cer(ref, raw), cer(ref, fixed.text)
        acc_b, acc_a = accent_share(raw), accent_share(fixed.text)
        id_b = identifier_preservation(ref, raw)
        id_a = identifier_preservation(ref, fixed.text)

        nref = normalize_for_compare(ref)
        agg["ref_chars"] += len(nref)
        agg["edits_before"] += levenshtein(nref, normalize_for_compare(raw))
        agg["edits_after"] += levenshtein(nref,
                                          normalize_for_compare(fixed.text))
        from collections import Counter
        rc = Counter(identifiers(ref))
        agg["ids_total"] += sum(rc.values())
        for hyp, key in ((raw, "ids_before"), (fixed.text, "ids_after")):
            hc = Counter(identifiers(hyp))
            agg[key] += sum(min(c, hc[t]) for t, c in rc.items())

        rows.append({
            "page": name, "engine": args.engine,
            "cer_before": round(cer_b, 4), "cer_after": round(cer_a, 4),
            "accent_before": round(acc_b, 3), "accent_after": round(acc_a, 3),
            "identifier_before": round(id_b, 4),
            "identifier_after": round(id_a, 4),
            "chunks": fixed.chunks_total, "changed": fixed.chunks_changed,
            "postcorrect_seconds": round(pc_secs, 1),
            "ocr_seconds": round(res.elapsed_ms / 1000, 1),
        })

        arrow = "↓" if cer_a < cer_b else ("↑" if cer_a > cer_b else "=")
        print(f"{name[:36]:<38}"
              f"{cer_b:>6.3f} →{cer_a:>6.3f}{arrow}"
              f"{acc_b:>7.3f} →{acc_a:>6.3f}"
              f"{id_b:>7.3f} →{id_a:>6.3f}"
              f"{pc_secs:>7.1f}")

        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    if not rows:
        print("không đo được trang nào")
        return 1

    # ── tổng kết, cộng dồn theo trọng số ────────────────────────────────
    cer_b = agg["edits_before"] / agg["ref_chars"]
    cer_a = agg["edits_after"] / agg["ref_chars"]
    id_b = agg["ids_before"] / agg["ids_total"] if agg["ids_total"] else 1.0
    id_a = agg["ids_after"] / agg["ids_total"] if agg["ids_total"] else 1.0
    acc_b = sum(r["accent_before"] for r in rows) / len(rows)
    acc_a = sum(r["accent_after"] for r in rows) / len(rows)
    ocr_s = sum(r["ocr_seconds"] for r in rows) / len(rows)
    pc_s = sum(r["postcorrect_seconds"] for r in rows) / len(rows)

    print("\n" + "=" * 92)
    print(f"{len(rows)} trang · engine {args.engine} + {args.model}")
    print("=" * 92)
    print(f"CER          {cer_b:.3f} → {cer_a:.3f}   "
          f"({'giảm' if cer_a < cer_b else 'TĂNG'} "
          f"{abs(cer_a - cer_b) / max(cer_b, 1e-9):.0%})")
    print(f"tỉ lệ dấu    {acc_b:.3f} → {acc_a:.3f}   "
          f"(tiếng Việt thật ≈ 0,217)")
    print(f"định danh    {id_b:.3f} → {id_a:.3f}   — cổng chặn 0,99")
    print(f"thời gian    OCR {ocr_s:.1f}s + hậu xử lý {pc_s:.1f}s "
          f"= {ocr_s + pc_s:.1f}s/trang")
    print(f"lui về nguyên bản: {pc._fallbacks} đoạn")

    print("\nKẾT LUẬN: ", end="")
    if id_a < 0.99:
        print(f"định danh sau hậu xử lý {id_a:.1%} < 99% — TRƯỢT cổng.")
        if id_a >= id_b:
            print("  Lưu ý: hậu xử lý KHÔNG làm tình hình xấu đi "
                  f"({id_b:.1%} → {id_a:.1%}); phần thiếu là do OCR đọc trượt "
                  "từ đầu,\n  mà model sửa lỗi thì 'cannot restore missing "
                  "semantic content' (tác giả tự nêu).")
    elif cer_a < cer_b:
        print(f"QUA cổng và CER giảm {(cer_b - cer_a) / cer_b:.0%} — "
              f"đáng đưa vào pipeline.")
    else:
        print("qua cổng nhưng CER không giảm — không đáng thêm bước.")
    print(f"\nGhi: {ROOT / args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
