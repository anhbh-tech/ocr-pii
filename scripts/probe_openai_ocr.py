"""Chạy thử OCR bằng API OpenAI trên ĐÚNG MỘT hồ sơ khách hàng.

VÌ SAO SCRIPT NÀY CHỈ LÀM MỘT HỒ SƠ
───────────────────────────────────
Không phải vì tiện, mà vì hai ràng buộc thật:

1. **Ảnh rời khỏi máy.** Mỗi ảnh gửi đi là một tài liệu khách hàng nằm trên
   máy chủ của bên thứ ba. Một lượt chạy "cho cả thư mục" là một quyết định
   về dữ liệu, không phải một phép đo — nên trần hồ sơ là BẮT BUỘC, đặt cứng
   trong mã, không phải một cờ có giá trị mặc định rộng rãi.

2. **Mỗi ảnh là tiền.** Vòng lặp lỗi trên 300 ảnh là một hoá đơn chứ không
   phải một lần chạy hỏng. `--max-images` mặc định 8 và script in ước tính
   chi phí TRƯỚC khi gửi bất cứ thứ gì.

VÌ SAO CHƯA CHẤM ĐIỂM ĐƯỢC
──────────────────────────
Cả 23 tệp trong `data/gold/truth/` đều RỖNG — chưa ai gõ đáp án. Không có
ground truth thì CER và tỉ lệ định danh không tính được, và script sẽ KHÔNG
bịa ra một con số nào.

Nên lượt này cho ra một thứ khác: bản nháp đọc được, kèm các chỉ số TỰ THÂN
(số ký tự, tỉ lệ dấu, các định danh bắt được) — đủ để mắt người xét xem có
đáng đi tiếp không. Tỉ lệ dấu có mốc so sánh: tiếng Việt thật ≈ 0,217.

Khi `truth/` đã được điền, script tự động chấm thêm CER + tỉ lệ định danh.

CHẠY:
    # xem trước, KHÔNG gửi gì cả
    uv run python scripts/probe_openai_ocr.py --dry-run

    # chạy thật, bỏ ảnh giấy tờ tuỳ thân
    uv run python scripts/probe_openai_ocr.py --skip-identity
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.engines import (                                     # noqa: E402
    EngineUnavailable, OpenAiVisionEngine, build_engine, load_dotenv,
)
from ocr_lab.metrics import (                                     # noqa: E402
    accent_share, cer, identifier_preservation, identifiers,
)

GOLD = ROOT / "data" / "gold"

#: Mốc hiệu chuẩn: tỉ lệ dấu của tiếng Việt THẬT, đo trên ground truth
#: MDPBench. Đầu ra thấp hơn hẳn mốc này nghĩa là engine đọc mất dấu — mà dấu
#: chính là thứ phân biệt tên người này với tên người kia.
VIETNAMESE_ACCENT_SHARE = 0.217

#: Giá mỗi 1 triệu token (USD), để ƯỚC TÍNH thôi. Bảng giá thay đổi; con số
#: này dùng để biết lượt chạy tốn cỡ xu hay cỡ đô, không phải để kế toán.
_PRICE_PER_MTOK = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
}


def _estimate_cost(model: str, prompt_tok: int, completion_tok: int) -> float | None:
    """Ước tính chi phí. Trả `None` khi không biết giá model — thà không nói
    gì còn hơn in ra một con số bịa."""
    price = _PRICE_PER_MTOK.get(model)
    if price is None:
        return None
    return prompt_tok / 1e6 * price[0] + completion_tok / 1e6 * price[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matter", required=True,
                    help="tiền tố hồ sơ trong gold set; bắt buộc — ảnh rời khỏi máy")
    ap.add_argument("--engine", default="openai",
                    help="đặc tả engine, vd openai:gpt-4o-mini@1200")
    ap.add_argument("--max-images", type=int, default=8,
                    help="trần số ảnh gửi đi — chặn hoá đơn bất ngờ")
    ap.add_argument("--skip-identity", action="store_true",
                    help="bỏ qua ảnh giấy tờ tuỳ thân (CCCD, hộ chiếu)")
    ap.add_argument("--dry-run", action="store_true",
                    help="chỉ liệt kê ảnh SẼ gửi, không gọi API")
    ap.add_argument("--out", default="reports/openai_probe.json")
    args = ap.parse_args()

    load_dotenv()

    manifest = json.loads((GOLD / "manifest.json").read_text("utf-8"))
    rows = [r for r in manifest if r["gold_name"].startswith(args.matter)]
    if not rows:
        have = sorted({r["gold_name"].split("__")[0] for r in manifest})
        print(f"không có hồ sơ {args.matter!r}; có: {', '.join(have)}",
              file=sys.stderr)
        return 2

    matter = rows[0]["matter"]

    # Dựng engine TRƯỚC khi in bất cứ thứ gì về chi phí: tên model thật nằm
    # trong engine (có thể đến từ .env), không nằm trong chuỗi đặc tả.
    # `ensure_ready` — tức là đòi khoá API — để sau, vì --dry-run phải chạy
    # được trên máy chưa có khoá.
    engine = build_engine(args.engine)

    # Script này báo cáo token và chi phí, mà chỉ engine đám mây mới đếm được
    # hai thứ đó. Chặn ở đây thay vì để `getattr(..., None)` âm thầm bỏ qua:
    # một lượt chạy không báo chi phí trông y hệt một lượt chạy miễn phí.
    if not isinstance(engine, OpenAiVisionEngine):
        print(f"{args.engine!r} không phải engine đám mây; script này chỉ "
              f"dùng cho engine gọi API. Engine cục bộ đo bằng "
              f"scripts/benchmark.py.", file=sys.stderr)
        return 2

    identity = [r for r in rows if r["kind"] == "giấy tờ tuỳ thân"]
    if args.skip_identity:
        rows = [r for r in rows if r["kind"] != "giấy tờ tuỳ thân"]

    rows = rows[:args.max_images]

    # ── nói rõ điều gì sắp xảy ra, TRƯỚC khi nó xảy ra ──────────────────────
    print(f"\nHồ sơ:  {matter}")
    print(f"Engine: {args.engine}")
    print(f"\n{len(rows)} ảnh SẼ ĐƯỢC GỬI tới máy chủ OpenAI:")
    total_mb = 0.0
    for r in rows:
        img = GOLD / "images" / r["gold_name"]
        mb = img.stat().st_size / 1e6 if img.exists() else 0.0
        total_mb += mb
        print(f"   {r['gold_name']:<45} {r['kind']:<18} {mb * 1000:>5.0f} KB")

    if identity:
        mark = "ĐÃ BỎ QUA" if args.skip_identity else "SẼ ĐƯỢC GỬI ĐI"
        print(f"\n   ⚠ {len(identity)} ảnh giấy tờ tuỳ thân — {mark}")
        for r in identity:
            print(f"     {r['gold_name']}")
        if not args.skip_identity:
            print("     (dùng --skip-identity để loại khỏi lượt chạy)")

    # Ước tính thô: ảnh ~1,1 MP ở detail=high tốn ~1 100 token đầu vào, đầu ra
    # ~700 token cho một trang chữ. Đủ để biết cỡ tiền, không hơn.
    #
    # Tên model phải lấy từ CHÍNH engine, không phải từ chuỗi đặc tả: `openai`
    # trơn lấy model từ .env, nên đoán theo đặc tả sẽ báo giá của model khác
    # với model thật sự được gọi.
    probe_model = engine.model
    est = _estimate_cost(probe_model, len(rows) * 1100, len(rows) * 700)
    print(f"\nModel: {probe_model}")
    if est is not None:
        print(f"Ước tính chi phí: ~{est:.3f} USD ({total_mb:.1f} MB ảnh)")
    else:
        print(f"(chưa có bảng giá cho {probe_model} — không ước tính chi phí)")

    if args.dry_run:
        print("\n--dry-run: KHÔNG gửi gì cả. Bỏ cờ này để chạy thật.")
        return 0

    try:
        engine.ensure_ready()
    except EngineUnavailable as exc:
        print(f"\nengine không dùng được: {exc}", file=sys.stderr)
        return 1

    print(f"\n{'ảnh':<45} {'giây':>6} {'ký tự':>7} {'dấu':>6} {'đdanh':>6}")
    print("─" * 76)

    out_rows = []
    for r in rows:
        img = GOLD / "images" / r["gold_name"]
        if not img.exists():
            print(f"{r['gold_name']:<45} thiếu tệp")
            continue

        res = engine.read_page(img)
        acc = accent_share(res.text)
        ids = identifiers(res.text)

        row = {
            "gold_name": r["gold_name"], "kind": r["kind"], "matter": matter,
            "engine": args.engine, "seconds": round(res.elapsed_ms / 1000, 1),
            "chars": len(res.text), "accent_share": round(acc, 3),
            "identifiers": ids, "warnings": res.warnings, "text": res.text,
        }

        # Chấm điểm CHỈ KHI có ground truth thật. Tệp rỗng = chưa ai gõ, và
        # chấm với chuỗi rỗng sẽ cho CER = 1,0 — một con số trông như kết quả
        # nhưng thực ra nói rằng ta chưa có đáp án.
        truth = GOLD / "truth" / f"{Path(r['gold_name']).stem}.txt"
        ref = truth.read_text("utf-8").strip() if truth.exists() else ""
        if ref:
            row["cer"] = round(cer(ref, res.text), 4)
            row["identifier_preservation"] = round(
                identifier_preservation(ref, res.text), 4)

        out_rows.append(row)

        ident = (f"{row['identifier_preservation']:>6.3f}"
                 if "identifier_preservation" in row else "     —")
        print(f"{r['gold_name'][:43]:<45} {row['seconds']:>6.1f} "
              f"{row['chars']:>7} {acc:>6.3f} {ident}")
        for w in res.warnings:
            print(f"    ⚠ {w}")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_rows, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    # ── tổng kết ────────────────────────────────────────────────────────────
    read = [r for r in out_rows if r["chars"] > 0]
    print("\n" + "═" * 76)
    print(f"Đọc được {len(read)}/{len(out_rows)} ảnh")

    if read:
        mean_acc = sum(r["accent_share"] for r in read) / len(read)
        print(f"Tỉ lệ dấu trung bình: {mean_acc:.3f} "
              f"(tiếng Việt thật ≈ {VIETNAMESE_ACCENT_SHARE})")
        if mean_acc < VIETNAMESE_ACCENT_SHARE * 0.6:
            print("   ⚠ thấp hơn hẳn mốc — engine đang làm MẤT DẤU, "
                  "hoặc ảnh vốn ít chữ tiếng Việt")

    scored = [r for r in out_rows if "cer" in r]
    if scored:
        mean_cer = sum(r["cer"] for r in scored) / len(scored)
        mean_id = sum(r["identifier_preservation"] for r in scored) / len(scored)
        print(f"CER trung bình: {mean_cer:.3f} · "
              f"định danh: {mean_id:.1%} trên {len(scored)} ảnh có đáp án")
        if mean_id < 0.99:
            print(f"   ⚠ KHÔNG QUA CỔNG: định danh {mean_id:.1%} < 99%")
    else:
        print("Chưa chấm điểm được: mọi tệp trong data/gold/truth/ đều RỖNG.")
        print("   Muốn có CER và tỉ lệ định danh thì phải gõ đáp án vào đó.")

    use = engine.usage
    cost = _estimate_cost(engine.model, use["prompt_tokens"],
                          use["completion_tokens"])
    print(f"\nToken: {use['prompt_tokens']:,} vào + "
          f"{use['completion_tokens']:,} ra"
          + (f" ≈ {cost:.3f} USD" if cost is not None else ""))
    print(f"Ghi: {out}")

    if not engine.keeps_data_on_device:
        print("\n⚠ Các ảnh trên đã rời khỏi máy và nằm trên máy chủ nhà cung cấp.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
