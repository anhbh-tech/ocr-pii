"""Chạy ADE trên kho hồ sơ khách hàng, ghi kết quả vào kho cục bộ.

VÌ SAO CHỈ GỬI TRANG CẦN OCR
────────────────────────────
Đo thật trên kho: 1.163 trang PDF, nhưng chỉ **333 trang (29%) là bản quét**
cần đọc bằng OCR — 825 trang còn lại có sẵn text layer, đọc thẳng được.

Lọc trước khi gửi tiết kiệm nhiều hơn mọi lựa chọn model cộng lại, và quan
trọng hơn: mỗi trang không gửi là một trang tài liệu khách hàng KHÔNG rời khỏi
máy. Đây là lý do bảo mật, không chỉ lý do tiền.

VÌ SAO BỎ QUA TÀI LIỆU ĐÃ CÓ TRONG KHO
──────────────────────────────────────
Chạy lại là chuyện thường (thêm hồ sơ, sửa script, máy mất mạng giữa chừng).
Không chặn thì mỗi lần chạy lại là trả tiền lần nữa cho đúng những trang đã
đọc xong — và không có gì báo cho ta biết điều đó.

`--force` để ghi đè có chủ ý.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.ade_store import (                                    # noqa: E402
    DEFAULT_STORE, doc_id_for, render_pages, save_result,
)
from ocr_lab.engines import (                                      # noqa: E402
    AdeEngine, EngineUnavailable, load_dotenv,
)

#: Thư mục hồ sơ khách hàng. Ngoài cây dự án, quyền 700.
PRIVATE = Path.home() / ".private" / "refiny_data"

#: 1 credit = 1 xu Mỹ (docs.landing.ai). Hằng số của nhà cung cấp.
USD_PER_CREDIT = 0.01

#: Đuôi tệp engine đọc được.
SUPPORTED = {".pdf", ".jpg", ".jpeg", ".png"}


def needs_ocr_pages(path: Path) -> list[int] | None:
    """Trang nào của PDF này cần OCR (1-indexed). `None` nghĩa là không phải PDF.

    Phân loại theo TỪNG TRANG, không theo tệp: một PDF thường trộn lẫn trang
    số hoá sẵn với trang quét, và đuôi tệp không nói lên điều gì.
    """
    if path.suffix.lower() != ".pdf":
        return None
    from ocr_lab.classify import classify_pdf
    res = classify_pdf(path)
    return [p.index + 1 for p in res.pages if p.needs_ocr]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=PRIVATE)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--pattern", default="",
                    help="chỉ xử lý tệp có chuỗi này trong đường dẫn")
    ap.add_argument("--model", default="dpt-3-verity")
    ap.add_argument("--tier", default="standard",
                    choices=("standard", "priority"))
    ap.add_argument("--max-files", type=int, default=2,
                    help="trần số TỆP — đây là dữ liệu thật, và mỗi tệp là tiền")
    ap.add_argument("--max-credits", type=float, default=50.0,
                    help="dừng khi vượt ngưỡng credits (chặn hoá đơn bất ngờ)")
    ap.add_argument("--force", action="store_true",
                    help="chạy lại cả tài liệu đã có trong kho (TRẢ TIỀN LẠI)")
    ap.add_argument("--all-pages", action="store_true",
                    help="gửi cả trang có text layer (mặc định: chỉ trang quét)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_dotenv()

    if not args.root.exists():
        print(f"không có thư mục {args.root}", file=sys.stderr)
        return 2

    # ── lập kế hoạch ────────────────────────────────────────────────────────
    plan: list[tuple[Path, str, list[int] | None, bool]] = []
    skipped_done = 0

    for p in sorted(args.root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED:
            continue
        rel = str(p.relative_to(args.root))
        if args.pattern and args.pattern.lower() not in rel.lower():
            continue

        did = doc_id_for(rel)
        if (args.store / did / "parse.json").exists() and not args.force:
            skipped_done += 1
            continue

        scan_pages = None if args.all_pages else needs_ocr_pages(p)
        # PDF không có trang nào cần OCR ⇒ bỏ hẳn, không tốn lần gọi nào.
        if scan_pages is not None and not scan_pages:
            continue

        plan.append((p, rel, scan_pages, p.suffix.lower() == ".pdf"))
        if len(plan) >= args.max_files:
            break

    if not plan:
        print(f"không có tài liệu nào cần xử lý"
              + (f" ({skipped_done} tệp đã có trong kho)" if skipped_done else ""))
        return 0

    # ── báo trước khi gửi ───────────────────────────────────────────────────
    print(f"\nNguồn : {args.root}")
    print(f"Kho   : {args.store}")
    print(f"Model : {args.model} · tier {args.tier}")
    if skipped_done:
        print(f"\n{skipped_done} tệp đã có trong kho — bỏ qua (dùng --force để chạy lại)")

    print(f"\n{len(plan)} tài liệu SẼ ĐƯỢC GỬI tới máy chủ LandingAI:\n")
    for p, rel, scan_pages, is_pdf in plan:
        mb = p.stat().st_size / 1e6
        note = (f"{len(scan_pages)} trang quét" if scan_pages
                else "cả tệp" if is_pdf else "ảnh")
        print(f"   {rel[:66]:<68} {note:<15} {mb * 1000:>5.0f} KB")

    # Ước tính: Verity/standard = 0,15/trang + 0,1 mỗi 1.000 ký tự. Trang giấy
    # tờ thường ~1.000 ký tự ⇒ ~0,3 credits. Đo thật trên CCCD: đúng 0,3.
    est_pages = sum(len(sp) if sp else 1 for _, _, sp, _ in plan)
    est = est_pages * 0.3
    print(f"\nƯớc tính: ~{est_pages} trang × 0,3 = {est:.1f} credits "
          f"≈ ${est * USD_PER_CREDIT:.3f}")

    print("\n⚠ Đây là HỒ SƠ KHÁCH HÀNG THẬT. Chạy tiếp nghĩa là chúng được gửi\n"
          "  tới máy chủ LandingAI.")

    if args.dry_run:
        print("\n--dry-run: KHÔNG gửi gì cả. Bỏ cờ này để chạy thật.")
        return 0

    engine = AdeEngine(model=args.model, service_tier=args.tier)
    try:
        engine.ensure_ready()
    except EngineUnavailable as exc:
        print(f"\nengine không dùng được: {exc}", file=sys.stderr)
        return 1

    # ── chạy ────────────────────────────────────────────────────────────────
    print("\n" + "─" * 78)
    ok = failed = 0

    for p, rel, _scan, _is_pdf in plan:
        if engine.credits_used >= args.max_credits:
            print(f"\nDỪNG: đã dùng {engine.credits_used:.1f} credits, "
                  f"chạm trần --max-credits {args.max_credits}")
            break

        did = doc_id_for(rel)
        print(f"{Path(rel).name[:44]:<46}", end="", flush=True)

        try:
            data = engine.parse_document(p)
        except Exception as exc:
            # Một tài liệu hỏng không được làm sập cả lượt đã trả tiền cho các
            # tài liệu trước nó.
            print(f"LỖI: {type(exc).__name__}: {str(exc)[:60]}")
            failed += 1
            continue

        pages = render_pages(p, args.store / did / "pages")
        meta = data.get("metadata") or {}
        credits = ((meta.get("billing") or {}).get("total_credits")) or 0.0

        save_result(args.store, did, data, source=rel, model=args.model,
                    credits=credits, pages=pages)

        chars = meta.get("output_markdown_chars") or len(data.get("markdown") or "")
        n_el = sum(len(pg.get("children") or [])
                   for pg in (data.get("structure") or {}).get("children") or [])
        print(f"{len(pages):>2} tr  {n_el:>3} phần tử  {chars:>5} ký tự  "
              f"{credits:>4.1f} cr")
        ok += 1

    # ── tổng kết ────────────────────────────────────────────────────────────
    print("\n" + "═" * 78)
    print(f"Xong {ok}/{len(plan)} tài liệu" + (f" · {failed} lỗi" if failed else ""))
    print(f"Credits (API báo): {engine.credits_used:.1f} "
          f"≈ ${engine.credits_used * USD_PER_CREDIT:.3f}")
    print(f"Kho: {args.store}")
    print("\n⚠ Các tài liệu trên đã rời khỏi máy và nằm trên máy chủ LandingAI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
