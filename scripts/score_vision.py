"""Chấm điểm đầu ra Apple Vision bằng đúng bộ đo của dự án.

VÌ SAO ĐO APPLE VISION DÙ NÓ KHÔNG TRIỂN KHAI ĐƯỢC LÊN NAS
──────────────────────────────────────────────────────────
Ràng buộc số 0 của dự án: đích là NAS chỉ có CPU, nên Apple Vision (macOS +
Neural Engine) **không phải ứng viên triển khai**. Điều đó không đổi.

Nhưng nó trả lời được hai câu hỏi mà không engine nào khác trả lời được:

1. **Trần chất lượng của bộ dữ liệu này là bao nhiêu?** Nếu một engine hạng
   nhất cũng chỉ đạt CER 0,3 trên lát ảnh chụp MDPBench thì con số 0,361 của
   VLM không phải "model kém" mà là "bộ này khó". Không có mốc đó thì ta
   không biết còn bao nhiêu dư địa để cải thiện.

2. **Lỗi nào là lỗi của ENGINE, lỗi nào là của ẢNH?** Trang nào cả Vision lẫn
   VLM đều đọc trượt thì gần như chắc chắn ảnh hỏng, không phải engine dở.

Đây là vai trò "công cụ đối chiếu khi phát triển" mà kế hoạch gốc đã dành cho
Vision — không phải ứng viên, mà là cái thước.

PHÁT HIỆN NGƯỢC VỚI GIẢ ĐỊNH: Vision CÓ model tiếng Việt (`vi-Latn-VT`, 1
trong 30 ngôn ngữ). Vậy câu hỏi thật không phải "nó có đọc được tiếng Việt
không" mà là "khai ngôn ngữ có hơn để nó tự nhận không" — HideMyData dùng
`automaticallyDetectsLanguage = true` và không khai gì cả.

Chạy:
    swift/vision_ocr <thư mục ảnh> > ra.json
    uv run python scripts/score_vision.py ra.json --label "tự nhận"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.language import detect_language                      # noqa: E402
from ocr_lab.metrics import (                                     # noqa: E402
    accent_share, identifiers, levenshtein, normalize_for_compare,
)

BENCH = ROOT / "data" / "benchmarks" / "mdpbench"


def _ground_truth(page: dict) -> str:
    """Header lên đầu, footer xuống cuối — giống `scripts/benchmark.py`."""
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
    ap.add_argument("results", nargs="+",
                    help="tệp JSON do swift/vision_ocr sinh ra")
    ap.add_argument("--label", action="append", default=[],
                    help="nhãn cho từng tệp, theo thứ tự")
    ap.add_argument("--out", default="reports/vision_scores.json")
    args = ap.parse_args()

    pages = {p["page_info"]["image_path"]: p
             for p in json.loads(
                 (BENCH / "vietnamese_pages.json").read_text("utf-8"))}

    summaries = []
    for idx, path in enumerate(args.results):
        label = args.label[idx] if idx < len(args.label) else Path(path).stem
        rows = json.loads(Path(path).read_text("utf-8"))

        edits = ref_chars = 0
        ids_total = ids_kept = 0
        acc_ref = acc_hyp = alpha_ref = alpha_hyp = 0
        seconds = []
        langs = Counter()
        per_page = []

        for r in rows:
            page = pages.get(r["page"])
            if not page:
                continue
            ref = _ground_truth(page)
            hyp = r["text"]

            nref = normalize_for_compare(ref)
            ref_chars += len(nref)
            edits += levenshtein(nref, normalize_for_compare(hyp))

            rc, hc = Counter(identifiers(ref)), Counter(identifiers(hyp))
            ids_total += sum(rc.values())
            ids_kept += sum(min(c, hc[t]) for t, c in rc.items())

            ra = [c for c in ref if c.isalpha()]
            ha = [c for c in hyp if c.isalpha()]
            alpha_ref += len(ra)
            alpha_hyp += len(ha)
            acc_ref += accent_share(ref) * len(ra)
            acc_hyp += accent_share(hyp) * len(ha)

            seconds.append(r["seconds"])
            langs[detect_language(hyp).language.value] += 1
            per_page.append({
                "page": r["page"],
                "cer": round(levenshtein(nref, normalize_for_compare(hyp))
                             / max(len(nref), 1), 4),
                "accent": round(accent_share(hyp), 3),
                "coverage": round(len(hyp) / max(len(ref), 1), 2),
                "seconds": r["seconds"],
            })

        n = len(seconds)
        summaries.append({
            "label": label, "pages": n,
            "cer": round(edits / ref_chars, 4) if ref_chars else None,
            "identifier_preservation": (round(ids_kept / ids_total, 4)
                                        if ids_total else None),
            "accent_ref": round(acc_ref / alpha_ref, 3) if alpha_ref else None,
            "accent_hyp": round(acc_hyp / alpha_hyp, 3) if alpha_hyp else None,
            "seconds_median": round(sorted(seconds)[n // 2], 2) if n else None,
            "languages_detected": dict(langs),
            "per_page": per_page,
        })

    print(f"{'cấu hình':<24}{'CER':>8}{'dấu':>8}{'đdanh':>8}{'giây':>8}"
          f"  ngôn ngữ nhận được")
    print("=" * 82)
    ref_acc = summaries[0]["accent_ref"] if summaries else None
    if ref_acc:
        print(f"{'(bản gốc)':<24}{'—':>8}{ref_acc:>8.3f}{'—':>8}{'—':>8}"
              f"  mốc tiếng Việt thật")
    for s in summaries:
        print(f"{s['label']:<24}{s['cer']:>8.3f}{s['accent_hyp']:>8.3f}"
              f"{s['identifier_preservation']:>8.3f}{s['seconds_median']:>8.2f}"
              f"  {s['languages_detected']}")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summaries, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\nGhi: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
