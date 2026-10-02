"""Sổ mã lạc đàn — kiểm trên một kho GIẢ dựng trong tmp_path.

Không mã hồ sơ, tên nhãn hay số hiệu nào ở đây là của khách thật.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.ade_store import doc_id_for  # noqa: E402


def _nap():
    spec = importlib.util.spec_from_file_location(
        "so_ma_lac_test", ROOT / "scripts" / "so_ma_lac.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m        # dataclass tra module qua sys.modules
    spec.loader.exec_module(m)
    return m


sml = _nap()

MANG = "Phòng IP/1. Mảng thử"
A = f"{MANG}/501.US. ALPHA in class 009"
B = f"{MANG}/60. US. 01 tac pham GAMMA"
C = "Phòng IP/5. Mảng khác/320. Vu viec OMEGA"

TEP = [
    *(f"{A}/1. Filing/NH501.US_Tai lieu {i}_0{i}0125.pdf" for i in range(1, 6)),
    f"{A}/1. Filing/NH501.US_VAT_010125.pdf",
    f"{A}/1. Filing/NH501.US_TM Application - Alpha (009) - 90000002_010125.pdf",
    # lỗi gõ lệch 1 chữ số
    f"{A}/0. Info/NH502.US_Info_010125.docx",
    # hệ đánh số song song, kèm thư mục con mang số tra cứu
    f"{A}/0. Info/2001. Tra cuu ALPHA/TV2001_Tong hop doi chung_010125.pdf",
    f"{A}/0. Info/2001. Tra cuu ALPHA/TV2001.2_Ket qua_020125.docx",
    # tệp để nhầm: mã khác + tên nhãn khác, không có thư mục riêng
    f"{A}/Accounting/Bo (NH777, NH501)/NH777.US_BETA_Receipt - 90000001.pdf",
    f"{A}/Accounting/Bo (NH777, NH501)/NH777.US_(signed) BETA_HD_010125.pdf",
    f"{A}/Accounting/Bo (NH777, NH501)/NH777.US_VAT_020125.pdf",
    f"{A}/Accounting/Bo (NH777, NH501)/NH777.US, NH501.US_(scan) Agreement_010125.pdf",
    # lỗi gõ trong tệp nhiều mã: mã đa số đã có trong tên nên ứng viên là NH777
    f"{A}/Accounting/Bo (NH777, NH501)/NH7777.US, NH501.US_Chuyen tien_030125.pdf",
    # lệch 3 chữ số: chỉ nội dung mới quyết được
    f"{A}/Accounting/Draft/NH388.US_Cv letter_010125.docx",
    # không phải mã hồ sơ
    f"{A}/0. Info/NQ1234 van ban.pdf",
    # tệp chung hai hồ sơ đều có thư mục
    f"{A}/3. OA/NH501.US, BQ060.US_Tin nhan_010125.docx",
    *(f"{B}/BQ060.US_Tai lieu {i}_0{i}0225.pdf" for i in range(1, 4)),
    *(f"{C}/TV044-320_Tai lieu {i}_0{i}0325.pdf" for i in range(1, 4)),
    "Phòng IP/1. Mảng thử/_Quy trinh chuan/Mau.docx",
]


def _dung_kho(tmp_path: Path, them: list[str] = ()) -> Path:
    kho = tmp_path / "kho"
    for rel in [*TEP, *them]:
        p = kho / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return kho


def _ghi_parse(store: Path, rel: str, md: str) -> None:
    d = store / doc_id_for(unicodedata.normalize("NFC", rel))
    d.mkdir(parents=True, exist_ok=True)
    (d / "parse_pro.json").write_text(json.dumps({"markdown": md}), "utf-8")


def _dong(so: dict, ma: str) -> dict:
    [d] = [r for r in so["ma_lac"] if r["ma_lac"] == ma]
    return d


@pytest.fixture
def so(tmp_path):
    kho = _dung_kho(tmp_path)
    store = tmp_path / "store"
    _ghi_parse(store, f"{A}/Accounting/Draft/NH388.US_Cv letter_010125.docx",
               "Kính gửi\nRe: hồ sơ NH501.US nhãn ALPHA\n")
    return sml.lap_so(kho, store, None)


# ── tách mã ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ten, khoa", [
    ("NH501.US_Info_010125", ["NH501"]),
    ("NH501. US. (scan) Phu luc", ["NH501"]),
    ("BQ060,US_Tai lieu", ["BQ060"]),
    ("TV071-88_Tu van 2_010125", ["TV071-88"]),
    ("TV2001.2_Ket qua", ["TV2001.2"]),
    ("TV2001. Tong hop", ["TV2001"]),
    ("NH777.US, NH778,US, NH501.US_(scan) Agreement", ["NH777", "NH778", "NH501"]),
    ("CCCD", []),
    ("Ty gia 140825", []),
    ("Doc23", []),
])
def test_tach_ma_dau(ten, khoa):
    ma, _ = sml.tach_ma_dau(ten)
    assert [m.khoa for m in ma] == khoa


def test_khoang_cach_giu_so_0_dau():
    assert sml.khoang_cach("0071-88", "071-88") == 1
    assert sml.khoang_cach("046", "064") == 2
    assert sml.khoang_cach("777", "1234") == 4


def test_bo_dau_tach_ca_chu_d():
    assert sml.khong_dau("Hợp đồng ĐƠN") == "Hop dong DON"


# ── đa số và ba loại ────────────────────────────────────────────────────

def test_ma_da_so_moi_thu_muc(so):
    hs = {h["thu_muc"]: h for h in so["ho_so"]}
    assert set(hs) == {A, B, C}
    assert hs[A]["ma_da_so"] == "NH501"
    assert hs[A]["khop_so_thu_muc"] is True
    assert hs[B]["ma_da_so"] == "BQ060"
    assert hs[C]["ma_da_so"] == "TV044-320"
    assert hs[C]["khop_so_thu_muc"] is True
    assert so["tom_tat"]["so_tep_ngoai_thu_muc_ho_so"] == 1


def test_loi_go_lech_mot_chu_so(so):
    d = _dong(so, "NH502")
    assert d["loai"] == "loi_go"
    assert d["ma_da_so"] == "NH501"
    assert d["so_tep_da_so"] == 10
    assert d["so_lan_xuat_hien"] == 1
    assert d["tep_lo_ra"][0]["duong_dan"].endswith("NH502.US_Info_010125.docx")
    dx = d["de_xuat"]
    assert dx["ma_de_xuat"] == "NH501"
    assert dx["so_chu_so_lech"] == 1
    assert dx["can_nguoi_chot"] is False
    assert dx["ten_de_xuat"] == "NH501.US_Info_010125.docx"
    assert "10/" in dx["bang_chung_da_so"]


def test_loi_go_trong_tep_nhieu_ma_khong_de_xuat_ma_da_co_trong_ten(so):
    d = _dong(so, "NH7777")
    assert d["loai"] == "loi_go"
    assert d["de_xuat"]["ma_de_xuat"] == "NH777"
    assert d["de_xuat"]["ten_de_xuat"].startswith("NH777.US, NH501.US_")


def test_lech_qua_nguong_can_noi_dung_xac_nhan(so):
    d = _dong(so, "NH388")
    assert d["loai"] == "loi_go"
    assert d["de_xuat"]["so_chu_so_lech"] == 3
    assert d["de_xuat"]["vuot_nguong"] is True
    assert d["de_xuat"]["xac_nhan_noi_dung"] is True
    assert "NH501" in d["de_xuat"]["noi_dung"]["dong_trich"]


def test_lech_qua_nguong_khong_co_ban_doc_thi_chua_phan_loai(tmp_path):
    so = sml.lap_so(_dung_kho(tmp_path), tmp_path / "store_rong", None)
    d = _dong(so, "NH388")
    assert d["loai"] == "chua_phan_loai"
    assert "nội dung" in d["ly_do"]


def test_danh_so_song_song_va_lien_ket(so):
    for ma in ("TV2001", "TV2001.2"):
        d = _dong(so, ma)
        assert d["loai"] == "danh_so_song_song"
        assert d["ma_da_so"] == "NH501"
        assert "de_xuat" not in d
    [lk] = [r for r in so["lien_ket_so_tra_cuu"] if r["goc"] == "TV2001"]
    assert lk["ma_ho_so"] == "NH501"
    assert sorted(lk["bien_the"]) == ["TV2001", "TV2001.2"]
    assert lk["thu_muc_con_mang_so"] == ["0. Info/2001. Tra cuu ALPHA"]


def test_de_nham_ho_so_giao_nguoi_kem_ten_nhan(so):
    d = _dong(so, "NH777")
    assert d["loai"] == "de_nham_ho_so"
    assert d["ten_nhan"] == ["BETA"]
    assert d["so_lan_xuat_hien"] == 4
    [g] = so["giao_nguoi_xu_ly"]
    assert g["ma"] == "NH777" and g["ten_nhan"] == ["BETA"]
    assert g["co_thu_muc_ho_so_rieng"] is False
    assert g["thu_muc_con_khai_ma"] == ["Accounting/Bo (NH777, NH501)"]
    nham = {Path(t["duong_dan"]).name for t in g["tep_de_nham"]}
    assert nham == {"NH777.US_BETA_Receipt - 90000001.pdf",
                    "NH777.US_(signed) BETA_HD_010125.pdf",
                    "NH777.US_VAT_020125.pdf"}
    assert [Path(t["duong_dan"]).name for t in g["tep_chung"]] == [
        "NH777.US, NH501.US_(scan) Agreement_010125.pdf"]
    assert g["serial_trong_ten"] == ["90000001"]
    assert "không tự dời" in g["trang_thai"]


def test_token_chung_khong_phai_ten_nhan(so):
    assert "VAT" not in _dong(so, "NH777")["ten_nhan"]


def test_tep_chung_hai_ho_so_khong_phai_ma_lac(so):
    assert not [r for r in so["ma_lac"] if r["ma_lac"] == "BQ060"]
    [t] = so["tep_nhieu_ho_so"]
    assert t["ma"] == "BQ060" and t["thu_muc_ho_so_cua_ma"] == [B]


def test_ma_khong_phai_he_ho_so_bi_bo_qua(so):
    assert [b["ma"] for b in so["bo_qua"]] == ["NQ1234"]


def test_tom_tat_dem_du_bon_loai(so):
    t = so["tom_tat"]["theo_loai"]
    assert t == {"loi_go": 3, "danh_so_song_song": 2,
                 "de_nham_ho_so": 1, "chua_phan_loai": 0}
    assert sml.kiem_so(so) == []


def test_ban_giao_serial_cho_so_so_hieu(so):
    by = {r["serial"]: r for r in so["ban_giao_so_hieu_q4"]}
    assert set(by) == {"90000001", "90000002"}
    assert by["90000002"]["nhan"] == "Alpha"
    assert by["90000002"]["nhom"] == "009"
    assert by["90000002"]["ngay_trong_ten"] == "010125"
    assert by["90000001"]["nhan"] == "BETA"


# ── ràng buộc kho gốc ───────────────────────────────────────────────────

def test_duong_dan_nfd_quy_ve_nfc(tmp_path):
    nfd = unicodedata.normalize("NFD", f"{A}/1. Filing/NH502.US_Hợp đồng_010125.pdf")
    so = sml.lap_so(_dung_kho(tmp_path, [nfd]), tmp_path / "s", None)
    tep = [t for r in so["ma_lac"] for t in r["tep_lo_ra"]]
    nfc = unicodedata.normalize("NFC", nfd)
    [t] = [t for t in tep if "Hợp" in t["duong_dan"]]
    assert t["duong_dan"] == nfc
    assert t["doc_id"] == doc_id_for(nfc)


def test_khong_dong_toi_kho_goc(tmp_path):
    kho = _dung_kho(tmp_path)
    truoc = sml.chup_kho(kho)
    sml.lap_so(kho, tmp_path / "s", None)
    assert sml.chup_kho(kho) == truoc


def test_doi_chieu_de_xuat_cua_so_ban_sach(tmp_path):
    kho = _dung_kho(tmp_path)
    ban_sach = tmp_path / "ban_sach.json"
    ban_sach.write_text(json.dumps({"de_xuat_doi_ten": [
        {"duong_dan": f"{A}/0. Info/NH502.US_Info_010125.docx",
         "ma_hien_tai": "NH502", "ma_de_xuat": "NH501"},
        {"duong_dan": f"{A}/1. Filing/NH501.US_VAT_010125.pdf",
         "ma_hien_tai": "NH501. US", "ma_de_xuat": "NH501.US"},
    ]}), "utf-8")
    so = sml.lap_so(kho, tmp_path / "s", ban_sach)
    dc = {Path(r["duong_dan"]).name: r for r in so["doi_chieu_so_khac"]}
    assert dc["NH502.US_Info_010125.docx"]["khop"] is True
    assert dc["NH501.US_VAT_010125.pdf"]["khop"] is None
