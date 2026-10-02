"""Khoá sổ danh tính trên một kho GIẢ dựng đúng bốn kiểu gãy đo được.

Mọi mã, thư mục và tên kênh ở đây là bịa; chỉ HÌNH DẠNG giống kho thật:
chứng từ dùng chung một thư mục thanh toán cho ba hồ sơ, mã thừa số 0 đệm,
một hồ sơ nhiều mã giai đoạn kèm bản sao y hệt, và một tệp mang ba danh tính
(tên tệp, thư mục, tiêu đề kênh) không khớp nhau.
"""

import importlib.util
import re
from pathlib import Path

import pytest

from ocr_lab.ade_store import doc_id_for
from ocr_lab.danh_tinh import (CHO_NGUOI_XAC_NHAN, bo_dau, chuan_ma, doc_thu_muc_ho_so,
                               dung_so, gop_hang_cho, kenh_id, kiem_tra, la_nhap,
                               ma_tren_duong_dan, ma_tren_ten_tep, sua_so_0_thua)

DK = "Kho/1. Dang ky nhan hieu"
TC = "Kho/5. C&D"

# Kiểu 1: hồ sơ 4003 giữ thư mục thanh toán chung cho 4001 và 4002, hai hồ
# sơ không có thư mục riêng; một hoá đơn gõ thừa số 0 (NH40001).
TT = f"{DK}/4003. US. GAMMA/Thanh toan (NH4003, NH4001, NH4002)"
WIRE = f"{TT}/NH4003.US, NH4001.US, NH4002.US_Wire transfer_010125.pdf"
HD_THUA_0 = f"{TT}/NH40001.US_Invoice_010125.pdf"
HD_4002 = f"{TT}/NH4002.US_Invoice_010125.pdf"

# Kiểu 2: một vụ tranh chấp, mã tư vấn viết hai kiểu số 0 đệm.
VU = f"{TC}/77. A v. B"
THU_CANH_BAO = f"{VU}/0. Info/2025_01_02 Letter re Unauthorized Uses.pdf"
PHAN_HOI = f"{VU}/1. To client/TV012-77_Response letter_010225.docx"
DAM_PHAN = f"{VU}/3. Negotiation/TV0012-77_Round 1_020225.docx"

# Kiểu 3: một hồ sơ, ba mã theo giai đoạn, bản scan hợp đồng nằm ba chỗ.
HS = f"{DK}/600. US. DELTA"
TU_VAN = f"{HS}/TV3001_Tu van_010325.docx"
NHAP = f"{HS}/TV3002_(du thao) Hop dong dich vu phap ly_020325_ver0.1.docx"
SCAN = f"{HS}/NH600.US_(scan) Hop dong dich vu phap ly_030325.pdf"
SCAN_NEW = f"{HS}/New folder/NH600.US_(scan) Hop dong dich vu phap ly_030325.pdf"
SCAN_1 = f"{HS}/NH600.US_(scan) Hop dong dich vu phap ly_030325 (1).pdf"
BIEN_NHAN = f"{HS}/NH600.US_Filing receipt_040325.pdf"

# Kiểu 4: tên tệp nói 707, thư mục nói 700, kênh chat nói ZETA.
LECH = f"{DK}/700. US. EPSILON/NH707.US_Info_050425.docx"

# Một ảnh chụp đoạn chat y hệt nằm ở hai hồ sơ; tiêu đề kênh OCR lệch dấu.
CHAT_A = f"{DK}/800. US. ETA/Chat/CF closed.pdf"
CHAT_B = f"{DK}/801. US. THETA/CF closed.pdf"
# Hợp đồng nháp xếp ở 800 nhưng văn bản in số hợp đồng của 801.
HD_LECH_NOI_DUNG = f"{DK}/800. US. ETA/NH800.US_(du thao) Hop dong_010625_v0.1.docx"
NGOAI = "Kho/README.txt"

TEP = [(WIRE, "w"), (HD_THUA_0, "i1"), (HD_4002, "i2"),
       (THU_CANH_BAO, "c1"), (PHAN_HOI, "c2"), (DAM_PHAN, "c3"),
       (TU_VAN, "t1"), (NHAP, "t2"), (SCAN, "s"), (SCAN_NEW, "s"), (SCAN_1, "s"),
       (BIEN_NHAN, "b"), (LECH, "l"), (CHAT_A, "cf"), (CHAT_B, "cf"),
       (HD_LECH_NOI_DUNG, "hl"), (NGOAI, "x")]

KENH = {doc_id_for(LECH): {"tieu_de": "ZETA x REFINY", "thanh_vien": 3},
        doc_id_for(CHAT_A): {"tieu_de": "N.Văn IP US x Refiny", "thanh_vien": 4},
        doc_id_for(CHAT_B): {"tieu_de": "N.Vẫn IP US x Refiny", "thanh_vien": 4}}


def _tep_hd(*rels):
    return [{"ade_id": doc_id_for(r), "duong_dan": r} for r in rels]


HOP_DONG = [
    {"khoa": "NH600/2025/HD-SHTT", "loai": "hop_dong", "ma_ho_so": "NH600",
     "co_so_trong_van_ban": True, "da_ky": True, "doi_tac": {"vai_tro": "khach_hang"},
     "tep": _tep_hd(SCAN_NEW, SCAN, SCAN_1)},
    {"khoa": "TV3002/2025/HD-SHTT", "loai": "hop_dong", "ma_ho_so": "TV3002",
     "co_so_trong_van_ban": True, "da_ky": False, "doi_tac": {"vai_tro": "khach_hang"},
     "tep": _tep_hd(NHAP)},
    {"khoa": "NH801/2025/HD-SHTT", "loai": "hop_dong", "ma_ho_so": "NH801",
     "co_so_trong_van_ban": True, "da_ky": False, "doi_tac": {"vai_tro": "khach_hang"},
     "tep": _tep_hd(HD_LECH_NOI_DUNG)},
]


@pytest.fixture(scope="module")
def so():
    return dung_so(TEP, doc_id_for=doc_id_for, kenh_theo_doc=KENH, hop_dong=HOP_DONG)


def _ho_so(so, nhan):
    return next(h for h in so["ho_so"] if h["ho_so"] == nhan)


def _tai_lieu(so, rel):
    return next(t for t in so["tai_lieu"] if any(b["duong_dan"] == rel for b in t["tep"]))


def _tep(so, rel):
    return next(b for t in so["tai_lieu"] for b in t["tep"] if b["duong_dan"] == rel)


def _ca(so, rel, loai):
    return next(c for c in so["hang_cho_xung_dot"]
                if c["xung_dot"] == loai and (c["duong_dan"] == rel or rel in c["ban_khac"]))


# ── Hàm lẻ ───────────────────────────────────────────────────────────────

def test_bo_dau_thay_d_truoc_khi_tach_dau():
    assert bo_dau("Hợp đồng Đăng ký") == "hop dong dang ky"


def test_chuan_ma_giu_nghia_cua_so_ban_sach():
    assert chuan_ma("TV0012-77") == chuan_ma("TV012-77") == "TV12-77"
    assert chuan_ma("NH600. US") == "NH600.US"
    assert chuan_ma("NH955") != chuan_ma("NH959")


def test_ma_dau_ten_tep_moi_la_ma_tu_nhan():
    assert [c.khoa for c in ma_tren_ten_tep("NH4001.US, BQ402.US_Invoice 12345.pdf")] == [
        "NH4001", "BQ402"]
    assert ma_tren_ten_tep("Invoice NH4001.pdf") == []
    assert [c.khoa for c in ma_tren_duong_dan(["Thanh toan (NH4001, NH4002)"])] == [
        "NH4001", "NH4002"]


def test_thu_muc_ho_so_cho_so_va_nhan():
    assert doc_thu_muc_ho_so("500. US. FOO") == (500, "500.US")
    assert doc_thu_muc_ho_so("77. A v. B") == (77, "77")
    assert doc_thu_muc_ho_so("Accounting") is None


def test_chi_sua_so_0_khi_co_moc_neo_duy_nhat():
    assert sua_so_0_thua(40001, {4001, 4002}) == 4001
    assert sua_so_0_thua(707, {700}) is None           # chữ số khác, không phải số 0 thừa
    assert sua_so_0_thua(40001, set()) is None         # không có mỏ neo thì không sửa
    assert sua_so_0_thua(20304, {2304, 2034}) is None  # hai cách sửa ⟶ không đoán


def test_ban_nhap_theo_du_thao_hoac_so_ban_0x():
    assert la_nhap(NHAP) and la_nhap("a/b_v0.2C.docx") and la_nhap("draft/x.pdf")
    assert not la_nhap(SCAN) and not la_nhap("a/b_v1.0.docx")


def test_kenh_id_bo_ten_hang_tu_noi_va_dau():
    assert kenh_id("ZETA x REFINY") == kenh_id("Refiny × Zeta") == kenh_id("ZETA × RFEINY")
    assert kenh_id("N.Văn IP US x Refiny") == kenh_id("N.Vẫn IP US x Refiny")
    assert kenh_id("ZETA x REFINY") != kenh_id("N.Văn IP US x Refiny")


def test_kenh_id_khong_mang_chu_nao_cua_tieu_de():
    for td in ["ZETA x REFINY", "N.Văn IP US x Refiny", "Mr Quang - Dispute x Refiny"]:
        kid = kenh_id(td)
        assert kid == kenh_id(td) and kid.startswith("k-")
        tu = {t for t in re.split(r"[^a-z0-9]+", bo_dau(td)) if len(t) > 1}
        assert not any(t in kid for t in tu), (td, kid)


# ── Bốn kiểu gãy ─────────────────────────────────────────────────────────

def test_chung_tu_dung_chung_thuoc_moi_ho_so_no_neu(so):
    tl = _tai_lieu(so, WIRE)
    assert tl["thuoc_ho_so"] == ["4001.US", "4002.US", "4003.US"]
    assert tl["vai"] == "chung_tu_dung_chung"
    assert tl["nguon_ho_so"]["4001.US"] == ["duong_dan", "ten_tep"]
    assert tl["nguon_ho_so"]["4003.US"] == ["duong_dan", "ten_tep", "thu_muc"]
    for nhan in ("4001.US", "4002.US"):
        h = _ho_so(so, nhan)
        assert not h["co_thu_muc"] and h["nam_trong"] == ["4003.US"]
        assert h["so_tep"] == 0 and h["so_tep_thuoc"] >= 1   # không nằm đâu, vẫn có tệp
        assert tl["id"] in h["tai_lieu"]


def test_ma_thua_so_0_sua_theo_moc_duong_dan_va_giu_ma_goc(so):
    b = _tep(so, HD_THUA_0)
    assert b["thuoc_ho_so"] == ["4001.US"] and b["xung_dot"] == []
    assert b["sua_ma"] == [{"ma_goc": "NH40001.US", "ma": "NH4001",
                            "ly_do": "thua_so_0; neo: ma khai tren duong dan"}]
    assert _ho_so(so, "4001.US")["ma_goc_da_sua"] == ["NH40001.US"]


def test_so_0_dem_la_mot_khoa_hai_bi_danh(so):
    h = _ho_so(so, "77")
    assert h["khoa"] == "TV12-77" and h["ma_chuan"] == ["TV12-77"]
    assert h["bi_danh"] == ["TV0012-77", "TV012-77"]
    assert _tep(so, DAM_PHAN)["bi_danh"] == ["TV0012-77"]


def test_tranh_chap_khai_khong_tom_tat_duoc_va_chi_tep_phai_mo(so):
    h = _ho_so(so, "77")
    assert h["loai_ho_so"] == "tranh_chap"
    assert h["tu_khai"] == "khong_tom_tat_duoc_lap_luan_phai_mo_toan_van"
    mo = {k: [t["duong_dan"] for t in v] for k, v in h["phai_mo_toan_van"].items()}
    assert mo == {"thu_phan_hoi": [PHAN_HOI], "dam_phan": [DAM_PHAN],
                  "thu_canh_bao": [THU_CANH_BAO]}


def test_nhieu_ma_giai_doan_mot_ho_so_va_ban_trung_gop_theo_bam(so):
    h = _ho_so(so, "600.US")
    assert h["khoa"] == "NH600" and h["ma_chuan"] == ["NH600", "TV3001", "TV3002"]
    assert (h["so_tep"], h["so_tai_lieu"], h["so_ban_trung"]) == (6, 4, 2)
    tl = _tai_lieu(so, SCAN)
    assert tl["so_ban"] == 3 and tl["ban_chinh"] == SCAN and tl["id"] == doc_id_for(SCAN)
    for rel in (SCAN_NEW, SCAN_1):
        b = _tep(so, rel)
        assert b["la_ban_sao_cua"] == tl["id"] and b["cach_gop"] == "bam_noi_dung"


def test_cong_hop_dong_dem_mot_ban_ky_va_ban_nhap_ma_giai_doan(so):
    cong = _ho_so(so, "600.US")["cong_hop_dong"]
    assert cong["so_hop_dong_khach_da_ky"] == 1
    assert cong["hop_dong_khach_da_ky"] == ["NH600/2025/HD-SHTT"]
    assert cong["nhap"] == ["TV3002/2025/HD-SHTT"]
    hd = next(x for x in so["hop_dong"] if x["khoa"] == "NH600/2025/HD-SHTT")
    assert hd["ho_so"] == "600.US" and hd["ban_chinh"]["duong_dan"] == SCAN


def test_ba_danh_tinh_lech_ghi_ca_ba_va_cho_nguoi(so):
    b = _tep(so, LECH)
    assert b["thuoc_ho_so"] == ["700.US"] and b["nguon_ho_so"] == {"700.US": ["thu_muc"]}
    assert b["bi_danh"] == ["NH707.US"] and b["kenh"] == kenh_id("ZETA x REFINY")
    assert b["xung_dot"] == ["ma_ten_tep_khac_thu_muc"]
    assert b["trang_thai"] == CHO_NGUOI_XAC_NHAN
    ca = _ca(so, LECH, "ma_ten_tep_khac_thu_muc")
    assert ca["trang_thai"] == CHO_NGUOI_XAC_NHAN
    assert ca["danh_tinh"] == {"ten_tep": ["NH707.US"], "thu_muc": "700.US",
                               "duong_dan": [], "noi_dung": None,
                               "kenh": kenh_id("ZETA x REFINY")}
    assert [(u["ho_so"], u["co_thu_muc_trong_kho"]) for u in ca["ung_vien"]] == [
        ("700.US", True), ("707.US", False)]
    # Mã lệch không đẻ ra một hồ sơ ma.
    assert "707.US" not in {h["ho_so"] for h in so["ho_so"]}


# ── n–n, kênh, nội dung ──────────────────────────────────────────────────

def test_ban_y_het_o_hai_ho_so_la_mot_tai_lieu_thuoc_ca_hai(so):
    tl = _tai_lieu(so, CHAT_A)
    assert tl["so_ban"] == 2 and tl["thuoc_ho_so"] == ["800.US", "801.US"]
    kid = kenh_id("N.Văn IP US x Refiny")
    assert tl["kenh"] == [kid]
    k = next(k for k in so["kenh"] if k["kenh_id"] == kid)
    assert {k["tieu_de"], *k["tieu_de_bien_the"]} == {"N.Văn IP US x Refiny",
                                                     "N.Vẫn IP US x Refiny"}
    assert k["thanh_vien"] == 4 and k["thuoc_ho_so"] == ["800.US", "801.US"]
    assert k["tin"] == {"truoc_gop": 2, "sau_gop": 1} and len(k["tieu_de_bien_the"]) == 1


def test_so_trong_van_ban_lech_cho_xep_la_mot_danh_tinh_nua(so):
    b = _tep(so, HD_LECH_NOI_DUNG)
    assert "ma_noi_dung_khac_ten_tep" in b["xung_dot"]
    assert b["ho_so_trong_van_ban"] == {"ho_so": "801.US", "so_hop_dong": "NH801/2025/HD-SHTT"}
    ca = _ca(so, HD_LECH_NOI_DUNG, "ma_noi_dung_khac_ten_tep")
    assert ca["danh_tinh"]["noi_dung"] == "801.US" and ca["nhap"]
    assert {"ho_so": "801.US", "nguon": ["noi_dung"], "co_thu_muc_trong_kho": True} in ca["ung_vien"]
    assert ca["xep_tam"] == ["800.US"]


def test_hang_cho_moi_ca_mot_dong_va_liet_ke_du(so):
    assert so["tom_tat"]["hang_cho"]["theo_loai"] == {
        "ma_ten_tep_khac_thu_muc": 1, "ma_noi_dung_khac_ten_tep": 1}
    assert len({c["ca"] for c in so["hang_cho_xung_dot"]}) == len(so["hang_cho_xung_dot"]) == 2


def test_ma_giai_doan_trong_hai_ho_so_la_xung_dot():
    tep = [(f"{DK}/600. US. A/TV3001_x.docx", "a"), (f"{DK}/601. US. B/TV3001_y.docx", "b")]
    so = dung_so(tep, doc_id_for=doc_id_for)
    assert {c["xung_dot"] for c in so["hang_cho_xung_dot"]} == {"ma_giai_doan_o_nhieu_ho_so"}
    assert all(h["ma_chuan"] == [] for h in so["ho_so"])
    assert kiem_tra(so, tep) == []


def test_hop_dong_ma_lech_khong_tu_chon_ho_so():
    hd = [{"khoa": "NH707/2025/HD-SHTT", "loai": "hop_dong", "ma_ho_so": "NH707",
           "da_ky": True, "doi_tac": {"vai_tro": "khach_hang"}, "tep": _tep_hd(LECH)}]
    so = dung_so([(LECH, "l")], doc_id_for=doc_id_for, hop_dong=hd)
    assert so["hop_dong"][0]["ho_so"] is None
    assert "cong_hop_dong" not in _ho_so(so, "700.US")


def test_ghi_thay_nguyen_tu_va_giu_quyen_600(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "so_danh_tinh", Path(__file__).parents[1] / "scripts" / "so_danh_tinh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dich = tmp_path / "hang_cho.jsonl"
    dich.write_text("cu\n", "utf-8")
    mod.ghi(dich, "moi\n")
    assert dich.read_text("utf-8") == "moi\n"
    assert dich.stat().st_mode & 0o777 == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["hang_cho.jsonl"]


def test_tep_ngoai_ho_so_khong_bi_ep_vao_ho_so(so):
    assert [b["duong_dan"] for b in so["ngoai_ho_so"]] == [NGOAI]


def test_bat_bien_dat(so):
    assert kiem_tra(so, TEP) == []


# ── Hàng chờ qua các lần dựng lại ────────────────────────────────────────

def test_gop_hang_cho_giu_quyet_dinh_cua_nguoi(so):
    moi = [dict(c) for c in so["hang_cho_xung_dot"]]
    cu = [{**moi[0], "trang_thai": "da_xac_nhan", "quyet_dinh": "700.US",
           "nguoi_xac_nhan": "nguoi-duyet"},
          {"ca": "ma_ten_tep_khac_thu_muc/da-doi-ten", "trang_thai": "da_xac_nhan",
           "quyet_dinh": "1.US"},
          {**moi[1]}]                              # ca chưa quyết: lấy bản mới
    ra = gop_hang_cho(cu, [dict(c) for c in moi])
    assert ra[0]["trang_thai"] == "da_xac_nhan" and ra[0]["quyet_dinh"] == "700.US"
    assert ra[0]["danh_tinh"] == moi[0]["danh_tinh"]
    assert ra[1]["trang_thai"] == CHO_NGUOI_XAC_NHAN
    assert ra[2]["ca"] == "ma_ten_tep_khac_thu_muc/da-doi-ten" and ra[2]["con_trong_kho"] is False


def test_duong_dan_khai_ho_so_khac_thu_muc_la_xung_dot():
    rel = f"{DK}/900. US. A/Thanh toan (NH901)/Invoice.pdf"
    tep = [(rel, "a"), (f"{DK}/901. US. B/x.pdf", "b")]
    so = dung_so(tep, doc_id_for=doc_id_for)
    assert [c["xung_dot"] for c in so["hang_cho_xung_dot"]] == ["ma_duong_dan_khac_thu_muc"]
    assert _tep(so, rel)["thuoc_ho_so"] == ["900.US", "901.US"]
    assert kiem_tra(so, tep) == []


def test_sua_so_0_ma_tu_van_doi_so_vu_viec_khong_doi_so_tu_van():
    rel = f"{VU}/Vong 2 (TV12-77)/TV12-707_Round 2.docx"
    so = dung_so([(rel, "a")], doc_id_for=doc_id_for)
    b = _tep(so, rel)
    assert b["sua_ma"][0]["ma"] == "TV12-77" and b["thuoc_ho_so"] == ["77"]
    assert _ho_so(so, "77")["ma_goc_da_sua"] == ["TV12-707"]
