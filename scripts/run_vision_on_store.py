"""Chạy Apple Vision lên đúng những tài liệu đã có trong kho ADE.

VÌ SAO SCRIPT NÀY NẰM Ở `ocr-lab`, KHÔNG PHẢI `ocr-lab-gpu`
───────────────────────────────────────────────────────────
Hai dự án có quy tắc "không sửa chéo". Script này chỉ ĐỌC `ocr-lab-gpu` như
một thư viện ngoài (thêm vào `sys.path`, không import ngược lại), còn nơi ghi
kết quả là kho của `ocr-lab` — vì trang đối chiếu ở đây, và so sánh chỉ có
nghĩa khi hai bản chép nằm cạnh nhau trên cùng một tài liệu.

VÌ SAO DÙNG LẠI ẢNH TRANG ĐÃ RENDER
───────────────────────────────────
Kho ADE đã có `pages/p1.png` (200 DPI) cho mỗi tài liệu. Render lại từ PDF
gốc bằng tham số khác sẽ cho ảnh khác, và khi đó chênh lệch giữa hai engine
lẫn cả chênh lệch do ảnh — không tách được nguyên nhân.

Dùng chung đúng một tệp ảnh thì mọi khác biệt còn lại là của engine.

KHÔNG GỌI API, KHÔNG TỐN TIỀN. Vision chạy cục bộ trên Neural Engine.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: `ocr-lab-gpu` là dự án ANH EM, không phải phụ thuộc được cài. Thêm vào
#: sys.path thay vì `uv add` vì nó không có trên PyPI và không nên bị ghim
#: phiên bản — ta muốn luôn chạy mã mới nhất của nó khi so sánh.
GPU_ROOT = Path.home() / "ocr-lab-gpu"
sys.path.insert(0, str(GPU_ROOT / "src"))

from ocr_lab.ade_store import DEFAULT_STORE                        # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--doc", default="", help="chỉ một doc_id")
    ap.add_argument("--force", action="store_true",
                    help="chạy lại cả tài liệu đã có vision.json")
    args = ap.parse_args()

    try:
        from ocr_gpu.engines.vision import VisionEngine
    except ImportError as exc:
        print(f"Không nạp được ocr-lab-gpu: {exc}", file=sys.stderr)
        print(f"Kiểm tra: {GPU_ROOT}/src/ocr_gpu/engines/vision.py",
              file=sys.stderr)
        return 1

    eng = VisionEngine()
    docs = sorted(d for d in args.store.iterdir()
                  if d.is_dir() and (d / "parse.json").is_file())
    if args.doc:
        docs = [d for d in docs if d.name == args.doc]
    if not docs:
        print("Kho rỗng.", file=sys.stderr)
        return 1

    print(f"Kho    : {args.store}")
    print(f"Engine : Apple Vision (cục bộ, KHÔNG gọi API)\n")
    print(f"{'tài liệu':<30} {'trang':>5} {'ký tự':>7} {'dòng':>5} {'giây':>6}")
    print("─" * 60)

    total_pages = total_chars = 0
    t_all = time.perf_counter()

    for d in docs:
        out_file = d / "vision.json"
        if out_file.is_file() and not args.force:
            print(f"{d.name[:28]:<30} {'—':>5} (đã có, bỏ qua)")
            continue

        meta = json.loads((d / "meta.json").read_text("utf-8"))
        name = Path(meta.get("source", d.name)).name
        pages_dir = d / "pages"
        # Ảnh trang lưu dạng `.jpg` (ảnh gốc chép thẳng) hoặc `.png` (PDF đã
        # render). Bắt cả hai — dò đúng một đuôi thì mất sạch nhóm còn lại mà
        # vẫn chạy xong không lỗi, kiểu hỏng im lặng khó thấy nhất.
        imgs = sorted(
            [p for p in pages_dir.glob("p*.*")
             if p.suffix.lower() in (".png", ".jpg", ".jpeg")],
            key=lambda p: int("".join(c for c in p.stem if c.isdigit()) or 0),
        ) if pages_dir.is_dir() else []
        if not imgs:
            print(f"{name[:28]:<30} {'—':>5} (không có ảnh trang)")
            continue

        t0 = time.perf_counter()
        pages_out = []
        for img in imgs:
            page = eng.read_page(img)
            # Giữ nguyên cấu trúc Vision trả về: text + bbox từng dòng. Không
            # ép về khuôn của ADE — hai engine chia phần tử khác nhau, và ép
            # khuôn là đã áp một cách diễn giải lên dữ liệu trước khi người
            # soát kịp nhìn.
            pages_out.append({
                "page": int("".join(c for c in img.stem if c.isdigit()) or 1),
                "width": page.width,
                "height": page.height,
                "text": page.text,
                "lines": [
                    {"text": s.text, "confidence": s.confidence,
                     "bbox_topleft": s.bbox_topleft}
                    for s in page.lines
                ],
            })
        dt = time.perf_counter() - t0

        chars = sum(len(p["text"]) for p in pages_out)
        lines = sum(len(p["lines"]) for p in pages_out)
        payload = {"engine": "apple-vision", "doc_id": d.name,
                   "source": meta.get("source", ""), "seconds": round(dt, 2),
                   "pages": pages_out}
        out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        out_file.chmod(0o600)

        total_pages += len(pages_out)
        total_chars += chars
        print(f"{name[:28]:<30} {len(pages_out):>5} {chars:>7} {lines:>5} "
              f"{dt:>6.2f}")

    print("─" * 60)
    print(f"{total_pages} trang · {total_chars} ký tự · "
          f"{time.perf_counter() - t_all:.1f}s tổng")
    print("\nVision chạy CỤC BỘ — không tệp nào rời khỏi máy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
