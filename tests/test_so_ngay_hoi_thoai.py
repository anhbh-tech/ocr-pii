"""Ba tầng thời gian trong ảnh chụp chat (`scripts/so_ngay.py`), dữ liệu bịa.

Không tên khách, không mã hồ sơ, không con số nào của kho thật.
"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("so_ngay_test", ROOT / "scripts" / "so_ngay.py")
sn = importlib.util.module_from_spec(spec)
sys.modules["so_ngay_test"] = sn
spec.loader.exec_module(sn)
sk = sn._so_kenh()

REL_A = "Phòng Mẫu/1. Nhóm mẫu/901.US. Nhãn mẫu/NH901.US_Tra cuu_011025.docx"
REL_KHONG_NGAY = "Phòng Mẫu/1. Nhóm mẫu/901.US. Nhãn mẫu/NH901.US_Anh chup.docx"
REL_HOP_DONG = "Phòng Mẫu/1. Nhóm mẫu/901.US. Nhãn mẫu/NH901.US_Hop dong_011025.docx"

CHAT_A = """[PROFILE_PICTURE]
Mr. Alpha Demo x Refiny
👤 3 thành viên | 🔲
T4 01/10/2025
Anh ơi hồ sơ cần bổ sung trước 30/9 ạ, bản scan ngày 8.10.2025 em gửi sau
10:05
Alpha
em hẹn 9.30 sáng mai nhé
09:12 [LIKE_ICON]
Tờ khai.pdf 1.26 MB
Vụ 1:25-cv-00001 bên em đang theo
Nhập @, tin nhắn tới Mr. Alpha Demo x Refiny
"""


def _tep(ngay):
    return sn.NgayHienThi(ngay, "ten_tep", ngay.strftime("%d%m%y"))


def test_gio_khong_bao_gio_la_ngay():
    ht = sn.thoi_gian_hoi_thoai(CHAT_A, _tep(dt.date(2025, 10, 8)), None)
    assert [(g["gia_tri"], g["nguon"]) for g in ht["gio"]] == [
        ("10:05", "dong_ho_chat"),
        ("09:30", "trong_loi"),
        ("09:12", "dong_ho_chat"),
    ]
    dong_gio = {g["dong"] for g in ht["gio"] if g["nguon"] == "dong_ho_chat"}
    assert not dong_gio & {n["dong"] for n in ht["ngay"]}


def test_ngay_co_nhom_thu_ba_la_ngay_con_24_10_va_co_tep_thi_khong():
    ht = sn.thoi_gian_hoi_thoai(
        "bản ngày 8.10.2025\nlúc 24.10 thì sao\nTờ khai.pdf 1.26 MB\n", None, None
    )
    assert [n["gia_tri"] for n in ht["ngay"]] == ["2025-10-08"]
    assert ht["gio"] == []


def test_moi_ngay_mang_nhan_nguon():
    ht = sn.thoi_gian_hoi_thoai(CHAT_A, _tep(dt.date(2025, 10, 8)), None)
    assert [(n["nguon"], n["gia_tri"]) for n in ht["ngay"]] == [
        ("ten_tep", "2025-10-08"),
        ("dong_ho_chat", "2025-10-01"),
        ("trong_loi", "2025-10-08"),
        ("trong_loi", "2025-09-30"),
    ]
    assert ht["dem"]["ngay_theo_nguon"] == {"ten_tep": 1, "dong_ho_chat": 1, "trong_loi": 2}


def test_ngay_thieu_nam_so_voi_tin_lien_truoc():
    ht = sn.thoi_gian_hoi_thoai(CHAT_A, _tep(dt.date(2025, 10, 8)), None)
    n = next(x for x in ht["ngay"] if x["nguyen_van"] == "30/9")
    assert n["suy_nam"] == {"so_voi": "2025-10-01", "so_voi_nguon": "dong_ho_chat", "lui_nam": False}
    assert n["dung_de"] == "hien_thi"


def test_roi_vao_tuong_lai_thi_lui_mot_nam_va_ghi_co():
    ht = sn.thoi_gian_hoi_thoai("lịch thanh toán đợt hai 20/7\n", _tep(dt.date(2026, 6, 25)), None)
    n = ht["ngay"][1]
    assert n["gia_tri"] == "2025-07-20"
    assert n["suy_nam"] == {
        "so_voi": "2026-06-25", "so_voi_nguon": "ten_tep",
        "lui_nam": True, "neu_khong_lui": "2026-07-20",
    }
    assert ht["dem"]["lui_nam"] == 1


def test_tep_khong_ngay_lay_moc_kenh():
    ht = sn.thoi_gian_hoi_thoai("bên em nộp hôm 20/12 ạ\n", None, dt.date(2026, 1, 15))
    assert ht["moc_nam"] == {"gia_tri": "2026-01-15", "nguon": "ten_tep_kenh"}
    assert ht["ngay"][0]["gia_tri"] == "2025-12-20"
    assert ht["ngay"][0]["suy_nam"]["so_voi_nguon"] == "ten_tep_kenh"


def test_khong_moc_nam_thi_khong_doan():
    ht = sn.thoi_gian_hoi_thoai("hẹn 20/12\nchia 31/2 phần\n", None, None)
    assert [(n["gia_tri"], n.get("thieu_moc_nam")) for n in ht["ngay"]] == [(None, True)]


def test_phan_cach_tuong_doi_khong_gia_tri_va_tra_moc_ve_anh():
    md = "T4 01/10/2025\n10:08 Hôm qua\nnhớ gửi trước 5/10 nhé\n"
    ht = sn.thoi_gian_hoi_thoai(md, _tep(dt.date(2025, 10, 8)), None)
    pc = ht["ngay"][2]
    assert (pc["gia_tri"], pc["nguon"], pc["tuong_doi"]) == (None, "dong_ho_chat", "hom_qua")
    assert ht["gio"] == [{"gia_tri": "10:08", "nguon": "dong_ho_chat",
                          "nguyen_van": "10:08 Hôm qua", "dong": 2}]
    # sau `Hôm qua` tin liền trước không còn là 01/10 mà là lúc chụp
    n = ht["ngay"][3]
    assert (n["gia_tri"], n["suy_nam"]["so_voi_nguon"]) == ("2025-10-05", "ten_tep")
    assert ht["dem"]["tuong_doi"] == 1 and ht["dem"]["ngay_co_gia_tri"] == 3


def _ghi_kenh(tmp_path, cac_tep):
    ket_qua = [sk.nhan_dien(sk.TaiLieu(d, rel, {"parse_pro": md})) for d, rel, md in cac_tep]
    kenh = sk.dung_kenh(ket_qua, "2025-10-01T00:00:00+00:00")
    dich = tmp_path / "kenh"
    dich.mkdir()
    sk.ghi_so(kenh, ket_qua, dich, tmp_path / "nhan_dien.json", "2025-10-01T00:00:00+00:00")
    (dich / "khac.json").write_text("{}")  # tệp không do sổ kênh sinh
    return kenh, dich


def test_dong_phan_cach_khop_so_kenh_ca_khi_tep_khong_ngay(tmp_path):
    khong_ngay = "Mr. Alpha Demo x Refiny\n3 thành viên\n20/12\nbên em đã nộp đơn ạ\n09:01\n"
    kenh, dich = _ghi_kenh(tmp_path, [("e1", REL_A, CHAT_A), ("e2", REL_KHONG_NGAY, khong_ngay)])
    so = sn.nap_so_kenh(dich)
    assert set(so) == {"e1", "e2"}
    assert so["e2"]["moc_kenh"] == dt.date(2025, 10, 1)
    ht = sn.thoi_gian_hoi_thoai(khong_ngay, None, so["e2"]["moc_kenh"])
    tin = next(t for k in kenh.values() for t in k["tin"] if t["doc_id"] == "e2")
    assert [n["gia_tri"] for n in ht["ngay"] if n["nguon"] == "dong_ho_chat"] == [
        d["moc"]["ngay"] for d in tin["doan"]
    ] == ["2024-12-20"]


def test_dung_so_gan_nhan_nguon_cho_ca_ba_truong(tmp_path, monkeypatch):
    kho = tmp_path / "ade_out"
    for ma, rel, md in (
        ("aaaa000000000001", REL_A, CHAT_A),
        ("aaaa000000000002", REL_HOP_DONG, "HỢP ĐỒNG\nNgày ký: 02/10/2025\n"),
    ):
        (kho / ma).mkdir(parents=True)
        (kho / ma / "meta.json").write_text(json.dumps({"source": rel}))
        (kho / ma / "parse_pro.json").write_text(json.dumps({"markdown": md}))
    _, dich = _ghi_kenh(tmp_path, [("aaaa000000000001", REL_A, CHAT_A)])
    goc = tmp_path / "goc" / REL_A
    goc.parent.mkdir(parents=True)
    goc.write_text("x")
    monkeypatch.setattr(sn, "KHO", kho)
    monkeypatch.setattr(sn, "NGUON", tmp_path / "goc")
    monkeypatch.setattr(sn, "KENH", dich)
    monkeypatch.setattr(sn, "BAO_CAO_77", tmp_path / "khong_co.json")

    so = sn.dung_so()
    chat, hd = so["tai_lieu"][1], so["tai_lieu"][0]
    assert chat["duong_dan"] == REL_A and hd["duong_dan"] == REL_HOP_DONG
    assert chat["ngay_luu_tep"]["nguon"] == "ten_tep"
    assert chat["ngay_sua_dia"]["nguon"] == "mtime"
    assert chat["ngay_van_ban"]["nguon"] == "dong_ho_chat"  # 01/10/2025 đứng đầu, trên dòng phân cách
    assert chat["hoi_thoai"]["kenh_id"] == sk.kenh_id("Mr. Alpha Demo x Refiny")
    assert hd["hoi_thoai"] is None
    assert hd["ngay_van_ban"]["nguon"] == "trong_loi" and hd["ngay_van_ban"]["dung_de"] == "tinh_han"
    t = so["tong_ket"]
    assert t["ngay_thieu_nguon"] == 0
    assert t["hoi_thoai"]["tep"] == 1 and t["hoi_thoai"]["gio"] == 3
    assert t["hoi_thoai"]["ngay_theo_nguon"] == {"ten_tep": 1, "dong_ho_chat": 1, "trong_loi": 2}
