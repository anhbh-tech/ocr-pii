"""Sổ danh tính: mỗi tệp thuộc hồ sơ nào, bản nào là bản chính, ca nào chờ người.

    uv run python scripts/so_danh_tinh.py              # dựng sổ, in tóm tắt
    uv run python scripts/so_danh_tinh.py --kiem-tra   # dựng rồi soát bất biến

Đọc (chỉ đọc):
    ~/.private/refiny_data                 kho hồ sơ gốc — băm từng tệp
    ~/.private/ho_so_boc/o_du_kien.json    tiêu đề kênh chat của tệp hội thoại
    ~/.private/so/hop_dong.json            hợp đồng đã gộp theo số trong văn bản

Ghi (ngoài cây git, quyền 600):
    ~/.private/so/danh_tinh.json           hồ sơ, tài liệu, hợp đồng, kênh
    ~/.private/so/kenh/<kenh_id>.json      một bản ghi cho mỗi kênh
    ~/.private/so/hang_cho_xung_dot.jsonl  MỘT DÒNG MỘT CA, chờ người xác nhận

Hàng chờ được GỘP với bản cũ chứ không ghi đè: ca người duyệt đã quyết giữ
nguyên quyết định qua mọi lần chạy lại. Logic nằm ở `ocr_lab.danh_tinh`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.ade_store import _ensure_private, doc_id_for      # noqa: E402
from ocr_lab.danh_tinh import dung_so, gop_hang_cho, kiem_tra  # noqa: E402

PRIVATE = Path.home() / ".private"
KHO = PRIVATE / "refiny_data"
O_DU_KIEN = PRIVATE / "ho_so_boc" / "o_du_kien.json"
HOP_DONG = PRIVATE / "so" / "hop_dong.json"
RA = PRIVATE / "so"

QUY_TAC = [
    "khoa = tien to + so bo so 0 dem (+ '-' + so vu viec); bo duoi nuoc va so giai doan",
    "bi_danh = moi cach viet ma quy ve khoa cua ho so; ma sua giu o ma_goc_da_sua",
    "thuoc_ho_so la MANG: ma tren ten tep > ma khai tren duong dan > thu muc ho so",
    "ma ten tep khong trung thu muc lan duong dan -> xung_dot, xep tam theo cho nam, cho nguoi",
    "chi sua thua mot so 0 ben trong khi ket qua trung ma chinh duong dan khai",
    "ban y het (sha256 noi dung) gop thanh mot tai lieu; thuoc_ho_so la hop cua moi ban",
    "nhap: du thao/draft hoac so ban 0.x; khong tinh vao cong",
]


def bam(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for khoi in iter(lambda: f.read(1 << 20), b""):
            h.update(khoi)
    return h.hexdigest()


def quet(kho: Path) -> list[tuple[str, str]]:
    """(đường dẫn tương đối NFC, sha256). Bỏ tệp ẩn của hệ điều hành."""
    return [(unicodedata.normalize("NFC", str(p.relative_to(kho))), bam(p))
            for p in sorted(kho.rglob("*"))
            if p.is_file() and not p.name.startswith((".", "~$"))]


def doc_kenh(duong: Path) -> dict[str, dict]:
    if not duong.exists():
        return {}
    return {r["id"]: {"tieu_de": r["kenh"], "thanh_vien": r.get("thanh_vien")}
            for r in json.loads(duong.read_text("utf-8")) if r.get("kenh")}


def doc_hop_dong(duong: Path) -> list[dict]:
    return json.loads(duong.read_text("utf-8"))["hop_dong"] if duong.exists() else []


def ghi(duong: Path, noi_dung: str) -> None:
    tam = duong.with_name(f".{duong.name}.tam")
    tam.write_text(noi_dung, "utf-8")
    tam.chmod(0o600)
    os.replace(tam, duong)


def ghi_so(so: dict, ra: Path, kho: Path) -> None:
    _ensure_private(ra)
    hang_cho_tep = ra / "hang_cho_xung_dot.jsonl"
    cu = ([json.loads(d) for d in hang_cho_tep.read_text("utf-8").splitlines() if d.strip()]
          if hang_cho_tep.exists() else [])
    hang_cho = gop_hang_cho(cu, so.pop("hang_cho_xung_dot"))
    ghi(hang_cho_tep, "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in hang_cho))

    kenh_dir = ra / "kenh"
    _ensure_private(kenh_dir)
    moi = {k["kenh_id"] for k in so["kenh"]}
    for cu_tep in kenh_dir.glob("*.json"):          # thư mục này chỉ chứa sổ kênh
        if cu_tep.stem not in moi:
            cu_tep.unlink()
    for k in so["kenh"]:
        ghi(kenh_dir / f"{k['kenh_id']}.json", json.dumps(k, ensure_ascii=False, indent=2))

    so = {"tao_luc": datetime.now(timezone.utc).isoformat(), "kho": str(kho),
          "quy_tac": QUY_TAC, **so,
          "hang_cho_xung_dot": {"tep": str(hang_cho_tep), "so_ca": len(hang_cho),
                                "cho_nguoi_xac_nhan": sum(
                                    1 for c in hang_cho if c["trang_thai"] == "cho_nguoi_xac_nhan")}}
    ghi(ra / "danh_tinh.json", json.dumps(so, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--kho", type=Path, default=KHO, help="kho hồ sơ gốc (chỉ đọc)")
    ap.add_argument("--o-du-kien", type=Path, default=O_DU_KIEN, help="sổ ô dữ kiện (kênh)")
    ap.add_argument("--hop-dong", type=Path, default=HOP_DONG, help="sổ hợp đồng")
    ap.add_argument("--ra", type=Path, default=RA, help="thư mục ghi sổ")
    ap.add_argument("--kiem-tra", action="store_true", help="soát bất biến, lỗi thì trả mã 1")
    ap.add_argument("--khong-ghi", action="store_true", help="chỉ in tóm tắt")
    a = ap.parse_args()

    tep = quet(a.kho)
    so = dung_so(tep, doc_id_for=doc_id_for, kenh_theo_doc=doc_kenh(a.o_du_kien),
                 hop_dong=doc_hop_dong(a.hop_dong))
    loi = kiem_tra(so, tep) if a.kiem_tra else []

    t = so["tom_tat"]
    print(f"tệp: {t['so_tep']} ({t['so_tep_trong_ho_so']} trong hồ sơ, "
          f"{t['so_tep_ngoai_ho_so']} ngoài)")
    print(f"tài liệu: {t['so_tai_lieu']}; nhóm bản trùng: {t['so_nhom_ban_trung']}, "
          f"bản thừa: {t['so_ban_trung']}; dùng chung nhiều hồ sơ: {t['so_tai_lieu_dung_chung']}")
    print(f"hồ sơ: {t['so_ho_so']} ({t['so_ho_so_khong_thu_muc']} không có thư mục riêng); "
          f"mã đã sửa: {t['so_ma_da_sua']}; kênh: {t['so_kenh']}")
    print(f"hàng chờ xung đột: {t['hang_cho']['so_ca']} ca {t['hang_cho']['theo_loai']}")
    if not a.khong_ghi:
        ghi_so(so, a.ra, a.kho)
        print(f"sổ: {a.ra / 'danh_tinh.json'}")
    if a.kiem_tra:
        for x in loi:
            print(f"  LỖI {x}")
        print("kiểm tra:", "ĐẠT" if not loi else f"{len(loi)} lỗi")
    return 1 if loi else 0


if __name__ == "__main__":
    sys.exit(main())
