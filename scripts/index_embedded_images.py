#!/usr/bin/env python3
"""Quét kho, lập danh mục ảnh nhúng có chữ trong PDF digital.

CHỈ DÒ, KHÔNG ĐỌC — nên chạy được ở mọi nơi và không tốn tiền. Kết quả là
danh sách những tấm ảnh ĐÁNG đưa vào engine, kèm ảnh đã cắt sẵn để bước sau
chạy ADE Pro làm ground truth rồi so các model nhẹ vào đó.

    uv run python scripts/index_embedded_images.py --gioi-han 120

Ảnh cắt ra lưu ở `~/.private/anh_nhung` quyền 700 — chúng là mảnh của hồ sơ
khách hàng, không được nằm trong cây dự án.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ocr_lab.classify import classify_pdf  # noqa: E402
from ocr_lab.embedded_images import (  # noqa: E402
    MIN_CANH, MIN_TI_LE_TRANG, AnhNhung, DanhMuc, bam_noi_dung, phan_nhom,
)

NGUON = Path.home() / ".private" / "refiny_data"
DICH = Path.home() / ".private" / "anh_nhung"


def _bao_dam_rieng(d: Path) -> None:
    """Thư mục chứa mảnh hồ sơ khách hàng: 700, không nằm trong cây dự án."""
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)


def quet(gioi_han: int, luu_crop: bool) -> DanhMuc:
    import pymupdf
    from rapidocr_onnxruntime import RapidOCR

    # Chỉ nạp phần DÒ. Phần đọc của RapidOCR dùng model tiếng Trung và đã đo
    # được tỉ lệ dấu 0,000 — nó không tham gia việc này.
    do = RapidOCR()
    dm = DanhMuc()
    _bao_dam_rieng(DICH)

    tep = sorted(NGUON.rglob("*.pdf"))[:gioi_han]
    print(f"quét {len(tep)} PDF…")

    for i, f in enumerate(tep, start=1):
        try:
            kq = classify_pdf(f)
        except Exception:       # noqa: BLE001 — PDF hỏng không được dừng cả lượt
            continue
        # CHỈ xét trang digital: trang scan thì cả trang là một tấm ảnh, và
        # đó là bài toán OCR thông thường — không phải bài toán này.
        #
        # `PageResult.index` là 0-based; số trang hiển thị là 1-based. Giữ
        # 0-based ở đây để truy `doc[i]` trực tiếp, đổi khi ghi ra.
        digital = {p.index for p in kq.pages if p.kind.name == "BORN_DIGITAL"}
        if not digital:
            continue

        rel = str(f.relative_to(NGUON))
        try:
            doc = pymupdf.open(f)
        except Exception:       # noqa: BLE001
            continue
        try:
            for chi_so in sorted(digital):
                so_trang = chi_so + 1
                page = doc[chi_so]
                dien_tich_trang = page.rect.width * page.rect.height
                n_ky_tu = len(page.get_text().strip())

                for im in page.get_images(full=True):
                    xref = im[0]
                    hcn = page.get_image_rects(xref) or []
                    if not hcn:
                        continue
                    dt = max(r.width * r.height for r in hcn)
                    ti_le = dt / max(dien_tich_trang, 1)
                    if ti_le < MIN_TI_LE_TRANG:
                        continue

                    try:
                        pix = pymupdf.Pixmap(doc, xref)
                        if pix.n - pix.alpha >= 4:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                    except Exception:   # noqa: BLE001
                        continue
                    if pix.width < MIN_CANH or pix.height < MIN_CANH:
                        continue

                    png = pix.tobytes("png")
                    a = AnhNhung(tep=rel, trang=so_trang, xref=xref,
                                 rong=pix.width, cao=pix.height,
                                 ti_le_trang=round(ti_le, 4),
                                 van_ban_lop_text=n_ky_tu,
                                 bam_anh=bam_noi_dung(png))

                    # Ghi ra đĩa TRƯỚC khi dò: bộ dò nhận đường dẫn, và ảnh
                    # này còn dùng lại ở bước chạy engine.
                    ra = DICH / f"{a.bam_anh}.png"
                    if not ra.is_file():
                        ra.write_bytes(png)
                    a.duong_dan_crop = str(ra)

                    hop, _ = do(str(ra), use_det=True, use_cls=False,
                                use_rec=False)
                    if hop:
                        a.n_vung_chu = len(hop)
                        tong = 0.0
                        for diem in hop:
                            xs = [float(p[0]) for p in diem]
                            ys = [float(p[1]) for p in diem]
                            tong += (max(xs) - min(xs)) * (max(ys) - min(ys))
                        a.ti_le_dien_tich_chu = round(
                            tong / max(pix.width * pix.height, 1), 4)
                    dm.anh.append(a)
        finally:
            doc.close()

        if i % 20 == 0:
            print(f"  {i}/{len(tep)} tệp · {len(dm.anh)} ảnh")

    # Đếm lặp trên TOÀN KHO rồi mới phân nhóm — xem ghi chú trong module.
    dem = {}
    for a in dm.anh:
        dem[a.bam_anh] = dem.get(a.bam_anh, 0) + 1
    for a in dm.anh:
        phan_nhom(a, dem)

    if not luu_crop:
        for a in dm.anh:
            if a.nhom != "noi_dung" and a.duong_dan_crop:
                Path(a.duong_dan_crop).unlink(missing_ok=True)
                a.duong_dan_crop = ""
    return dm


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gioi-han", type=int, default=120)
    ap.add_argument("--giu-moi-crop", action="store_true",
                    help="giữ cả ảnh nhóm trống/khung (mặc định chỉ giữ nội dung)")
    ap.add_argument("--ra", type=Path,
                    default=Path("reports/danh_muc_anh_nhung.json"))
    a = ap.parse_args()

    t0 = time.perf_counter()
    dm = quet(a.gioi_han, a.giu_moi_crop)
    giay = time.perf_counter() - t0

    tt = dm.tom_tat()
    print(f"\n{tt['tong_anh']} ảnh nhúng trong {giay:.0f}s")
    print(f"  trống    {tt['trong']:>5}   không có vùng chữ")
    print(f"  khung    {tt['khung']:>5}   logo / chân trang lặp khắp kho")
    print(f"  NỘI DUNG {tt['noi_dung']:>5}   chữ thật nằm trong ảnh "
          f"({tt['so_tep_co_noi_dung']} tệp)")
    print(f"           {tt['noi_dung_duy_nhat']:>5}   ẢNH KHÁC NHAU — "
          f"đây mới là số việc thật")

    nd = dm.duy_nhat("noi_dung")
    if nd:
        print("\n10 tấm đáng đọc nhất (theo số vùng chữ):")
        for x in sorted(nd, key=lambda z: -z.n_vung_chu)[:10]:
            print(f"  {x.n_vung_chu:>3} vùng · {x.rong}x{x.cao} · "
                  f"{Path(x.tep).name[:44]} tr{x.trang}")

    a.ra.parent.mkdir(parents=True, exist_ok=True)
    a.ra.write_text(json.dumps(
        {"tom_tat": tt, "anh": [vars(x) for x in dm.anh]},
        ensure_ascii=False, indent=2), "utf-8")
    print(f"\n→ {a.ra}")
    print(f"→ ảnh cắt: {DICH} (quyền 700)")


if __name__ == "__main__":
    main()
