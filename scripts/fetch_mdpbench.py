"""Tải lát cắt tiếng Việt của MDPBench — 160 trang, ~176 MB.

Vì sao chỉ tải lát VN: toàn bộ bộ này 2 720 ảnh × 17 ngôn ngữ ≈ 3 GB. Ta chỉ
cần đúng 160 trang tiếng Việt — cùng tập mà SenOCR-Vi công bố điểm trên đó,
nên tái lập được bảng của họ.

Ground truth `MDPBench_public.json` nặng 73 MB, theo khuôn OmniDocBench:

    [{"page_info": {"image_path": ..., "page_attribute": {"language": ...}},
      "layout_dets": [{"category_type": "text_block", "text": ..., "poly": ...}]}]

Lọc theo `page_info.page_attribute.language == "Vietnamese"`.

Chạy:
    uv run python scripts/fetch_mdpbench.py
    uv run python scripts/fetch_mdpbench.py --limit 10   # thử nhanh
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "benchmarks" / "mdpbench"

REPO = "Delores-Lin/MDPBench"
GT_NAME = "MDPBench_public.json"
IMG_PREFIX = "MDPBench_img_public"
LANGUAGE = "Vietnamese"


def _download_ground_truth(force: bool) -> Path:
    from huggingface_hub import hf_hub_download

    dest = OUT / GT_NAME
    if dest.exists() and not force:
        print(f"đã có ground truth: {dest} "
              f"({dest.stat().st_size / 1e6:.1f} MB)")
        return dest

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"tải {GT_NAME} (~73 MB)…")
    got = hf_hub_download(REPO, GT_NAME, repo_type="dataset",
                          local_dir=str(OUT))
    return Path(got)


def _vietnamese_pages(gt_path: Path) -> list[dict]:
    """Lọc các trang tiếng Việt và kiểm ngay con số 160.

    Nếu ra khác 160 thì bộ dữ liệu đã đổi so với lúc SenOCR-Vi đo, và bảng
    điểm của họ không còn là mốc so sánh hợp lệ nữa. Phải biết điều đó TRƯỚC
    khi chạy model, chứ không phải sau khi thấy số lệch rồi đổ cho model.
    """
    data = json.loads(gt_path.read_text(encoding="utf-8"))
    pages = [p for p in data
             if p.get("page_info", {}).get("page_attribute", {})
                 .get("language") == LANGUAGE]

    print(f"\nTrang tiếng Việt: {len(pages)}")
    if len(pages) != 160:
        print(f"  ⚠️  CẢNH BÁO: SenOCR-Vi công bố điểm trên đúng 160 trang. "
              f"Ở đây có {len(pages)} — bộ dữ liệu có thể đã thay đổi, "
              f"bảng điểm của họ không còn so trực tiếp được.", file=sys.stderr)
    return pages


def _summarise(pages: list[dict]) -> None:
    """In đúng những con số quyết định bộ này có hợp với ta không."""
    sys.path.insert(0, str(ROOT / "src"))
    from ocr_lab.metrics import accent_share

    blocks = Counter()
    texts: list[str] = []
    conditions = Counter()
    doc_types = Counter()
    pristine = 0

    for p in pages:
        name = Path(p["page_info"]["image_path"]).stem
        # Tên tệp mang cả metadata: vi_<loại>_<số>[_<điều kiện>…]
        # ví dụ: vi_exampaper_3_bend-in_hold_left_outdoor_shadow_light
        parts = name.split("_")
        doc_types[parts[1] if len(parts) > 1 else "?"] += 1
        conds = parts[3:]            # sau "vi", loại, số thứ tự
        if not conds:
            pristine += 1            # bản gốc sạch, không biến dạng
        for c in conds:
            conditions[c] += 1
        for det in p.get("layout_dets", []):
            blocks[det.get("category_type", "?")] += 1
            t = det.get("text")
            if t:
                texts.append(t)

    joined = "\n".join(texts)
    print(f"Khối có chữ: {len(texts)}")
    print(f"Tỉ lệ dấu ground truth: {accent_share(joined):.3f} "
          f"(tiếng Việt thật ≈ 0,217)")
    print(f"\nLoại khối: {dict(blocks.most_common(8))}")
    print(f"Loại tài liệu: {dict(doc_types.most_common(10))}")
    photographed = len(pages) - pristine
    print(f"\nẢnh CHỤP có biến dạng: {photographed}/{len(pages)}  "
          f"(bản gốc sạch: {pristine})")
    print("  ← đây là lý do chọn bộ này: hỏng trong kho thật của ta là 51/51 "
          "tệp ẢNH, 0 PDF")
    if conditions:
        for cond, n in conditions.most_common(14):
            print(f"    {cond:22s} {n:3d}")


def _download_images(pages: list[dict], limit: int | None) -> None:
    """Tải ảnh bằng `snapshot_download` — song song, nối lại được khi đứt.

    Ảnh nằm ở `MDPBench_img_public/<tên>`; ground truth chỉ ghi tên trần, nên
    phải tự ghép tiền tố. Đã đối chiếu: 160 tên trong ground truth khớp đúng
    160 tệp `vi_*` trong repo, không thiếu không thừa.
    """
    from huggingface_hub import snapshot_download

    names = [Path(p["page_info"]["image_path"]).name for p in pages]
    if limit:
        names = names[:limit]

    img_dir = OUT / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    missing = [n for n in names if not (img_dir / n).exists()]
    if not missing:
        print(f"\nĐã có đủ {len(names)} ảnh ở {img_dir}")
        return

    print(f"\nTải {len(missing)} ảnh (~{len(missing) * 1.1:.0f} MB)…")
    staging = OUT / "_hf"
    snapshot_download(
        REPO, repo_type="dataset", local_dir=str(staging),
        allow_patterns=[f"{IMG_PREFIX}/{n}" for n in missing],
        max_workers=8)

    moved = 0
    for n in missing:
        src = staging / IMG_PREFIX / n
        if src.exists():
            src.replace(img_dir / n)
            moved += 1

    have = sum(1 for n in names if (img_dir / n).exists())
    print(f"Ảnh: {have}/{len(names)} → {img_dir}")
    if have != len(names):
        print(f"  ⚠️  thiếu {len(names) - have} ảnh — kiểm lại trước khi đo",
              file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="chỉ tải N ảnh đầu (để thử)")
    ap.add_argument("--force", action="store_true", help="tải lại ground truth")
    ap.add_argument("--no-images", action="store_true",
                    help="chỉ lấy ground truth, không tải ảnh")
    args = ap.parse_args()

    gt = _download_ground_truth(args.force)
    pages = _vietnamese_pages(gt)
    _summarise(pages)

    manifest = OUT / "vietnamese_pages.json"
    manifest.write_text(json.dumps(pages, ensure_ascii=False),
                        encoding="utf-8")
    print(f"\nGhi lát VN: {manifest} ({manifest.stat().st_size / 1e6:.1f} MB)")

    if not args.no_images:
        _download_images(pages, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
