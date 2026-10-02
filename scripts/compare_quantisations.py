"""So sánh ĐỊNH DẠNG LƯỢNG TỬ HOÁ của model VLM — không phải so model khác nhau.

PHÁT HIỆN DẪN TỚI SCRIPT NÀY
────────────────────────────
Bản GGUF chính chủ của PaddlePaddle phát hành ở **BF16**. Trên CPU Apple
Silicon đó là trường hợp xấu nhất có thể: không có kernel BF16, phép nhân ma
trận rơi về vòng lặp vô hướng.

Đo trên cùng một ảnh, cùng 6 luồng, chỉ đổi định dạng:

    mmproj BF16 (841 MB) + model BF16    mã hoá 274 s   tổng 410 s
    mmproj Q8_0 (570 MB) + model Q4_K_M  mã hoá  66 s   tổng  82 s
                                         ────────────────────────
                                         nhanh gấp 5,0 lần

Điều bất ngờ nhất: **chính bộ mã hoá thị giác (mmproj) mới là chỗ nghẽn**, chứ
không phải phần ngôn ngữ. `llama-bench` cho thấy phần ngôn ngữ vẫn đạt 565
token/s ở BF16 — hoàn toàn bình thường. Toàn bộ thiệt hại nằm ở mmproj.

Bài học chung: khi đánh giá một VLM trên CPU, **phải kiểm định dạng của mmproj
riêng**, không chỉ của model ngôn ngữ. Chúng thường được phát hành ở định dạng
khác nhau và các bảng benchmark hầu như chỉ nói về phần ngôn ngữ.

TẠI SAO PHẢI ĐO CHẤT LƯỢNG CHỨ KHÔNG CHỈ ĐO GIỜ
───────────────────────────────────────────────
Lượng tử hoá làm tròn trọng số, nên nó CÓ THỂ làm giảm chất lượng đọc. Với
tiếng Việt, thứ mất trước tiên thường là dấu — mà dấu thì mang thông tin định
danh. Vì vậy mỗi cấu hình đều phải qua đủ ba chỉ số, và cổng
`identifier_preservation ≥ 99%` không được nới cho một cấu hình chỉ vì nó nhanh.

Chạy:
    uv run python scripts/compare_quantisations.py --pages 3
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.metrics import (                                     # noqa: E402
    accent_share, cer, identifier_preservation,
)

BENCH = ROOT / "data" / "benchmarks" / "mdpbench"
GGUF = ROOT / "models" / "gguf"
_ENCODE_RE = re.compile(r"batch encoding done in (\d+) ms")
_LOG_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+ [IWED] ")

#: (tên, model, mmproj). mmproj để riêng vì nó mới là chỗ quyết định tốc độ.
CONFIGS = [
    # Thứ tự có chủ ý: bản gốc trước, rồi hai cách đổi MỘT biến mỗi lần.
    ("bf16 (chính chủ)", "PaddleOCR-VL-1.6-GGUF.gguf",
     "PaddleOCR-VL-1.6-GGUF-mmproj.gguf"),
    # Chỉ đổi mmproj ⇒ cô lập được ảnh hưởng của bộ mã hoá thị giác.
    ("bf16 + mmproj q8", "PaddleOCR-VL-1.6-GGUF.gguf", "mmproj-Q8_0.gguf"),
    # Đổi thêm model ngôn ngữ ⇒ đo riêng cái giá của việc hạ nửa còn lại.
    # Thang lượng tử hoá đi từ nhẹ tay tới mạnh tay, để thấy chất lượng rơi ở đâu.
    ("q8_0 + mmproj q8", "PaddleOCR-VL-1.6-Q8_0.gguf", "mmproj-Q8_0.gguf"),
    ("q6_k + mmproj q8", "PaddleOCR-VL-1.6-Q6_K.gguf", "mmproj-Q8_0.gguf"),
    ("q4_k_m + mmproj q8", "PaddleOCR-VL-1.6-Q4_K_M.gguf", "mmproj-Q8_0.gguf"),
]


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


def _run(model: Path, mmproj: Path, image: Path, threads: int,
         n_predict: int) -> tuple[str, float, int]:
    cmd = ["llama-mtmd-cli", "-m", str(model), "--mmproj", str(mmproj),
           "--image", str(image), "-p", "OCR:", "-n", str(n_predict),
           "--temp", "0", "-ngl", "0", "--no-mmproj-offload",
           "-t", str(threads), "--jinja"]
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    m = _ENCODE_RE.search(r.stderr + r.stdout)
    text = "\n".join(ln for ln in r.stdout.splitlines()
                     if not _LOG_RE.match(ln)).strip()
    return text, elapsed, int(m.group(1)) if m else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--threads", type=int, default=6,
                   help="mặc định 6 = số nhân hiệu năng của M4; nhân tiết "
                        "kiệm kéo tụt cả nhóm do llama.cpp đồng bộ rào chắn")
    # 2048 chứ không phải 1024: đo thật cho 2,61 ký tự/token, nên 1024 chỉ đủ
    # ~2 670 ký tự và trang tài liệu tham khảo (2 844 ký tự) bị CẮT. Trang bị
    # cắt làm hỏng cả CER lẫn tỉ lệ định danh, rồi ta đổ oan cho model.
    ap.add_argument("--n-predict", type=int, default=2048)
    ap.add_argument("--out", default="reports/quantisation_comparison.json")
    args = ap.parse_args()

    manifest = json.loads((BENCH / "vietnamese_pages.json").read_text("utf-8"))
    pristine = [p for p in manifest
                if len(Path(p["page_info"]["image_path"]).stem.split("_")) == 3]
    pages = (pristine or manifest)[:args.pages]

    missing = [(n, m, p) for n, m, p in CONFIGS
               if not (GGUF / m).exists() or not (GGUF / p).exists()]
    for n, m, p in missing:
        print(f"bỏ qua {n}: thiếu {m} hoặc {p}", file=sys.stderr)
    configs = [c for c in CONFIGS if c not in missing]

    rows = []
    for name, model, mmproj in configs:
        print(f"\n── {name} " + "─" * (66 - len(name)))
        print(f"   model {(GGUF / model).stat().st_size / 1e6:.0f} MB · "
              f"mmproj {(GGUF / mmproj).stat().st_size / 1e6:.0f} MB")
        print(f"{'trang':<34} {'tổng':>7} {'mã hoá':>8} {'CER':>7} "
              f"{'dấu':>6} {'đdanh':>7}")

        for page in pages:
            name_img = page["page_info"]["image_path"]
            img = BENCH / "images" / name_img
            if not img.exists():
                continue
            ref = _ground_truth(page)
            text, secs, enc = _run(GGUF / model, GGUF / mmproj, img,
                                   args.threads, args.n_predict)
            row = {
                "config": name, "model": model, "mmproj": mmproj,
                "page": name_img, "seconds": round(secs, 1),
                "encode_ms": enc,
                "cer": round(cer(ref, text), 4),
                "accent_ref": round(accent_share(ref), 3),
                "accent_hyp": round(accent_share(text), 3),
                "identifier_preservation": round(
                    identifier_preservation(ref, text), 4),
                "chars": len(text),
            }
            rows.append(row)
            print(f"{name_img[:32]:<34} {secs:>6.1f}s {enc / 1000:>7.1f}s "
                  f"{row['cer']:>7.3f} {row['accent_hyp']:>6.3f} "
                  f"{row['identifier_preservation']:>7.3f}")

            out = ROOT / args.out
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    # ── tổng kết ────────────────────────────────────────────────────────────
    print("\n" + "=" * 84)
    print(f"{'cấu hình':<22} {'tổng':>8} {'mã hoá':>8} {'CER':>7} {'dấu':>7} "
          f"{'đdanh':>7}  kết luận")
    print("=" * 84)

    ref_acc = rows[0]["accent_ref"] if rows else None
    if ref_acc:
        print(f"{'(bản gốc)':<22} {'—':>8} {'—':>8} {'—':>7} {ref_acc:>7.3f} "
              f"{'—':>7}  mốc tiếng Việt thật")

    baseline = None
    for name, _, _ in configs:
        rs = [r for r in rows if r["config"] == name]
        if not rs:
            continue
        secs = sum(r["seconds"] for r in rs) / len(rs)
        enc = sum(r["encode_ms"] for r in rs) / len(rs) / 1000
        c = sum(r["cer"] for r in rs) / len(rs)
        a = sum(r["accent_hyp"] for r in rs) / len(rs)
        ident = sum(r["identifier_preservation"] for r in rs) / len(rs)
        baseline = baseline or secs
        verdict = (f"nhanh gấp {baseline / secs:.1f}×" if secs else "")
        if ident < 0.99:
            verdict += f" · LOẠI: định danh {ident:.1%}"
        print(f"{name:<22} {secs:>7.1f}s {enc:>7.1f}s {c:>7.3f} {a:>7.3f} "
              f"{ident:>7.3f}  {verdict}")

    print(f"\nGhi: {ROOT / args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
