#!/usr/bin/env python3
"""Chạy ADE Pro trên các ẢNH NHÚNG — dựng ground truth cho bài toán nhỏ.

VÌ SAO CHẠY RIÊNG TRÊN ẢNH, KHÔNG PHẢI TRÊN TRANG
─────────────────────────────────────────────────
Trang PDF digital đã có lớp text hoàn hảo. Gửi cả trang cho Pro là trả tiền
để đọc lại thứ đã đọc được, và kết quả sẽ bị lớp text áp đảo — chữ trong
ảnh chỉ là vài phần trăm nội dung, nên mọi chỉ số tính trên cả trang đều
không nhìn thấy nó.

Gửi ĐÚNG tấm ảnh thì ngược lại: 100% nội dung trả về là thứ ta cần đo, và
mỗi ảnh chỉ tốn 1 trang credit.

CHI PHÍ
───────
    Pro:    0,9 credits/ảnh = $0,009
    38 ảnh  ≈ $0,34

TỐN TIỀN THẬT — script đòi `--xac-nhan` và in dự toán trước.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ocr_lab.engines import load_dotenv  # noqa: E402

DANH_MUC = Path("reports/danh_muc_anh_nhung.json")
KHO = Path.home() / ".private" / "anh_nhung_gt"


def _bao_dam_rieng(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)


def nap_viec(gioi_han: int) -> list[dict]:
    """Ảnh nhóm nội dung, MỖI ẢNH MỘT LẦN.

    Dedupe theo băm nội dung: kho có bản sao cùng tài liệu ở nhiều thư mục,
    và trả tiền hai lần cho cùng một tấm ảnh là lãng phí thuần tuý.
    """
    if not DANH_MUC.is_file():
        raise SystemExit(
            f"chưa có {DANH_MUC} — chạy scripts/index_embedded_images.py trước")
    d = json.loads(DANH_MUC.read_text("utf-8"))
    thay: dict[str, dict] = {}
    for a in d["anh"]:
        if a["nhom"] == "noi_dung" and a["bam_anh"] not in thay:
            if a.get("duong_dan_crop") and Path(a["duong_dan_crop"]).is_file():
                thay[a["bam_anh"]] = a
    viec = sorted(thay.values(), key=lambda x: -x["n_vung_chu"])
    return viec[:gioi_han] if gioi_han else viec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gioi-han", type=int, default=0, help="0 = tất cả")
    ap.add_argument("--xac-nhan", action="store_true",
                    help="BẮT BUỘC để thực sự gọi API — mặc định chỉ dự toán")
    a = ap.parse_args()

    viec = nap_viec(a.gioi_han)
    gia = len(viec) * 0.009
    print(f"{len(viec)} ảnh khác nhau · ADE Pro 0,9 credits/ảnh · ≈ ${gia:.3f}")

    if not a.xac_nhan:
        print("\nCHƯA CHẠY. Thêm --xac-nhan để gọi API thật.")
        for x in viec[:8]:
            print(f"  {x['n_vung_chu']:>3} vùng · {x['rong']}x{x['cao']} · "
                  f"{Path(x['tep']).name[:46]} tr{x['trang']}")
        return

    load_dotenv()
    from ocr_lab.engines.ade import AdeEngine

    _bao_dam_rieng(KHO)
    # Tên model phải lấy từ script Pro đang chạy được, không đoán: một tên
    # sai trả 422 cho CẢ MẺ (đã mất một lượt vì `dpt-2-latest` bịa ra).
    eng = AdeEngine(model="dpt-3-pro", service_tier="standard")

    xong, loi, credits = 0, 0, 0.0
    t0 = time.perf_counter()
    for i, x in enumerate(viec, start=1):
        ra = KHO / f"{x['bam_anh']}.json"
        if ra.is_file():
            xong += 1
            continue
        try:
            kq = eng.parse_document(Path(x["duong_dan_crop"]))
        except Exception as e:      # noqa: BLE001 — một ảnh lỗi không dừng cả mẻ
            loi += 1
            print(f"  [{i}/{len(viec)}] LỖI {type(e).__name__}: {str(e)[:90]}")
            continue
        cr = (kq.get("metadata", {}).get("billing", {})
              .get("total_credits", 0.9))
        credits += cr
        ra.write_text(json.dumps(
            {"bam_anh": x["bam_anh"], "tep": x["tep"], "trang": x["trang"],
             "markdown": kq.get("markdown", ""), "credits": cr,
             "parse": kq}, ensure_ascii=False, indent=2), "utf-8")
        xong += 1
        n = len(kq.get("markdown", ""))
        print(f"  [{i}/{len(viec)}] {n:>5} ký tự · {cr} cr · "
              f"{Path(x['tep']).name[:40]}")

    print(f"\n{xong} xong · {loi} lỗi · {credits:.1f} credits "
          f"(${credits / 100:.3f}) · {time.perf_counter() - t0:.0f}s")
    print(f"→ {KHO} (quyền 700)")


if __name__ == "__main__":
    main()
