"""Sổ số hiệu: số nào của ai, bảng nào, và tên tệp nào đang mang số cấm.

Mọi nhãn, số và đường dẫn ở đây là bịa. Không đưa số thật của hồ sơ vào kho git.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import stat
import unicodedata

import pytest

from ocr_lab import danh_tinh as dt
from ocr_lab.ade_store import doc_id_for


def _nap():
    """`scripts/` không phải package nên không import theo tên được."""
    p = pathlib.Path(__file__).parent.parent / "scripts" / "so_so_hieu.py"
    spec = importlib.util.spec_from_file_location("so_so_hieu_thu", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ssh = _nap()

HO_SO = "Phòng IP/1. Đăng ký/901.US. ZORBLAX, hinh IN CLASS 009"
CQT = "00ABCDEF0123456789ABCDEF0123456789"
SO_VAT = "00000042"

TSDR_DOI_CHUNG = "\n".join([
    "Trademark Status & Document Retrieval",
    "Mark: ZORBLUX",
    "US Serial Number: 91234567 · Application Filing Date: Jan. 1, 2021",
    "US Registration Number: 6123456 · Registration Date: Jan. 1, 2022",
    "Owner Name: Fake Other LLC",
    "https://tsdr.uspto.gov/#caseNumber=91234567&caseType=SERIAL_NO",
    "Trademark Status & Document Retrieval",
    "Mark: QUORBLAX",
    "US Serial Number: 79111222 · Application Filing Date: Feb. 2, 2022",
    "International Registration Number: 1555666",
    "Owner Name: Another Fake S.r.l.",
    "https://tsdr.uspto.gov/#caseNumber=79111222&caseType=SERIAL_NO",
])

TAI_LIEU = [
    # đơn của ta chỉ có trường Mark trong nhánh khiếu nại
    (f"{HO_SO}/2. Appeal/Appeal Letter_010225.pdf",
     "Re: Request for reconsideration\nMark: ZORBLAX\nSerial Number: 98765432\nWe respectfully request reconsideration."),
    # nhánh nộp đơn nhắc lại số, không có trường Mark nào gần
    (f"{HO_SO}/1. Filing/Filing receipt.pdf",
     "Filing receipt\n" + "text\n" * 40 + "Serial Number: 98765432"),
    (f"{HO_SO}/0. Info/Tong hop doi chung_010125.pdf", TSDR_DOI_CHUNG),
    (f"{HO_SO}/3. Accounting/NH901.US_Hoa don VAT.pdf",
     f"HÓA ĐƠN GIÁ TRỊ GIA TĂNG\nMã của CQT: {CQT}\nKý hiệu: 1C25TAA\nSố: {SO_VAT}"),
    (f"{HO_SO}/3. Accounting/NH901.US_Hoa don VAT nhap.pdf",
     "HÓA ĐƠN GIÁ TRỊ GIA TĂNG\nKý hiệu: 1C25TAA\nSố: <Chưa cấp số>"),
    (f"{HO_SO}/3. Accounting/NH901.US_ Invoice 4321_010325.pdf",
     "FAKE ASSOCIATES LLP\nInvoice No. 4321\nBill to: REFINY"),
    (f"{HO_SO}/4. Hop dong/Hop dong dich vu.pdf",
     "Căn cứ Nghị quyết số 80/2023/QH15 của Quốc hội;\n"
     "HỢP ĐỒNG DỊCH VỤ\nSố: 77/2025/HĐ-SHTT"),
    (f"{HO_SO}/2. Appeal/Signature.pdf",
     "Bar membership or registration number: 123456\nRegistration Number: 7000001"),
]


def _tai_lieu():
    return [{"doc_id": f"d{i:015d}", "nguon": unicodedata.normalize("NFC", n), "engine": "pro", "markdown": md}
            for i, (n, md) in enumerate(TAI_LIEU)]


def _so_danh_tinh(tai_lieu):
    """Sổ danh tính dựng bằng chính `ocr_lab.danh_tinh`, như so_danh_tinh.py."""
    return dt.dung_so([(n, f"bam{i}") for i, (n, _) in enumerate(tai_lieu)], doc_id_for=doc_id_for)


def _danh_tinh(tai_lieu=TAI_LIEU, quyet=None):
    so_dt = _so_danh_tinh(tai_lieu)
    hang_cho = [{**c, **(quyet or {})} for c in so_dt.pop("hang_cho_xung_dot")]
    return ssh.theo_danh_tinh(so_dt, hang_cho)


def _tai_lieu_tu(ds):
    return [{"doc_id": f"d{i:015d}", "nguon": unicodedata.normalize("NFC", n), "engine": "pro", "markdown": md}
            for i, (n, md) in enumerate(ds)]


@pytest.fixture(scope="module")
def so():
    return ssh.dung_so(_tai_lieu(), _danh_tinh())


def _dong(so, loai, chuan, ho_so="901.US"):
    hit = [g for g in so if g["loai"] == loai and g["chuan"] == chuan and g["ho_so"] == ho_so]
    assert len(hit) == 1, f"{loai} {chuan}: {len(hit)} dòng"
    return hit[0]


def test_nhan_cua_ho_so_bo_chu_kieu_nhan():
    assert ssh.nhan_cua_ho_so("901.US. ZORBLAX, hinh IN CLASS 009") == "ZORBLAX"
    assert ssh.nhan_cua_ho_so("902. US. FOO, handmade device IN CLASS 021") == "FOO HANDMADE"
    assert ssh.nhan_cua_ho_so("93.US. Tac pham") is None


def test_so_don_cua_ta_tu_nhanh_khieu_nai_lan_ra_ca_ho_so(so):
    """Phiếu `ta` trong Appeal đủ để số trong Filing cũng là của ta."""
    g = _dong(so, "so_don_uspto", "98765432")
    assert g["bang"] == ssh.CONG_KHAI
    assert g["chu_so_huu"] == "ta"
    assert g["so_tep"] == 2
    assert all(l["trich"] and l["dong"] >= 1 for l in g["lan_xuat_hien"])


def test_so_trong_ban_in_tsdr_la_doi_chung(so):
    assert _dong(so, "so_don_uspto", "91234567")["chu_so_huu"] == "doi_chung"
    assert _dong(so, "so_van_bang_uspto", "6123456")["chu_so_huu"] == "doi_chung"


def test_so_dang_ky_quoc_te_khong_bi_nhan_la_so_van_bang(so):
    assert not [g for g in so if g["loai"] == "so_van_bang_uspto" and g["chuan"] == "1555666"]
    assert _dong(so, "so_dang_ky_quoc_te", "1555666")["bang"] == ssh.CHUA_XEP


def test_so_the_luat_su_khong_bi_nhan_la_so_van_bang(so):
    assert _dong(so, "so_the_luat_su", "123456")["bang"] == ssh.CHUA_XEP
    assert not [g for g in so if g["loai"] == "so_van_bang_uspto" and g["chuan"] == "123456"]
    assert _dong(so, "so_van_bang_uspto", "7000001")["bang"] == ssh.CONG_KHAI


def test_hoa_don_vat_ma_cqt_so_va_ban_nhap(so):
    assert _dong(so, "ma_cqt", CQT)["bang"] == ssh.NHAY_CAM
    g = _dong(so, "so_hoa_don", SO_VAT)
    assert (g["bang"], g["chu_so_huu"]) == (ssh.NHAY_CAM, "ta")
    assert _dong(so, "so_hoa_don", ssh.CHUA_CAP_SO).get("chua_cap_so")
    assert _dong(so, "ky_hieu_hoa_don", "1C25TAA")["bang"] == ssh.NHAY_CAM


def test_hoa_don_dai_dien_la_doi_tac(so):
    g = _dong(so, "so_hoa_don", "4321")
    assert (g["bang"], g["chu_so_huu"]) == (ssh.NHAY_CAM, "doi_tac")


def test_trich_dan_van_ban_phap_luat_khong_phai_so_hop_dong(so):
    hd = [g["chuan"] for g in so if g["loai"] == "so_hop_dong"]
    assert not [h for h in hd if "QH" in h], hd
    assert len(hd) == 1 and hd[0].startswith("77/2025/")


def test_bang_doi_chung_theo_ban_ghi(so):
    tl = next(t for t in _tai_lieu() if "doi chung" in t["nguon"])
    bang = ssh.bang_doi_chung(tl, so, _danh_tinh())
    assert [r["nhan_hieu"] for r in bang] == ["ZORBLUX", "QUORBLAX"]
    assert [r["chu_nhan"] for r in bang] == ["Fake Other LLC", "Another Fake S.r.l."]
    assert not any(r["cua_ta"] for r in bang), "tra cứu trước khi nộp: chưa có số của ta"
    assert {(s["loai"], s["gia_tri"]) for s in bang[1]["so"]} == {
        ("so_don_uspto", "79111222"), ("so_dang_ky_quoc_te", "1555666")}


HO_SO_2 = "Phòng IP/1. Đăng ký/902.US. QUUXA IN CLASS 025"
STK = "001099000001"


def test_chung_tu_dung_chung_ghi_so_duoi_moi_ho_so():
    ds = [(f"{HO_SO}/3. Accounting/Thanh toan (NH901, NH902)/Wire.pdf", f"Số tài khoản: {STK}"),
          (f"{HO_SO_2}/1. Filing/Receipt.pdf", "Filing receipt")]
    so = ssh.dung_so(_tai_lieu_tu(ds), _danh_tinh(ds))
    assert sorted(g["ho_so"] for g in so if g["chuan"] == STK) == ["901.US", "902.US"]
    assert {g["nhan_ho_so"] for g in so if g["chuan"] == STK} == {"ZORBLAX", "QUUXA"}


XUNG_DOT = [(f"{HO_SO}/1. Filing/NH903.US_Receipt.pdf", "Mark: ZORBLAX\nSerial Number: 98700001"),
            (f"{HO_SO}/1. Filing/Receipt.pdf", "Filing receipt")]


def test_tep_xung_dot_khong_duoc_chon_ho_so():
    so = ssh.dung_so(_tai_lieu_tu(XUNG_DOT), _danh_tinh(XUNG_DOT))
    g = _dong(so, "so_don_uspto", "98700001", ho_so=None)
    assert g["chu_so_huu"] == "chua_ro"
    assert g["xung_dot"]["loai"] == ["ma_ten_tep_khac_thu_muc"]
    assert g["xung_dot"]["xep_tam"] == ["901.US"] and len(g["xung_dot"]["ca"]) == 1
    assert ssh.tom_tat(so, [], ssh.chung_minh_ten_tep([], so))["so_dong_cho_xac_nhan_ho_so"] == 1


def test_quyet_dinh_trong_hang_cho_duoc_giu():
    quyet = {"trang_thai": "da_xac_nhan", "quyet_dinh": "901.US"}
    so = ssh.dung_so(_tai_lieu_tu(XUNG_DOT), _danh_tinh(XUNG_DOT, quyet))
    g = _dong(so, "so_don_uspto", "98700001")
    assert "xung_dot" not in g and g["chu_so_huu"] == "ta"


def test_ca_da_doi_trang_thai_ma_khong_ghi_quyet_dinh_van_la_xung_dot():
    so = ssh.dung_so(_tai_lieu_tu(XUNG_DOT), _danh_tinh(XUNG_DOT, {"trang_thai": "da_xem"}))
    assert _dong(so, "so_don_uspto", "98700001", ho_so=None)["xung_dot"]


@pytest.mark.parametrize("ten, bat", [
    ("NH901.US_Hoa don 42.pdf", True),
    ("HD so 42.pdf", True),
    ("Hóa đơn VAT số 0042.pdf", True),
    ("Bien ban 42.pdf", False),
    ("Hoa don 420.pdf", False),
    ("Hoa don 142.pdf", False),
    ("Hoa don 4.pdf", False),
    ("HD_42.pdf", True),
    ("NH901.US_Hoa_don_42.pdf", True),
    ("HOA_DON_SO_0042.pdf", True),
    ("HD_420.pdf", False),
])
def test_so_hoa_don_dem_0_dang_ngan_chi_bat_sau_tu_khoa(so, ten, bat):
    ket = ssh.chung_minh_ten_tep([f"{HO_SO}/3. Accounting/{ten}"], so)
    thay = [(s["loai"], s["chuan"]) for v in ket["vi_pham"] for s in v["so"]]
    assert (("so_hoa_don", SO_VAT) in thay) is bat, thay


def test_tom_tat_tach_dinh_danh_nhan_khoi_so_khac(so):
    t = ssh.tom_tat(so, _tai_lieu(), ssh.chung_minh_ten_tep([], so))["theo_nhom_loai"]
    # 98765432, 91234567, 6123456, 7000001, 79111222 và số quốc tế 1555666
    assert t["dinh_danh_nhan"] == {"so_dong": 6, "so_tai_lieu": 4}
    assert "so_dien_thoai" not in t and t["khac"]["so_dong"] > 0


def test_ten_tep_mang_so_hoa_don_dai_dien_bi_liet_ke(so):
    tep = [unicodedata.normalize("NFC", n) for n, _ in TAI_LIEU]
    ket = ssh.chung_minh_ten_tep(tep, so)
    vi_pham = {pathlib.Path(v["tep"]).name: v["so"] for v in ket["vi_pham"]}
    assert set(vi_pham) == {"NH901.US_ Invoice 4321_010325.pdf"}
    assert vi_pham["NH901.US_ Invoice 4321_010325.pdf"][0]["loai"] == "so_hoa_don"
    # số hoá đơn VAT và mã CQT có trong nội dung nhưng không lên tên nào
    assert not any(s["chuan"] in (CQT, SO_VAT) for v in ket["vi_pham"] for s in v["so"])
    assert ket["khong_giai_thich"] == []


def test_ten_da_chap_nhan_van_liet_ke_nhung_khong_con_mo(so):
    """Quyết định giữ tên chỉ phủ đúng (tệp, loại, số) đã ghi."""
    ten = unicodedata.normalize("NFC", f"{HO_SO}/3. Accounting/NH901.US_ Invoice 4321_010325.pdf")
    moi = f"{HO_SO}/3. Accounting/Invoice 4321 ban sao.pdf"
    ket = ssh.chung_minh_ten_tep([ten, moi], so, frozenset({(ten, "so_hoa_don", "4321")}))
    trang_thai = {v["tep"]: v["trang_thai"] for v in ket["vi_pham"]}
    assert trang_thai == {ten: "da_chap_nhan", moi: "mo"}
    t = ssh.tom_tat(so, _tai_lieu(), ket)["ten_tep"]
    assert (t["tep_mang_so_nhay_cam"], t["tep_mang_so_nhay_cam_chua_chap_nhan"]) == (2, 1)


def test_so_cam_bi_ngan_boi_dau_cham_van_bi_bat(so):
    tep = [f"{HO_SO}/3. Accounting/Hoa don 0000.0042.pdf"]
    assert ssh.chung_minh_ten_tep(tep, so)["vi_pham"], "số hoá đơn bị tách bằng dấu chấm vẫn là số hoá đơn"


def test_so_hop_dong_tren_ten_bi_bat_du_dau_ngan_khac(so):
    """Sổ giữ `/` và `-` của số hợp đồng; tên tệp không mang được `/`."""
    hd = next(g["chuan"] for g in so if g["loai"] == "so_hop_dong")
    tep = [f"{HO_SO}/4. Hop dong/HĐ 77_2025_HĐ-SHTT ban ky.pdf"]
    ket = ssh.chung_minh_ten_tep(tep, so)
    assert [(s["loai"], s["chuan"]) for v in ket["vi_pham"] for s in v["so"]] == [("so_hop_dong", hd)]
    assert ket["khong_giai_thich"] == []


@pytest.mark.parametrize("ten, mong", [
    ("NH901.US_Tong hop_010825.pdf", [("ngay", "010825")]),
    ("Wiring Instructions_12312025.pdf", [("ngay", "12312025")]),
    ("TV951-123_Tu van_010825.docx", [("ma_ho_so", "951123"), ("ngay", "010825")]),
    ("NH901.US_ De nghi thanh toan V2025-999_010825.pdf",
     [("dang_so_de_nghi_thanh_toan", "2025999"), ("ngay", "010825")]),
    ("Cover to client_7654321.docx", [(None, "7654321")]),
    ("Lien he 0900 111 222.pdf", [(None, "0900111222")]),
    ("Round 2 010825.docx", [("ngay", "010825")]),
])
def test_xep_day_so_tren_ten(ten, mong):
    ten = ssh._bo_dau_giu_vi_tri(ten)
    assert sorted(ssh._xep_day_so(ten, [], set()), key=lambda x: x[1]) == sorted(mong, key=lambda x: x[1])


def test_main_ghi_so_0600_va_khong_in_so_nhay_cam(tmp_path, capsys):
    kho, nguon, ra = tmp_path / "ade_out", tmp_path / "goc", tmp_path / "so" / "so_hieu.json"
    for i, (n, md) in enumerate(TAI_LIEU):
        d = kho / f"d{i:015d}"
        d.mkdir(parents=True)
        (d / "meta_pro.json").write_text(json.dumps({"source": n}), "utf-8")
        (d / "parse_pro.json").write_text(json.dumps({"markdown": md}), "utf-8")
        # kho gốc trên macOS trả tên NFD
        p = nguon / unicodedata.normalize("NFD", n)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    so_dt = _so_danh_tinh(TAI_LIEU)
    (tmp_path / "dt").mkdir()
    (tmp_path / "dt" / "hang_cho_xung_dot.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in so_dt.pop("hang_cho_xung_dot")), "utf-8")
    (tmp_path / "dt" / "danh_tinh.json").write_text(json.dumps(so_dt, ensure_ascii=False), "utf-8")
    chap_nhan = tmp_path / "chap_nhan.json"
    chap_nhan.write_text(json.dumps({
        "quyet_dinh": {"ai": "chủ hồ sơ", "ngay": "2001-01-01"},
        # ghi bằng NFD như bản sao chép từ Finder; vẫn phải khớp
        "tep": [{"tep": unicodedata.normalize("NFD", TAI_LIEU[5][0]), "loai": "so_hoa_don", "chuan": "4321"}],
    }), "utf-8")
    assert ssh.main(["--ade-out", str(kho), "--nguon", str(nguon), "--ra", str(ra),
                     "--danh-tinh", str(tmp_path / "dt" / "danh_tinh.json"),
                     "--chap-nhan", str(chap_nhan)]) == 0

    assert stat.S_IMODE(ra.stat().st_mode) == 0o600
    assert stat.S_IMODE(ra.parent.stat().st_mode) == 0o700
    ket = json.loads(ra.read_text("utf-8"))
    assert ket["tom_tat"]["ten_tep"]["tep_mang_so_nhay_cam"] == 1
    assert ket["tom_tat"]["ten_tep"]["tep_mang_so_nhay_cam_chua_chap_nhan"] == 0
    assert [v["trang_thai"] for v in ket["ten_tep"]["vi_pham"]] == ["da_chap_nhan"]
    assert ket["ten_tep"]["chap_nhan"]["quyet_dinh"]["ngay"] == "2001-01-01"
    assert ket["tom_tat"]["ten_tep"]["so_tep_trong_ho_so"] == len(TAI_LIEU)
    assert all(unicodedata.is_normalized("NFC", v["tep"]) for v in ket["ten_tep"]["vi_pham"])
    out = capsys.readouterr().out
    for bi_mat in (CQT, SO_VAT, "4321", "77/2025"):
        assert bi_mat not in out
