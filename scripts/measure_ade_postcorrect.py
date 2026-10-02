"""Đo xem lớp sửa chính tả protonX có đáng chồng lên ADE không.

KHÔNG GỌI API. Chỉ đọc `parse.json` đã có trong kho và chạy model cục bộ.

VÌ SAO MẶC ĐỊNH LÀ ĐO, KHÔNG PHẢI GHI
─────────────────────────────────────
Bằng chứng hiện có nói lớp này KHÔNG nên bật:

  1. ADE không mất dấu. Tỉ lệ dấu trên riêng những dòng thực sự là tiếng Việt
     (lọc bằng cấu trúc âm tiết) của 4 tài liệu CCCD: 0,202 · 0,216 · 0,229 ·
     0,237 — quanh mốc tiếng Việt thật 0,217, hai cái còn cao hơn.

  2. Đo trước đây trên đầu ra VLM: CER 0,254 → 0,267 và 0,185 → 0,188, tức
     XẤU ĐI, còn định danh không đổi. Một model phục hồi dấu đặt lên văn bản
     đã đủ dấu thì chỉ có thể thêm nhiễu.

Nên script này tồn tại để KIỂM CHỨNG lại kết luận đó trên dữ liệu ADE thật,
không phải để bật lớp sửa. `--write` có tồn tại, nhưng chỉ nên dùng sau khi
bảng dưới đây cho thấy cải thiện thật.

CỔNG: giữ lớp sửa chỉ khi CER giảm rõ rệt VÀ định danh giữ ≥ 99%.

CHẠY:
    uv run python scripts/measure_ade_postcorrect.py              # đo, không ghi
    uv run python scripts/measure_ade_postcorrect.py --force      # bỏ cổng dấu
    uv run python scripts/measure_ade_postcorrect.py --write      # ghi corrected.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.postcorrect import DEFAULT_MODEL_DIR                # noqa: E402
from ocr_lab.ade_postcorrect import (                              # noqa: E402
    ACCENT_FLOOR, ACCENT_TARGET, correct_parse, save_corrections,
)
from ocr_lab.ade_store import DEFAULT_STORE                        # noqa: E402
from ocr_lab.correction_audit import (                             # noqa: E402
    classify_change, diff_words, strip_tone,
)
from ocr_lab.metrics import accent_share                           # noqa: E402

#: Cổng định danh. Không nới cho bất kỳ model nào: một corrector từng đạt 86%
#: và đã bị loại dù cải thiện dấu.
IDENTIFIER_GATE = 0.99


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--model", default=Path(DEFAULT_MODEL_DIR).name,
                    help="thư mục model trong models/")
    ap.add_argument("--doc", default="", help="chỉ chạy một doc_id")
    ap.add_argument("--floor", type=float, default=ACCENT_FLOOR)
    ap.add_argument("--num-beams", type=int, default=10)
    ap.add_argument("--force", action="store_true",
                    help="bỏ cổng mật độ dấu — để kiểm cổng đặt đúng chỗ chưa")
    ap.add_argument("--write", action="store_true",
                    help="GHI corrected.json (mặc định chỉ đo)")
    args = ap.parse_args()

    if not args.store.exists():
        print(f"kho trống: {args.store}", file=sys.stderr)
        return 2

    docs = [d for d in sorted(args.store.iterdir())
            if (d / "parse.json").is_file()
            and (not args.doc or d.name == args.doc)]
    if not docs:
        print("không có tài liệu nào trong kho", file=sys.stderr)
        return 2

    model_dir = ROOT / "models" / args.model
    if not model_dir.exists():
        print(f"không thấy model: {model_dir}", file=sys.stderr)
        return 2

    print(f"\nKho   : {args.store}")
    print(f"Model : {args.model}")
    print(f"Cổng  : dấu < {args.floor:.3f} mới sửa "
          f"(mốc tiếng Việt {ACCENT_TARGET})"
          + ("  [BỎ QUA vì --force]" if args.force else ""))
    print(f"Chế độ: {'GHI corrected.json' if args.write else 'CHỈ ĐO, không ghi'}")

    # Nạp model MỘT LẦN cho cả lượt — nạp lại mỗi tài liệu là ~5 s mỗi lần.
    from ocr_lab.postcorrect import PostCorrector
    corrector = PostCorrector(model_dir, num_beams=args.num_beams)

    print(f"\n{'tài liệu':<26} {'chunk':>6} {'sửa':>5} {'bỏ':>4} "
          f"{'thanh điệu':>11} {'đổi chữ':>8} {'nuốt dòng':>10} {'đdanh':>7}")
    print("─" * 82)

    rows = []
    all_changes = []
    for d in docs:
        parse = json.loads((d / "parse.json").read_text("utf-8"))
        meta = json.loads((d / "meta.json").read_text("utf-8"))
        name = Path(meta.get("source", d.name)).name

        res = correct_parse(parse, corrector, doc_id=d.name,
                            floor=args.floor, force=args.force)

        # Phân loại TỪNG thay đổi thay vì lấy trung bình accent_share.
        #
        # accent_share đếm SỐ LƯỢNG dấu, không đếm dấu ĐÚNG hay SAI:
        # 'điện tứ' và 'điện tử' cho cùng một con số. Dùng nó để kết luận thì
        # một corrector sửa đúng thanh điệu sẽ bị báo là "không cải thiện" —
        # đúng lỗi đã suýt mắc ở lượt đo trước.
        changes = [classify_change(c.original, c.corrected)
                   for c in res.chunks if c.changed]
        all_changes.extend(changes)
        n_tone = sum(c.n_tone for c in changes)
        n_char = sum(c.n_char for c in changes)
        n_space = sum(c.n_space for c in changes)

        print(f"{name[:24]:<26} {len(res.chunks):>6} {res.n_changed:>5} "
              f"{len(res.skipped):>4} {n_tone:>11} {n_char:>8} {n_space:>10} "
              f"{res.identifier_preservation:>7.3f}")

        rows.append({"doc": name, "doc_id": d.name,
                     "n_chunks": len(res.chunks), "n_changed": res.n_changed,
                     "n_skipped": len(res.skipped),
                     "n_tone_fix": n_tone, "n_char_edit": n_char,
                     "n_newline_eaten": n_space,
                     "identifier_preservation": res.identifier_preservation,
                     "seconds": res.elapsed_ms / 1000})
        if args.write:
            save_corrections(args.store, d.name, res)

        # In TỪNG TỪ đã đổi, không in cả đoạn: mắt người không tìm ra chỗ khác
        # nhau trong một đoạn 60 ký tự.
        for ch in changes:
            for wb, wa in diff_words(" ".join(ch.before.split()),
                                     " ".join(ch.after.split()))[:3]:
                tone = wb and wa and strip_tone(wb) == strip_tone(wa)
                print(f"      {'dấu' if tone else 'chữ'}  "
                      f"{wb[:28]!r} → {wa[:28]!r}")

    # ── kết luận ────────────────────────────────────────────────────────────
    print("\n" + "═" * 82)
    total_chunks = sum(r["n_chunks"] for r in rows)
    total_changed = sum(r["n_changed"] for r in rows)
    total_skipped = sum(r["n_skipped"] for r in rows)
    print(f"{total_chunks} chunk · model đổi {total_changed} · "
          f"cổng bỏ qua {total_skipped}")

    if total_changed == 0:
        print("\nKẾT LUẬN: model KHÔNG đổi gì.")
        if total_skipped:
            print("  Cổng mật độ dấu đã chặn mọi chunk — nghĩa là ADE không "
                  "mất dấu,\n  và không có việc gì cho lớp sửa làm.")
            print("  Chạy lại với --force để xem model làm gì khi bị ép.")
        return 0

    ident = min(r["identifier_preservation"] for r in rows)
    tone = sum(r["n_tone_fix"] for r in rows)
    char = sum(r["n_char_edit"] for r in rows)
    space = sum(r["n_newline_eaten"] for r in rows)

    print(f"Sửa thanh điệu : {tone:>3}   ← việc model làm ĐÚNG")
    print(f"Đổi chữ        : {char:>3}   ← phải xem từng ca bằng mắt")
    print(f"Nuốt xuống dòng: {space:>3}   ← THIỆT HẠI: mất ranh giới trường")
    print(f"Định danh thấp nhất: {ident:.3f}")

    print()
    if ident < IDENTIFIER_GATE:
        print(f"KHÔNG QUA CỔNG: định danh {ident:.1%} < {IDENTIFIER_GATE:.0%}")
        print("  → KHÔNG bật. Mất dấu rẻ hơn vỡ một số hiệu.")
    elif tone == 0:
        print("KHÔNG có lỗi thanh điệu nào được sửa.")
        print("  → Lớp này không có việc để làm trên dữ liệu ADE.")
    elif space > tone:
        print(f"Sửa được {tone} thanh điệu nhưng nuốt {space} xuống dòng.")
        print("  → Thiệt hại cấu trúc nhiều hơn cái được. Cần chặn phần nuốt")
        print("    dòng trước (giữ nguyên `\\n` của bản gốc) rồi đo lại.")
    else:
        print(f"Sửa được {tone} lỗi thanh điệu, định danh nguyên vẹn.")
        print("  → ĐÁNG dùng, nhưng phải chặn phần nuốt xuống dòng.")
        print("    Bước tiếp: giữ nguyên `\\n` của bản gốc sau khi model trả về.")

    print("\nLƯU Ý VỀ THƯỚC ĐO: bảng này KHÔNG dùng accent_share, vì nó đếm")
    print("SỐ LƯỢNG dấu chứ không đếm dấu ĐÚNG/SAI — 'điện tứ' và 'điện tử'")
    print("cho cùng một con số, nên nó mù với đúng loại lỗi cần sửa ở đây.")

    out = ROOT / "reports" / "ade_postcorrect.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\nGhi: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
