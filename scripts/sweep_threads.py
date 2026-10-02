"""Quét số luồng: nhiều nhân hơn có thật sự nhanh hơn không?

VÌ SAO CÓ SCRIPT NÀY
────────────────────
Máy M4 này có **10 nhân, nhưng không đồng nhất**: 6 nhân hiệu năng (P) và 4
nhân tiết kiệm điện (E). Nhân E chậm hơn nhân P vài lần.

llama.cpp chia đều công việc cho các luồng rồi **đồng bộ theo rào chắn** ở mỗi
lớp: mọi luồng phải chờ luồng chậm nhất xong mới đi tiếp. Nên khi đặt `-t 10`,
4 luồng chạy trên nhân E trở thành điểm nghẽn và **kéo tụt cả 6 luồng nhanh**.
Về lý thuyết `-t 6` (chỉ nhân P) có thể nhanh hơn `-t 10`.

Đây đúng là kiểu giả định phải đo chứ không suy luận. Ghi chú cũ của dự án có
câu "PyTorch chỉ dùng 4/10 nhân — đòn bẩy chưa dùng", ngụ ý càng nhiều luồng
càng tốt. Trên máy nhân không đồng nhất, điều đó có thể sai hẳn.

CẢNH BÁO VỀ BỘ NHỚ
──────────────────
Nếu máy đang dùng swap nặng thì mọi số đo đều nhiễu. Script kiểm swap trước và
nói rõ, thay vì cho ra một bảng số trông hợp lệ nhưng đo lẫn cả thời gian chờ
đĩa.

Chạy:
    uv run python scripts/sweep_threads.py
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

from ocr_lab.metrics import cer, identifier_preservation      # noqa: E402

BENCH = ROOT / "data" / "benchmarks" / "mdpbench"
GGUF = ROOT / "models" / "gguf"
_ENCODE_RE = re.compile(r"batch encoding done in (\d+) ms")
_LOG_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+ [IWED] ")


def _core_counts() -> tuple[int, int, int]:
    """(tổng, nhân hiệu năng, nhân tiết kiệm). Không phải macOS thì trả (n,0,0)."""
    def sysctl(key: str) -> int:
        try:
            return int(subprocess.run(["sysctl", "-n", key],
                                      capture_output=True, text=True).stdout)
        except Exception:
            return 0

    total = sysctl("hw.ncpu") or 4
    # perflevel0 = nhóm nhanh (P), perflevel1 = nhóm tiết kiệm (E).
    fast = sysctl("hw.perflevel0.logicalcpu")
    slow = sysctl("hw.perflevel1.logicalcpu")
    return total, fast, slow


def _swap_pressure_gb() -> float:
    try:
        out = subprocess.run(["sysctl", "-n", "vm.swapusage"],
                             capture_output=True, text=True).stdout
        m = re.search(r"used\s*=\s*([\d.]+)M", out)
        return float(m.group(1)) / 1024 if m else 0.0
    except Exception:
        return 0.0


def _run(image: Path, threads: int, n_predict: int) -> tuple[str, float, int]:
    cmd = ["llama-mtmd-cli",
           "-m", str(GGUF / "PaddleOCR-VL-1.6-GGUF.gguf"),
           "--mmproj", str(GGUF / "PaddleOCR-VL-1.6-GGUF-mmproj.gguf"),
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
    total, fast, slow = _core_counts()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--long-edge", type=int, default=1200,
                    help="thu nhỏ ảnh trước, để mỗi lượt chạy không quá lâu")
    ap.add_argument("--n-predict", type=int, default=1024)
    ap.add_argument("--out", default="reports/thread_sweep.json")
    args = ap.parse_args()

    print(f"Nhân: {total} tổng = {fast} hiệu năng + {slow} tiết kiệm")
    swap = _swap_pressure_gb()
    if swap > 2:
        print(f"\n⚠️  Swap đang dùng {swap:.1f} GB — số đo sẽ nhiễu vì lẫn cả "
              f"thời gian chờ đĩa.\n   Đóng bớt ứng dụng nặng rồi đo lại.\n",
              file=sys.stderr)

    # Các mốc đáng thử. `fast` là mốc quan trọng nhất: chỉ nhân hiệu năng.
    steps = sorted({2, 4, fast or 6, (fast or 6) + 1, total})

    pages = json.loads((BENCH / "vietnamese_pages.json").read_text("utf-8"))
    pristine = [p for p in pages
                if len(Path(p["page_info"]["image_path"]).stem.split("_")) == 3]
    page = (pristine or pages)[0]
    src = BENCH / "images" / page["page_info"]["image_path"]

    dets = sorted(page["layout_dets"],
                  key=lambda d: (d.get("order") is None, d.get("order") or 0))
    ref = "\n".join(d["text"] for d in dets if d.get("text"))

    # Thu nhỏ một lần, dùng chung cho mọi lượt — để biến duy nhất là số luồng.
    from PIL import Image
    im = Image.open(src)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if max(im.size) > args.long_edge:
        s = args.long_edge / max(im.size)
        im = im.resize((round(im.width * s), round(im.height * s)),
                       Image.Resampling.LANCZOS)
    tmp = BENCH / "_resized"
    tmp.mkdir(exist_ok=True)
    img = tmp / f"threadsweep_{args.long_edge}.jpg"
    im.save(img, quality=95)

    print(f"\nẢnh: {img.name} ({im.width}×{im.height})")
    print(f"{'luồng':>6} {'giây':>8} {'mã hoá':>9} {'sinh chữ':>10} "
          f"{'CER':>7} {'đdanh':>7}")

    rows = []
    for t in steps:
        text, secs, enc_ms = _run(img, t, args.n_predict)
        row = {"threads": t, "seconds": round(secs, 1),
               "encode_ms": enc_ms,
               "generate_s": round(secs - enc_ms / 1000, 1),
               "cer": round(cer(ref, text), 4),
               "identifier_preservation": round(
                   identifier_preservation(ref, text), 4)}
        rows.append(row)
        print(f"{t:>6} {secs:>8.1f} {enc_ms / 1000:>8.1f}s "
              f"{row['generate_s']:>9.1f}s {row['cer']:>7.3f} "
              f"{row['identifier_preservation']:>7.3f}")
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    best = min(rows, key=lambda r: r["seconds"])
    at_max = next((r for r in rows if r["threads"] == total), None)
    print(f"\nNhanh nhất: {best['threads']} luồng ({best['seconds']}s)")
    if at_max and best["threads"] != total:
        gain = (at_max["seconds"] - best["seconds"]) / at_max["seconds"]
        print(f"Nhanh hơn dùng đủ {total} luồng {gain:.0%} — "
              f"nhân tiết kiệm đang KÉO TỤT cả nhóm do đồng bộ rào chắn.")
    print(f"\nGhi: {ROOT / args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
