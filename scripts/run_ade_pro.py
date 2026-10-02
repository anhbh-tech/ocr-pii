"""Chạy ADE Pro lên những tài liệu ĐÃ CÓ trong kho, để so với Verity.

VÌ SAO KHÔNG DÙNG `run_ade_pipeline.py --model dpt-3-pro`
────────────────────────────────────────────────────────
Script kia duyệt từ thư mục hồ sơ gốc và bỏ qua tài liệu đã có trong kho —
đúng cho lần chạy đầu, nhưng ở đây ta CỐ Ý chạy lại đúng những tài liệu đó
bằng model khác. Nó cũng sẽ quét cả ảnh sản phẩm mà ta không cần.

Chạy từ KHO thay vì từ thư mục gốc còn bảo đảm một điều quan trọng hơn: hai
bản chép chắc chắn nói về cùng một tệp, cùng một ảnh trang đã render. So hai
engine trên hai tập tài liệu hơi khác nhau là so nhầm.

GIÁ: Pro standard 0,9 credits/trang — GẤP 3 Verity (0,3). Script in ước tính
và đòi `--yes` trước khi gửi.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.ade_store import DEFAULT_STORE, save_result          # noqa: E402
from ocr_lab.engines import load_dotenv                          # noqa: E402
from ocr_lab.engines.ade import AdeEngine                        # noqa: E402

#: Từ khoá nhận diện hợp đồng / biên bản scan và giấy tờ tuỳ thân.
#:
#: Dùng tên tệp chứ không dùng nội dung: nội dung thì phải đọc, mà đọc là
#: chính việc ta đang định trả tiền để làm.
HOP_DONG = ("hddvpl", "hop dong", "bien ban", "bb ban", "de nghi",
            "agreement", "hop dong dich vu", "sevices", "services")
GIAY_TO = ("cccd",)


def loai_tai_lieu(ten: str) -> str:
    t = ten.lower()
    if any(k in t for k in GIAY_TO):
        return "cccd"
    if any(k in t for k in HOP_DONG):
        return "hop_dong"
    return "khac"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--model", default="dpt-3-pro")
    ap.add_argument("--tier", default="standard",
                    choices=("standard", "priority"))
    ap.add_argument("--loai", default="hop_dong,cccd",
                    help="loại tài liệu cần chạy, cách nhau bằng dấu phẩy")
    ap.add_argument("--max-credits", type=float, default=80.0)
    ap.add_argument("--force", action="store_true",
                    help="chạy lại cả tài liệu đã có parse_pro.json")
    ap.add_argument("--yes", action="store_true",
                    help="xác nhận gửi thật (không có cờ này = chỉ ước tính)")
    args = ap.parse_args()

    muon = {s.strip() for s in args.loai.split(",") if s.strip()}
    viec = []
    for d in sorted(args.store.iterdir()):
        if not (d / "parse.json").is_file():
            continue
        if (d / "parse_pro.json").is_file() and not args.force:
            continue
        meta = json.loads((d / "meta.json").read_text("utf-8"))
        src = meta.get("source", "")
        ten = Path(src).name
        if loai_tai_lieu(ten) not in muon:
            continue
        n_trang = len(meta.get("pages") or []) or 1
        viec.append((d, src, ten, n_trang))

    if not viec:
        print("Không có tài liệu nào cần chạy.")
        return 0

    gia = 0.9 if args.model.endswith("pro") else 0.3
    if args.tier == "priority":
        gia *= 2
    tong_trang = sum(v[3] for v in viec)
    uoc = tong_trang * gia

    print(f"Kho   : {args.store}")
    print(f"Model : {args.model} · tier {args.tier}")
    print(f"Loại  : {', '.join(sorted(muon))}\n")
    for _, _, ten, n in viec:
        print(f"   {ten[:52]:<54} {n:>2} trang")
    print(f"\n{len(viec)} tài liệu · {tong_trang} trang")
    print(f"Ước tính: {uoc:.1f} credits ≈ ${uoc / 100:.3f}"
          f"   (Verity cùng số trang: {tong_trang * 0.3:.1f} cr)")

    if uoc > args.max_credits:
        print(f"\nVƯỢT TRẦN {args.max_credits} credits — dừng.", file=sys.stderr)
        return 1
    if not args.yes:
        print("\nChưa gửi gì cả. Thêm --yes để chạy thật.")
        return 0

    print("\n⚠ Đây là HỒ SƠ KHÁCH HÀNG THẬT, đang gửi tới LandingAI.\n")
    # `build_engine` gọi `load_dotenv()` giúp; dựng thẳng thì phải tự gọi,
    # nếu không khoá trong `.env` không tới được engine.
    load_dotenv()
    # Dựng thẳng AdeEngine thay vì qua `build_engine`: registry trả kiểu
    # chung `OcrEngine` không có `parse_document` (đường trả về cấu trúc +
    # toạ độ), nên đi qua nó là mất kiểm tra kiểu ở đúng chỗ dễ sai nhất.
    eng = AdeEngine(model=args.model, service_tier=args.tier)

    print(f"{'tài liệu':<46} {'phần tử':>8} {'ký tự':>7} {'credits':>8}")
    print("─" * 74)
    tong_cr = 0.0
    loi = 0
    goc = Path.home() / ".private" / "refiny_data"
    for d, src, ten, _ in viec:
        try:
            # `source` trong meta là đường dẫn TƯƠNG ĐỐI so với thư mục hồ sơ
            # gốc — kho cố ý không lưu đường tuyệt đối để không rò cấu trúc
            # máy nếu tệp meta lọt ra ngoài.
            data = eng.parse_document(goc / src)
        except Exception as exc:
            # Một tài liệu hỏng không được làm mất lượt đã trả tiền cho các
            # tài liệu trước nó.
            print(f"{ten[:44]:<46} LỖI: {type(exc).__name__}: {str(exc)[:40]}")
            loi += 1
            continue

        meta_api = data.get("metadata") or {}
        cr = ((meta_api.get("billing") or {}).get("total_credits")) or 0.0
        md = data.get("markdown") or ""
        n_el = sum(len(pg.get("children") or [])
                   for pg in (data.get("structure") or {}).get("children") or [])

        save_result(args.store, d.name, data, source=src,
                    model=args.model, credits=cr,
                    pages=json.loads((d / "meta.json").read_text("utf-8"))
                    .get("pages"), variant="pro")
        tong_cr += cr
        print(f"{ten[:44]:<46} {n_el:>8} {len(md):>7} {cr:>8.1f}")

    print("─" * 74)
    print(f"Xong {len(viec) - loi}/{len(viec)} tài liệu · {tong_cr:.1f} credits "
          f"≈ ${tong_cr / 100:.3f}")
    if loi:
        print(f"{loi} tài liệu lỗi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
