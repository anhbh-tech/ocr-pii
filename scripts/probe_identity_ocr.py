"""Chạy thử OCR giấy tờ tuỳ thân — ca TỆ NHẤT của hồ sơ khách hàng.

VÌ SAO CÓ SCRIPT RIÊNG CHO CCCD
───────────────────────────────
Giấy tờ tuỳ thân là ca khó nhất trong toàn bộ tập hồ sơ, vì ba lý do cộng dồn
mà tài liệu thường không có:

1. **Model hay TỪ CHỐI đọc.** Không phải vì chính sách cấm — chép chữ trên
   giấy tờ là việc hợp pháp mà cả ngành eKYC làm hằng ngày — mà vì model đọc
   nhầm ý định, tưởng ta muốn nhận dạng con người. Lời nhắc hệ thống trong
   `ocr_lab.prompts` nói rõ ngữ cảnh thật để chữa cái nhầm đó.

2. **Mọi trường đều là định danh.** Trên một tờ đơn, đọc sai một chữ trong câu
   văn là lỗi nhỏ. Trên CCCD, MỌI trường đều mang danh tính: sai một chữ số
   trong số thẻ là hồ sơ sai. Không có chữ nào "không quan trọng".

3. **Dấu tiếng Việt mang thông tin phân biệt người.** "Nguyễn Văn Hùng" và
   "Nguyên Văn Hung" là hai người khác nhau trước pháp luật. Một engine mất
   dấu có thể đạt CER trông chấp nhận được mà vẫn vô dụng.

ĐO ĐỘ PHỦ TRƯỜNG, KHÔNG CHỈ ĐO CER
──────────────────────────────────
Hai thất bại rất khác nhau mà CER gộp làm một:

    BỎ SÓT TRƯỜNG   model không tìm ra mục đó   → hồ sơ thiếu mục (NẶNG)
    SAI GIÁ TRỊ     đọc nhầm chữ                → soát tay sửa được (nhẹ hơn)

Độ phủ trường tách được hai thứ đó, và tính được NGAY CẢ KHI CHƯA CÓ ground
truth — chỉ cần biết CCCD phải có những trường nào. Đó là lý do script này cho
ra số liệu dùng được trong khi `data/gold/truth/` vẫn còn rỗng.

CHẠY:
    uv run python scripts/probe_identity_ocr.py --dry-run
    uv run python scripts/probe_identity_ocr.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.engines import (                                     # noqa: E402
    EngineUnavailable, OpenAiVisionEngine, load_dotenv,
)
from ocr_lab.metrics import accent_share, identifiers              # noqa: E402
from ocr_lab.prompts import (                                      # noqa: E402
    CCCD_FIELDS, IDENTITY_DOC_PROMPT, LEGAL_OCR_SYSTEM,
)

#: Thư mục hồ sơ khách hàng. Ngoài cây dự án, quyền 700.
PRIVATE = Path.home() / ".private" / "refiny_data"

#: Mốc: tỉ lệ dấu của tiếng Việt thật (ground truth MDPBench).
VIETNAMESE_ACCENT_SHARE = 0.217

_PRICE_PER_MTOK = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
}


#: Ước tính token cho MỘT trang tài liệu, dùng để báo chi phí trước khi chạy.
#:
#: Không phải số đoán: tính theo đúng quy tắc chia ô của OpenAI. Ảnh được vừa
#: khung 2048², rồi cạnh NGẮN hạ về 768, rồi chia ô 512×512; mỗi ô 170 token
#: cộng 85 token nền. Trang A4 dựng 200 DPI thu về cạnh dài 2000 px cho ra
#: 1545×2000 ⇒ 2×4 ô ⇒ 765 token thị giác.
#:
#: Cộng ~420 token cho lời nhắc hệ thống + lời nhắc người dùng.
_EST_INPUT_TOKENS = 1185

#: Đầu ra: một trang giấy tờ đủ trường ≈ 1 200 ký tự, và tiếng Việt tốn ~2,6
#: ký tự/token (đo thật, nhiều hơn tiếng Anh vì dấu).
_EST_OUTPUT_TOKENS = 478


def _estimate_cost(model: str, prompt_tok: int, completion_tok: int) -> float | None:
    price = _PRICE_PER_MTOK.get(model)
    if price is None:
        return None
    return prompt_tok / 1e6 * price[0] + completion_tok / 1e6 * price[1]


def find_identity_docs(root: Path) -> list[Path]:
    """Tìm tệp giấy tờ tuỳ thân theo TÊN TỆP.

    Chỉ dựa vào tên, không mở nội dung để phân loại: mở ra để quyết định có
    nên gửi đi hay không là đã đọc thứ ta đang cân nhắc có được đọc không.

    Đánh đổi đã biết: bỏ sót giấy tờ đặt tên khác thường. Chấp nhận được, vì
    script này để THỬ NGHIỆM trên vài tệp, không phải để quét toàn bộ kho.
    """
    keys = ("cccd", "cmnd", "can cuoc", "căn cước", "passport",
            "ho chieu", "hộ chiếu", "id card", "chung minh")
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (
                ".pdf", ".jpg", ".jpeg", ".png"):
            continue
        if any(k in p.name.lower() for k in keys):
            out.append(p)
    return out


def field_coverage(text: str) -> tuple[list[str], list[str]]:
    """Trường nào TÌM THẤY, trường nào BỎ SÓT trong bản chép.

    So khớp trên NHÃN chứ không trên giá trị: script không biết giá trị đúng
    là gì (đó là việc của ground truth do người gõ). Nó chỉ trả lời được một
    câu hẹp hơn — model có tìm ra mục đó không — và đó đã là câu hỏi phân biệt
    được lỗi nặng với lỗi nhẹ.
    """
    low = text.lower()
    found = [name for name, aliases in CCCD_FIELDS.items()
             if any(a in low for a in aliases)]
    missing = [n for n in CCCD_FIELDS if n not in found]
    return found, missing


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=PRIVATE,
                    help=f"thư mục hồ sơ (mặc định {PRIVATE})")
    ap.add_argument("--model", default=None,
                    help="ghi đè model, vd gpt-4o-mini")
    ap.add_argument("--max-files", type=int, default=2,
                    help="trần số TỆP (mặc định 2 — đây là dữ liệu thật)")
    ap.add_argument("--max-side", type=int, default=2000)
    ap.add_argument("--pdf-dpi", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true",
                    help="chỉ liệt kê tệp SẼ gửi, không gọi API")
    ap.add_argument("--save-text", action="store_true",
                    help="ghi cả bản chép vào báo cáo (CHỨA PII THẬT)")
    ap.add_argument("--out", default="reports/identity_probe.json")
    args = ap.parse_args()

    load_dotenv()

    if not args.root.exists():
        print(f"không có thư mục {args.root}", file=sys.stderr)
        return 2

    docs = find_identity_docs(args.root)
    if not docs:
        print(f"không tìm thấy giấy tờ tuỳ thân nào trong {args.root}",
              file=sys.stderr)
        return 2

    import os
    model = args.model or os.environ.get("OCR_LAB_OPENAI_MODEL", "gpt-4o")

    engine = OpenAiVisionEngine(
        model=model,
        system=LEGAL_OCR_SYSTEM,
        prompt=IDENTITY_DOC_PROMPT,
        max_side=args.max_side,
        pdf_dpi=args.pdf_dpi,
    )

    # ── đếm số LẦN GỌI, không phải số tệp ───────────────────────────────────
    # Một PDF n trang = n lần gọi có tính tiền. Đếm theo tệp sẽ báo thiếu.
    import pymupdf

    plan = []
    for p in docs[:args.max_files]:
        if p.suffix.lower() == ".pdf":
            with pymupdf.open(p) as d:
                pages = d.page_count
        else:
            pages = 1
        plan.append((p, pages))

    calls = sum(n for _, n in plan)

    print(f"\nThư mục: {args.root}")
    print(f"Model:   {model}")
    print(f"\nTìm thấy {len(docs)} giấy tờ tuỳ thân, "
          f"sẽ xử lý {len(plan)} tệp = {calls} lần gọi API:\n")
    for p, n in plan:
        rel = p.relative_to(args.root)
        size = p.stat().st_size / 1e6
        page = f"{n} trang" if p.suffix.lower() == ".pdf" else "ảnh"
        print(f"   {str(rel)[:70]:<72} {page:<9} {size * 1000:>5.0f} KB")

    if len(docs) > len(plan):
        print(f"\n   ({len(docs) - len(plan)} tệp còn lại bị trần "
              f"--max-files chặn)")

    est = _estimate_cost(model, calls * _EST_INPUT_TOKENS,
                         calls * _EST_OUTPUT_TOKENS)
    if est is not None:
        print(f"\nƯớc tính chi phí: ~{est:.4f} USD "
              f"({est / calls:.5f}/trang × {calls})")

    print("\n⚠ Đây là GIẤY TỜ TUỲ THÂN THẬT của thân chủ. Chạy tiếp nghĩa là "
          "chúng\n  được gửi tới máy chủ OpenAI.")

    if args.dry_run:
        print("\n--dry-run: KHÔNG gửi gì cả. Bỏ cờ này để chạy thật.")
        return 0

    try:
        engine.ensure_ready()
    except EngineUnavailable as exc:
        print(f"\nengine không dùng được: {exc}", file=sys.stderr)
        return 1

    print("\n" + "─" * 78)
    rows = []
    for path, npages in plan:
        rel = str(path.relative_to(args.root))
        results = (engine.read_pdf_pages(path)
                   if path.suffix.lower() == ".pdf"
                   else [engine.read_page(path)])

        for i, res in enumerate(results, start=1):
            label = f"{Path(rel).name}" + (f" tr.{i}" if npages > 1 else "")
            refused = any("TỪ CHỐI" in w for w in res.warnings)
            found, missing = field_coverage(res.text)
            acc = accent_share(res.text)

            row = {
                "file": rel, "page": i, "model": model,
                "seconds": round(res.elapsed_ms / 1000, 1),
                "chars": len(res.text),
                "refused": refused,
                "accent_share": round(acc, 3),
                "fields_found": found, "fields_missing": missing,
                "field_coverage": round(len(found) / len(CCCD_FIELDS), 3),
                "identifier_count": len(identifiers(res.text)),
                "warnings": res.warnings,
            }
            # Bản chép chứa PII THẬT. Mặc định KHÔNG ghi ra đĩa: một tệp báo
            # cáo nằm lại trong repo là một rò rỉ chờ xảy ra. Muốn thì phải
            # nói rõ ý định bằng --save-text.
            if args.save_text:
                row["text"] = res.text
            rows.append(row)

            state = "TỪ CHỐI" if refused else f"{len(found)}/{len(CCCD_FIELDS)} trường"
            print(f"{label[:44]:<46} {row['seconds']:>5.1f}s "
                  f"{row['chars']:>6} ký tự  dấu {acc:>5.3f}  {state}")
            for w in res.warnings:
                print(f"    ⚠ {w}")
            if missing and not refused:
                print(f"    thiếu: {', '.join(missing)}")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    # ── tổng kết ────────────────────────────────────────────────────────────
    print("\n" + "═" * 78)
    refused = [r for r in rows if r["refused"]]
    read = [r for r in rows if not r["refused"] and r["chars"] > 0]

    print(f"Đọc được {len(read)}/{len(rows)} trang · "
          f"từ chối {len(refused)}")

    if refused:
        print("\n⚠ CÒN BỊ TỪ CHỐI — lời nhắc hệ thống chưa đủ cho model này.")
        print("  Thử: đổi model, hoặc xem lại src/ocr_lab/prompts.py")

    if read:
        cov = sum(r["field_coverage"] for r in read) / len(read)
        acc = sum(r["accent_share"] for r in read) / len(read)
        print(f"\nĐộ phủ trường trung bình: {cov:.1%}")
        print(f"Tỉ lệ dấu trung bình:     {acc:.3f} "
              f"(tiếng Việt thật ≈ {VIETNAMESE_ACCENT_SHARE})")

        if acc < VIETNAMESE_ACCENT_SHARE * 0.6:
            print("   ⚠ MẤT DẤU — dấu là thứ phân biệt tên người này với "
                  "người kia")

        # Trường nào bị bỏ sót NHIỀU NHẤT: đó là chỗ cần sửa lời nhắc, và
        # cũng là chỗ người soát phải để mắt.
        from collections import Counter
        miss = Counter(f for r in read for f in r["fields_missing"])
        if miss:
            print("\nTrường hay bị bỏ sót nhất:")
            for name, n in miss.most_common(5):
                print(f"   {name:<22} thiếu ở {n}/{len(read)} trang")

    use = engine.usage
    cost = _estimate_cost(model, use["prompt_tokens"], use["completion_tokens"])
    print(f"\nToken: {use['prompt_tokens']:,} vào + "
          f"{use['completion_tokens']:,} ra"
          + (f" ≈ {cost:.3f} USD" if cost is not None else ""))
    print(f"Ghi: {out}" + ("" if args.save_text
                           else "  (KHÔNG kèm bản chép — dùng --save-text nếu cần)"))
    print("\n⚠ Các tệp trên đã rời khỏi máy và nằm trên máy chủ OpenAI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
