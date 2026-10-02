"""So sánh engine trên cùng một tập, cùng một bộ đo.

CỔNG CHẶN
─────────
Engine có `identifier_preservation < 99%` bị **LOẠI THẲNG**, bất kể CER đẹp
đến đâu. Văn bản đi tiếp vào đường lược danh tính, nơi số hiệu / email / ngày
tháng phải khớp nguyên văn. Một model sửa lỗi chính tả từng đạt 86% ở chỉ số
này và bị loại dù nó làm tăng tỉ lệ dấu.

Engine có `deployable_on_cpu_nas = False` được đo nhưng **đánh dấu riêng**: số
của nó chỉ để đối chiếu khi phát triển, không được dùng làm căn cứ chọn.

CỘNG DỒN THEO TRỌNG SỐ, KHÔNG LẤY TRUNG BÌNH CÁC TỈ LỆ
──────────────────────────────────────────────────────
Một trang 5 ký tự đọc sai hết sẽ kéo trung bình cộng xuống ngang một trang
2 000 ký tự đọc sai hết. Nên CER gộp = tổng phép sửa / tổng ký tự tham chiếu,
và tỉ lệ định danh gộp = tổng định danh còn / tổng định danh gốc.

Chạy:
    uv run python scripts/benchmark.py --engines tesseract --limit 20
    uv run python scripts/benchmark.py --engines tesseract,paddleocr-vl@1200
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
from ocr_lab.language import detect_language                       # noqa: E402
from ocr_lab.metrics import (                                      # noqa: E402
    accent_share, identifiers, levenshtein, normalize_for_compare, score,
)

BENCH = ROOT / "data" / "benchmarks" / "mdpbench"

#: Cổng chặn. KHÔNG hạ cho model mới, dù nó hứa gì.
IDENTIFIER_GATE = 0.99


def _ground_truth(page: dict) -> str:
    """Ghép text một trang theo thứ tự đọc.

    HEADER/FOOTER PHẢI ĐẶT Ở ĐẦU, KHÔNG PHẢI Ở CUỐI
    ───────────────────────────────────────────────
    Trong MDPBench, khối header/footer có `order = None` (chúng nằm ngoài
    luồng đọc chính). Bản đầu đẩy chúng xuống cuối cho tiện. Sai: model đọc
    trang từ trên xuống nên nó xuất header TRƯỚC. Đặt sai chỗ thì Levenshtein
    phạt như đọc sai, dù chữ đọc đúng từng ký tự.

    Đo trên `vi_academicpaper_17.jpg`: CER 0,389 (cuối) → 0,345 (đầu). Gần
    5 điểm phần trăm chỉ do cách ghép — đủ để xếp sai thứ hạng hai engine.

    Header đứng trước, footer đứng sau, phần thân theo `order`.
    """
    header, body, footer = [], [], []
    for det in page.get("layout_dets", []):
        if not det.get("text"):
            continue
        kind = det.get("category_type", "")
        if det.get("order") is None:
            (footer if kind == "footer" else header).append(det["text"])
        else:
            body.append((det["order"], det["text"]))
    return "\n".join(header + [t for _, t in sorted(body)] + footer)


def _load_pages(limit: int | None, photographed_only: bool) -> list[dict]:
    manifest = BENCH / "vietnamese_pages.json"
    if not manifest.exists():
        sys.exit(f"thiếu {manifest}\nchạy: uv run python "
                 f"scripts/fetch_mdpbench.py")
    pages = json.loads(manifest.read_text(encoding="utf-8"))

    if photographed_only:
        # Tên có hậu tố điều kiện chụp ⇒ là ảnh chụp biến dạng, không phải
        # bản gốc sạch. 120/160 trang thuộc loại này, và đó đúng là loại làm
        # hỏng 51 tệp trong kho thật.
        pages = [p for p in pages
                 if len(Path(p["page_info"]["image_path"]).stem.split("_")) > 3]
    return pages[:limit] if limit else pages


def _evaluate(engine, pages: list[dict], out_path: Path) -> dict:
    """Chạy một engine trên các trang, cộng dồn theo trọng số."""
    edits = ref_chars = 0
    ids_total = ids_kept = 0
    acc_ref_chars = acc_hyp_chars = alpha_ref = alpha_hyp = 0
    seconds = []
    encode_ms = []
    failures = []
    rows = []
    #: Trang bị CẮT vì hết ngân sách token. Chúng bị loại khỏi mọi con số
    #: tổng hợp — xem giải thích ở `_evaluate`.
    invalid = []

    for i, page in enumerate(pages, 1):
        name = page["page_info"]["image_path"]
        img = BENCH / "images" / name
        if not img.exists():
            failures.append({"page": name, "why": "thiếu ảnh"})
            continue

        ref = _ground_truth(page)
        try:
            res = engine.read_page(img)
        except Exception as exc:
            failures.append({"page": name,
                             "why": f"{type(exc).__name__}: {exc}"})
            continue

        s = score(ref, res.text)

        # TRANG BỊ CẮT KHÔNG ĐƯỢC GỘP VÀO SỐ TỔNG HỢP.
        #
        # Bài học đắt: một lượt đo có 6/12 trang chạm trần token. Cảnh báo đã
        # bắt đúng cả sáu, nhưng bảng tổng kết vẫn cộng dồn chúng và in ra
        # "LOẠI — định danh 81,9%". Con số đó nói về ngân sách token của ta,
        # không nói gì về model. Một cảnh báo mà phần tổng hợp phớt lờ là một
        # cảnh báo vô dụng.
        #
        # Số đo trên trang bị cắt không phải "kém chính xác" — nó VÔ NGHĨA:
        # phần văn bản thiếu chưa từng được model đọc sai, nó chưa từng được
        # model đọc.
        if any("CHẠM TRẦN" in w for w in res.warnings):
            invalid.append({"page": name, "why": "bị cắt vì hết token"})
            rows.append({"page": name, "invalid": "bị cắt vì hết token",
                         "seconds": round(res.elapsed_ms / 1000, 1)})
            print(f"  [{i}/{len(pages)}] {name[:46]:48s} "
                  f"BỎ — bị cắt vì hết ngân sách token")
            out_path.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2),
                encoding="utf-8")
            continue

        nref = normalize_for_compare(ref)
        edits += levenshtein(nref, normalize_for_compare(res.text))
        ref_chars += len(nref)
        ids_total += s.identifiers_total
        ids_kept += s.identifiers_kept

        # Tỉ lệ dấu cũng phải cộng dồn theo số chữ cái, không trung bình trang.
        ra = [c for c in ref if c.isalpha()]
        ha = [c for c in res.text if c.isalpha()]
        alpha_ref += len(ra)
        alpha_hyp += len(ha)
        acc_ref_chars += accent_share(ref) * len(ra)
        acc_hyp_chars += accent_share(res.text) * len(ha)

        seconds.append(res.elapsed_ms / 1000)
        if res.encode_ms:
            encode_ms.append(res.encode_ms)

        # Tỉ lệ độ dài so với bản gốc: dưới ~0,85 nghĩa là model BỎ SÓT nội
        # dung (khác với bị cắt — bị cắt thì kết thúc giữa câu). Ca thật:
        # `vi_academicpaper_16` ra 89% độ dài, mất số trang ở footer và một
        # đoạn thân bài, dù câu cuối vẫn kết thúc đúng dấu câu.
        coverage = len(res.text) / len(ref) if ref else 0.0
        warnings = list(res.warnings)
        if 0 < coverage < 0.85:
            warnings.append(f"chỉ đọc được {coverage:.0%} độ dài bản gốc — "
                            f"model BỎ SÓT nội dung")

        rows.append({
            "page": name, "cer": round(s.cer, 4),
            "identifier_preservation": round(s.identifier_preservation, 4),
            "accent_hyp": round(s.accent_hyp, 3),
            "coverage": round(coverage, 3),
            "seconds": round(res.elapsed_ms / 1000, 1),
            "language": detect_language(res.text).language.value,
            "warnings": warnings,
        })

        print(f"  [{i}/{len(pages)}] {name[:46]:48s} "
              f"CER {s.cer:5.3f}  dấu {s.accent_hyp:5.3f}  "
              f"đdanh {s.identifier_preservation:5.3f}  "
              f"{res.elapsed_ms / 1000:6.1f}s")

        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    n = len(seconds)
    med = sorted(seconds)[n // 2] if n else 0.0
    return {
        "engine": engine.name,
        "deployable_on_cpu_nas": engine.deployable_on_cpu_nas,
        "pages_read": n,
        "pages_failed": len(failures),
        "pages_invalid": len(invalid),
        "invalid": invalid[:10],
        # Cộng dồn, không trung bình các tỉ lệ.
        "cer": round(edits / ref_chars, 4) if ref_chars else None,
        "identifier_preservation": (round(ids_kept / ids_total, 4)
                                    if ids_total else None),
        "identifiers_total": ids_total,
        "accent_ref": (round(acc_ref_chars / alpha_ref, 3)
                       if alpha_ref else None),
        "accent_hyp": (round(acc_hyp_chars / alpha_hyp, 3)
                       if alpha_hyp else None),
        "seconds_median": round(med, 1),
        "seconds_total": round(sum(seconds), 1),
        "encode_ms_median": (round(sorted(encode_ms)[len(encode_ms) // 2], 0)
                             if encode_ms else None),
        "failures": failures[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engines", default="tesseract",
                    help="danh sách cách nhau bằng dấu phẩy, vd "
                         "tesseract,paddleocr-vl@1200")
    ap.add_argument("--limit", type=int, help="số trang")
    ap.add_argument("--photographed-only", action="store_true",
                    help="chỉ ảnh chụp biến dạng (120/160 trang)")
    ap.add_argument("--out", default="reports/engine_comparison.json")
    args = ap.parse_args()

    pages = _load_pages(args.limit, args.photographed_only)
    print(f"{len(pages)} trang"
          f"{' (chỉ ảnh chụp)' if args.photographed_only else ''}\n")

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    summaries = []

    for spec in args.engines.split(","):
        spec = spec.strip()
        print(f"── {spec} " + "─" * (70 - len(spec)))
        try:
            eng = build_engine(spec)
            t0 = time.perf_counter()
            eng.ensure_ready()
            load_s = time.perf_counter() - t0
        except EngineUnavailable as exc:
            print(f"  BỎ QUA: {exc}\n")
            summaries.append({"engine": spec, "skipped": str(exc)})
            continue

        s = _evaluate(eng, pages,
                      out_dir / f"pages_{spec.replace('@', '_')}.json")
        s["spec"] = spec
        s["load_seconds"] = round(load_s, 1)
        summaries.append(s)
        print()

    # ── bảng tổng kết ───────────────────────────────────────────────────────
    print("\n" + "=" * 92)
    print(f"{'engine':<22} {'CER':>7} {'dấu':>7} {'đdanh':>7} {'giây/tr':>8} "
          f"{'tr':>4} {'NAS':>4}  kết luận")
    print("=" * 92)

    ref_acc = next((s.get("accent_ref") for s in summaries
                    if s.get("accent_ref")), None)
    if ref_acc:
        print(f"{'(bản gốc)':<22} {'—':>7} {ref_acc:>7.3f} {'—':>7} "
              f"{'—':>8} {'—':>4} {'—':>4}  mốc tiếng Việt thật")

    for s in summaries:
        if "skipped" in s:
            print(f"{s['engine']:<22} {'—':>7} {'—':>7} {'—':>7} {'—':>8} "
                  f"{'—':>5}  BỎ QUA")
            continue

        gate = s["identifier_preservation"]
        n_bad = s.get("pages_invalid", 0)

        # Quá nửa số trang bị loại ⇒ KHÔNG kết luận gì về model. Đưa ra phán
        # quyết dựa trên phần còn lại là tự lừa mình: những trang sống sót
        # thường là trang ngắn, tức mẫu đã bị thiên lệch.
        if n_bad and n_bad >= s["pages_read"]:
            verdict = (f"KHÔNG KẾT LUẬN ĐƯỢC — {n_bad} trang bị cắt vì hết "
                       f"token; tăng n_predict rồi đo lại")
        elif gate is None:
            verdict = "không có định danh để kiểm"
        elif gate < IDENTIFIER_GATE:
            verdict = f"LOẠI — định danh {gate:.1%} < {IDENTIFIER_GATE:.0%}"
        elif not s["deployable_on_cpu_nas"]:
            verdict = "chỉ đối chiếu — không chạy được trên NAS"
        else:
            verdict = "qua cổng"
        if n_bad and n_bad < s["pages_read"]:
            verdict += f" (đã bỏ {n_bad} trang bị cắt)"

        if s["pages_read"] == 0:
            print(f"{s['spec']:<22} {'—':>7} {'—':>7} {'—':>7} {'—':>8} "
                  f"{0:>4} {'✓' if s['deployable_on_cpu_nas'] else '✗':>4}"
                  f"  {verdict}")
            continue

        print(f"{s['spec']:<22} {s['cer']:>7.3f} {s['accent_hyp']:>7.3f} "
              f"{gate if gate is not None else 0:>7.3f} "
              f"{s['seconds_median']:>8.1f} {s['pages_read']:>4} "
              f"{'✓' if s['deployable_on_cpu_nas'] else '✗':>4}  {verdict}")

    out = ROOT / args.out
    out.write_text(json.dumps(summaries, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\nGhi: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
