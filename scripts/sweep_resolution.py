"""Quét độ phân giải: ảnh nhỏ lại thì nhanh hơn bao nhiêu, và mất gì.

VÌ SAO CÓ SCRIPT NÀY
────────────────────
Phép đo đầu tiên trên llama.cpp (CPU, 10 luồng, ảnh gốc 2245×3189) cho:

    mtmd batch encoding done in 261 479 ms
    tổng                          306 s

**261/306 giây nằm ở bộ mã hoá ẢNH, không phải ở sinh token.** Đây là kết luận
NGƯỢC với chẩn đoán trên PyTorch trước đây ("nạp model không phải nút thắt,
toàn bộ thời gian ở sinh token"). Cùng một model, đổi runtime thì nút thắt dời
chỗ — nên phải đo lại chứ không suy từ lần trước.

PaddleOCR-VL dùng NaViT: số token ảnh tỉ lệ với SỐ ĐIỂM ẢNH, không cố định.
Trang 2245×3189 ≈ 9 000 token ảnh. Attention có chi phí bậc hai theo số token,
nên hạ độ phân giải một nửa có thể rẻ hơn bốn lần, không phải hai lần.

Câu hỏi phải trả lời bằng số: **hạ tới đâu thì chữ bắt đầu vỡ?**

Đây KHÔNG mâu thuẫn với bài học cũ "render lại ở DPI cao là vô ích". Bài học
đó nói tăng DPI không thêm thông tin. Đây là chiều ngược lại: bỏ bớt điểm ảnh
thừa mà vẫn đủ đọc.

Chạy:
    uv run python scripts/sweep_resolution.py --pages 3
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.metrics import accent_share, cer, identifier_preservation  # noqa: E402

BENCH = ROOT / "data" / "benchmarks" / "mdpbench"
GGUF = ROOT / "models" / "gguf"
MODEL = GGUF / "PaddleOCR-VL-1.6-GGUF.gguf"
MMPROJ = GGUF / "PaddleOCR-VL-1.6-GGUF-mmproj.gguf"

#: Cạnh dài của ảnh sau khi thu nhỏ. `None` = giữ nguyên ảnh gốc.
LONG_EDGE_STEPS = [None, 2000, 1500, 1100, 800]

_ENCODE_RE = re.compile(r"batch encoding done in (\d+) ms")


def _ground_truth(page: dict) -> str:
    """Ghép text của trang theo thứ tự đọc.

    `order` có thể là None (chú thích hình, khối ngoài luồng đọc chính) — đẩy
    xuống cuối thay vì để `sorted` ném lỗi.
    """
    dets = sorted(page.get("layout_dets", []),
                  key=lambda d: (d.get("order") is None, d.get("order") or 0))
    return "\n".join(d["text"] for d in dets if d.get("text"))


def _resize(src: Path, long_edge: int | None, out_dir: Path) -> tuple[Path, int]:
    im = Image.open(src)
    if long_edge is None or max(im.size) <= long_edge:
        return src, max(im.size)
    # Ảnh PNG dạng bảng màu (mode "P") không ghi ra JPEG được. Chuyển sang RGB
    # trước khi thu nhỏ — nội suy trên chỉ số bảng màu cũng vô nghĩa.
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    scale = long_edge / max(im.size)
    new = (round(im.width * scale), round(im.height * scale))
    # LANCZOS: giữ nét chữ tốt nhất khi thu nhỏ. BILINEAR làm nhoè nét mảnh
    # của dấu tiếng Việt — đúng thứ ta không được phép mất.
    dst = out_dir / f"{src.stem}__{long_edge}.jpg"
    im.resize(new, Image.Resampling.LANCZOS).save(dst, quality=95)
    return dst, long_edge


def _run_ocr(image: Path, n_predict: int, threads: int) -> tuple[str, float, int]:
    """Gọi llama-mtmd-cli một lần. Trả (text, giây, ms mã hoá ảnh)."""
    cmd = [
        "llama-mtmd-cli",
        "-m", str(MODEL), "--mmproj", str(MMPROJ),
        "--image", str(image),
        "-p", "OCR:", "-n", str(n_predict),
        "--temp", "0", "-ngl", "0", "--no-mmproj-offload",
        "-t", str(threads), "--jinja",
    ]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0

    enc_ms = 0
    m = _ENCODE_RE.search(r.stderr) or _ENCODE_RE.search(r.stdout)
    if m:
        enc_ms = int(m.group(1))

    # stdout của llama-mtmd-cli chứa cả log lẫn kết quả; log đi kèm dấu thời
    # gian dạng "0.12.345.678 I " ở đầu dòng.
    lines = [ln for ln in r.stdout.splitlines()
             if not re.match(r"^\d+\.\d+\.\d+\.\d+ [IWE] ", ln)]
    return "\n".join(lines).strip(), elapsed, enc_ms


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pages", type=int, default=3, help="số trang đo")
    ap.add_argument("--threads", type=int, default=10)
    ap.add_argument("--n-predict", type=int, default=1024)
    ap.add_argument("--out", default="reports/resolution_sweep.json")
    args = ap.parse_args()

    manifest = json.loads((BENCH / "vietnamese_pages.json").read_text("utf-8"))
    # Ưu tiên bản gốc sạch (không có hậu tố điều kiện chụp): tách bạch ảnh
    # hưởng của độ phân giải khỏi ảnh hưởng của biến dạng chụp.
    pristine = [p for p in manifest
                if len(Path(p["page_info"]["image_path"]).stem.split("_")) == 3]
    pages = (pristine or manifest)[:args.pages]

    tmp = BENCH / "_resized"
    tmp.mkdir(exist_ok=True)
    rows = []

    for page in pages:
        name = page["page_info"]["image_path"]
        src = BENCH / "images" / name
        if not src.exists():
            print(f"thiếu ảnh {name}", file=sys.stderr)
            continue
        ref = _ground_truth(page)
        print(f"\n{'=' * 74}\n{name}  ({Image.open(src).size[0]}×"
              f"{Image.open(src).size[1]})\n{'=' * 74}")
        print(f"{'cạnh dài':>9} {'giây':>7} {'mã hoá ảnh':>11} {'CER':>7} "
              f"{'dấu':>6} {'định danh':>10}")

        for step in LONG_EDGE_STEPS:
            img, actual = _resize(src, step, tmp)
            text, secs, enc_ms = _run_ocr(img, args.n_predict, args.threads)
            row = {
                "page": name, "long_edge": actual, "seconds": round(secs, 1),
                "encode_ms": enc_ms,
                "cer": round(cer(ref, text), 4),
                "accent_ref": round(accent_share(ref), 3),
                "accent_hyp": round(accent_share(text), 3),
                "identifier_preservation": round(
                    identifier_preservation(ref, text), 4),
                "chars": len(text),
            }
            rows.append(row)
            print(f"{actual:>9} {secs:>7.1f} {enc_ms / 1000:>10.1f}s "
                  f"{row['cer']:>7.3f} {row['accent_hyp']:>6.3f} "
                  f"{row['identifier_preservation']:>10.3f}")

            out = ROOT / args.out
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    print(f"\nGhi: {ROOT / args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
