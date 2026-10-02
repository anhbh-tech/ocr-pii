"""Hiệu chuẩn ngưỡng nhận dạng ngôn ngữ trên ground truth THẬT.

Ngưỡng đoán là cách sai lầm đã mắc một lần trong dự án này: ngưỡng 600 ký tự
trong `classify.py` được đoán, và nó xếp nhầm 6 trang tỷ giá. Lần này đo trước.

Dùng ground truth MDPBench (người gán nhãn, không phải đầu ra OCR) làm dữ liệu
hiệu chuẩn. Ba lát quan trọng:

    Vietnamese   — phải nhận đúng
    english      — không được nhận nhầm thành vi
    Indonesian   — CA ĐỐI KHÁNG: cũng Latin, cũng không dấu, cấu trúc âm tiết
                   gần giống tiếng Việt. Nếu tách được lát này thì ngưỡng vững.

Và quan trọng nhất: lát Vietnamese ĐÃ GỠ SẠCH DẤU. Đây là mô phỏng đúng lỗi
tesseract trên kho thật (tỉ lệ dấu tụt từ 0,217 xuống 0,08). Chỉ số cấu trúc
âm tiết phải giữ nguyên giá trị qua phép gỡ dấu này, nếu không nó vô dụng.

Chạy:
    uv run python scripts/calibrate_language.py
"""

from __future__ import annotations

import json
import sys
import unicodedata as ud
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.language import vietnamese_syllable_share          # noqa: E402
from ocr_lab.metrics import accent_share                        # noqa: E402

GT = ROOT / "data" / "benchmarks" / "mdpbench" / "MDPBench_public.json"
SLICES = ["Vietnamese", "english", "Indonesian", "French", "Portuguese"]


def _page_texts(pages: list[dict]) -> list[str]:
    """Ghép văn bản mỗi trang theo thứ tự đọc, giống đầu ra OCR một trang."""
    out = []
    for p in pages:
        # `order` có thể là None (khối không nằm trong luồng đọc chính, ví dụ
        # chú thích hình) — `.get(d, 0)` không cứu được vì key CÓ tồn tại,
        # giá trị mới là None. Đẩy chúng xuống cuối.
        parts = [d["text"] for d in sorted(
                     p.get("layout_dets", []),
                     key=lambda d: (d.get("order") is None, d.get("order") or 0))
                 if d.get("text")]
        if parts:
            out.append("\n".join(parts))
    return out


def _strip_all_accents(text: str) -> str:
    """Mô phỏng OCR nuốt sạch dấu — đúng lỗi tesseract trên kho thật."""
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in ud.normalize("NFD", text) if not ud.combining(c))


def main() -> int:
    if not GT.exists():
        print(f"thiếu {GT}\nchạy: uv run python scripts/fetch_mdpbench.py",
              file=sys.stderr)
        return 1

    data = json.loads(GT.read_text(encoding="utf-8"))
    by_lang: dict[str, list[dict]] = {}
    for p in data:
        lang = p.get("page_info", {}).get("page_attribute", {}).get("language")
        by_lang.setdefault(lang, []).append(p)

    print(f"{'lát':<26} {'trang':>5} {'dấu':>7} {'âm tiết VN':>11}")
    print("─" * 54)

    results = {}
    for lang in SLICES:
        pages = by_lang.get(lang)
        if not pages:
            continue
        texts = _page_texts(pages)
        joined = "\n".join(texts)
        acc = accent_share(joined)
        syl = vietnamese_syllable_share(joined)
        results[lang] = (acc, syl, texts)
        print(f"{lang:<26} {len(texts):>5} {acc:>7.3f} {syl:>11.3f}")

    # Ca quyết định: tiếng Việt mất sạch dấu.
    vi_texts = results["Vietnamese"][2]
    stripped = _strip_all_accents("\n".join(vi_texts))
    acc_s = accent_share(stripped)
    syl_s = vietnamese_syllable_share(stripped)
    print(f"{'Vietnamese (gỡ hết dấu)':<26} {len(vi_texts):>5} "
          f"{acc_s:>7.3f} {syl_s:>11.3f}")

    print("\n── điểm quyết định ──")
    vi_acc, vi_syl, _ = results["Vietnamese"]
    print(f"dấu tụt {vi_acc:.3f} → {acc_s:.3f}  "
          f"(mọi cách dựa vào dấu đều sập ở đây)")
    print(f"âm tiết giữ {vi_syl:.3f} → {syl_s:.3f}  "
          f"(chênh {abs(vi_syl - syl_s):.3f} — phải gần 0)")

    others = {k: v[1] for k, v in results.items() if k != "Vietnamese"}
    if others:
        hardest = max(others, key=lambda k: others[k])
        gap = syl_s - others[hardest]
        print(f"\nlát ngoại khó nhất: {hardest} = {others[hardest]:.3f}")
        print(f"khoảng cách tới tiếng Việt mất dấu: {gap:.3f}")
        mid = (syl_s + others[hardest]) / 2
        print(f"ngưỡng nên đặt ở khoảng: {mid:.2f}")
        if gap < 0.15:
            print("  ⚠️  khoảng cách hẹp — chỉ số này không đủ tách bạch",
                  file=sys.stderr)

    # Phân bố theo TRANG, không chỉ theo tổng: một trang lệch cũng làm hỏng
    # đường định tuyến của trang đó.
    print("\n── theo từng trang (âm tiết VN) ──")
    print(f"{'lát':<26} {'p05':>6} {'trung vị':>9} {'p95':>6}")
    for lang, (_, _, texts) in results.items():
        vals = sorted(vietnamese_syllable_share(t) for t in texts
                      if len(t.split()) >= 8)
        if vals:
            n = len(vals)
            print(f"{lang:<26} {vals[n // 20]:>6.3f} "
                  f"{vals[n // 2]:>9.3f} {vals[min(n - 1, n * 19 // 20)]:>6.3f}")
    vals = sorted(vietnamese_syllable_share(_strip_all_accents(t))
                  for t in vi_texts if len(t.split()) >= 8)
    n = len(vals)
    print(f"{'Vietnamese (gỡ dấu)':<26} {vals[n // 20]:>6.3f} "
          f"{vals[n // 2]:>9.3f} {vals[min(n - 1, n * 19 // 20)]:>6.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
