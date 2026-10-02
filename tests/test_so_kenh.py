"""Sổ kênh hội thoại (`scripts/so_kenh.py`) trên dữ liệu bịa hoàn toàn.

Không tên khách, không mã hồ sơ, không con số nào của kho thật.
"""

import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

from ocr_lab import danh_tinh

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("so_kenh_test", ROOT / "scripts" / "so_kenh.py")
sk = importlib.util.module_from_spec(spec)
sys.modules["so_kenh_test"] = sk
spec.loader.exec_module(sk)


CHAT_A = """[PROFILE_PICTURE]
Mr. Alpha Demo x Refiny
👤 3 thành viên | 🔲
[ICONS]
T4 01/10/2025
Anh @Alpha ơi, bên em đã tra cứu sơ bộ nhãn hiệu mẫu số 001099000001 ạ
10:05
[PROFILE_PICTURE]
Alpha
em ơi gửi giúp anh bản dự thảo nhé
10:12
Dạ vâng em gửi anh ạ
10.15
Nhập @, tin nhắn tới Mr. Alpha Demo x Refiny
"""

# Cùng kênh, OCR lệch chữ ở tiêu đề (`-`, `×`, `REFNIY`); tệp lưu ở hồ sơ khác.
CHAT_B = """Mr. Alpha-Demo × REFNIY
3 thành viên
Chị @ ơi bên em đã nộp đơn ạ
09:01
"""

# Giấy đăng ký doanh nghiệp bịa: có chữ "thành viên" nhưng không có tiêu đề kênh.
GIAY_DKKD = """GIẤY CHỨNG NHẬN ĐĂNG KÝ DOANH NGHIỆP
CÔNG TY TNHH HAI THÀNH VIÊN TRỞ LÊN
Mã số doanh nghiệp: 001099000001
Danh sách thành viên góp vốn
2 thành viên
"""


def _tl(doc_id, rel, pro=None, verity=None):
    parse = {}
    if pro is not None:
        parse["parse_pro"] = pro
    if verity is not None:
        parse["parse"] = verity
    return sk.TaiLieu(doc_id, rel, parse)


REL_A = "Phòng Mẫu/1. Nhóm mẫu/901.US. Nhãn mẫu/NH901.US_Tra cuu_011025.docx"
KID = sk.kenh_id("Mr. Alpha Demo × REFINY")
REL_B = "Phòng Mẫu/2. Nhóm khác/902. US. Bản quyền mẫu/BQ902.US_Nop don_051025.docx"


# ── bộ nhận diện ──


def test_can_ca_hai_dau_hieu():
    assert sk.nhan_dien(_tl("a", REL_A, CHAT_A)).trung
    chi_tieu_de = "Mr. Alpha Demo x Refiny\nxin chào\n"
    chi_thanh_vien = "Nhóm bạn bè\n4 thành viên\n"
    assert not sk.nhan_dien(_tl("b", REL_A, chi_tieu_de)).trung
    assert not sk.nhan_dien(_tl("c", REL_A, chi_thanh_vien)).trung


def test_giay_dang_ky_doanh_nghiep_bi_loai():
    kq = sk.nhan_dien(_tl("d", REL_A, GIAY_DKKD))
    assert not kq.trung and not kq.co_tieu_de and kq.co_thanh_vien


def test_dau_hieu_phai_cung_mot_ban_parse():
    kq = sk.nhan_dien(_tl("e", REL_A, "Mr. Alpha Demo x Refiny\n", "5 members\n"))
    assert not kq.trung and kq.co_tieu_de and kq.co_thanh_vien


def test_ban_verity_du_hai_dau_hieu_van_trung():
    kq = sk.nhan_dien(_tl("f", REL_A, "rỗng\n", CHAT_B))
    assert kq.trung and kq.ban == "parse"


def test_o_soan_tin_va_cau_nhac_ten_kenh_khong_la_tieu_de():
    assert sk.tieu_de_trong("Nhập @, tin nhắn tới Mr. Alpha Demo x Refiny") == []
    assert sk.tieu_de_trong("@, Message Mr. Alpha Demo x Refiny") == []
    assert sk.tieu_de_trong("Bảng so sánh A x B") == []  # không phải tên hãng


def test_tieu_de_co_duoi():
    [(td, doi_tac)] = sk.tieu_de_trong("Mr. Beta x REFINY - Review")
    assert td == "Mr. Beta × REFINY - Review" and doi_tac == "Mr. Beta"
    [(td, _)] = sk.tieu_de_trong("Gamma/ Demo x Refiny | Nhãn hiệu")
    assert td == "Gamma/ Demo × REFINY | Nhãn hiệu"


def test_kenh_id_on_dinh_qua_loi_ocr():
    assert sk.kenh_id("Mr. Alpha Demo × REFINY") == sk.kenh_id("Mr. Alpha Demo × REFNIY")
    assert sk.kenh_id("Ms. Thử Mẫu × REFINY") == sk.kenh_id("Ms. Thứ Mẫu × REFINY")
    assert sk.kenh_id("Mr. Beta × REFINY - Review") != sk.kenh_id("Mr. Beta × REFINY")


def test_kenh_id_khong_mang_ten():
    kid = sk.kenh_id("Mr. Alpha Demo × REFINY")
    assert re.fullmatch(r"k-[0-9a-f]{10}", kid)
    assert "alpha" not in kid and "demo" not in kid


def test_kenh_id_trung_giua_hai_so():
    # Cùng một tiêu đề đi qua sổ kênh và sổ danh tính phải ra cùng một khoá.
    from ocr_lab.danh_tinh import dung_so

    assert sk.kenh_id is danh_tinh.kenh_id
    kq = sk.nhan_dien(_tl("a", REL_A, CHAT_A))
    [kid_kenh] = sk.dung_kenh([kq])
    so = dung_so([(REL_A, "h")], doc_id_for=lambda r: "a",
                 kenh_theo_doc={"a": {"tieu_de": kq.tieu_de[0][0], "thanh_vien": 4}})
    kid_danh_tinh = {k["kenh_id"] for k in so["kenh"]}
    assert kid_danh_tinh == {kid_kenh}


# ── thời gian ──


def test_gio_chat_khong_phai_ngay():
    assert sk.doc_gio("13.43") == "13:43"
    assert sk.doc_gio("9:05") == "09:05"
    assert sk.doc_gio("24.10") is None
    assert sk.doc_gio("8.10.2025") is None


def test_ngay_thieu_nam_lui_mot_nam_neu_roi_vao_tuong_lai():
    moc = dt.date(2026, 1, 15)
    assert sk.ngay_thieu_nam(10, 1, moc) == dt.date(2026, 1, 10)
    assert sk.ngay_thieu_nam(20, 12, moc) == dt.date(2025, 12, 20)


def test_ngay_thieu_nam_khong_hop_le_nam_moc_thi_thu_nam_truoc():
    moc = dt.date(2025, 3, 5)
    assert sk.ngay_thieu_nam(29, 2, moc) == dt.date(2024, 2, 29)
    assert sk.doc_phan_cach("29/02", moc)["ngay"] == "2024-02-29"


def test_phan_cach():
    pc = sk.doc_phan_cach("T5 21/08/2025", None)
    assert pc["ngay"] == "2025-08-21"
    pc = sk.doc_phan_cach("13:45 09/09/2025", None)
    assert pc["ngay"] == "2025-09-09" and pc["gio"] == "13:45"
    pc = sk.doc_phan_cach("10:08 Hôm qua", None)
    assert pc["tuong_doi"] == "hom_qua" and pc["ngay"] is None
    pc = sk.doc_phan_cach("20/12", dt.date(2026, 1, 15))
    assert pc["ngay"] == "2025-12-20" and pc["suy_nam"]


def test_cat_doan_theo_dong_gio():
    doan, hinh = sk.cat_doan(CHAT_A, dt.date(2025, 10, 1))
    assert [d["gio"] for d in doan] == ["10:05", "10:12", "10:15"]
    assert all(d["moc"]["ngay"] == "2025-10-01" for d in doan)
    noi = "\n".join(x for d in doan for x in d["dong"])
    assert "Nhập @" not in noi and "thành viên" not in noi and "x Refiny" not in noi
    assert all(h["giao_dien"] for h in hinh)


# ── hình ──


def test_hinh_giao_dien_bo_bang_chung_cu_giu():
    md = (
        '<figure type="ILLUSTRATION"><description>Group profile picture</description></figure>\n'
        '<figure type="CHART">A chat screenshot<description>trademark results</description>'
        "<table><tr><th>Nhãn</th><th>Khả năng</th></tr><tr><td>DEMO</td><td>55%</td></tr></table>"
        "</figure>\nMr. Alpha Demo x Refiny\n3 thành viên\n"
    )
    doan, hinh = sk.cat_doan(md, None)
    assert [h["giao_dien"] for h in hinh] == [True, False]
    assert "DEMO | 55%" in doan[0]["dong"]


# ── người nói ──


def test_nguoi_noi_tu_giong():
    assert sk.nguoi_noi(["Dạ em nhận thông tin của anh ạ"])[0] == "refiny"
    assert sk.nguoi_noi(["bên em đã nộp đơn"])[0] == "refiny"
    assert sk.nguoi_noi(["Chị Demo ơi, liên quan đến đơn"])[0] == "refiny"
    assert sk.nguoi_noi(["em ơi gửi giúp chị bản dự thảo"])[0] == "khach"
    assert sk.nguoi_noi(["đúng ko e"])[0] == "khach"
    assert sk.nguoi_noi(["cảm ơn bạn, mình đồng ý"])[0] == "khach"
    assert sk.nguoi_noi(["Uh k cần"])[0] == "khach"


def test_goi_ten_nhan_vien_khong_la_refiny_goi_chi():
    ben, dau_hieu = sk.nguoi_noi(["@Demo Chi ơi xem giúp chị"])
    assert ben == "khach" and "refiny:goi_anh_chi" not in dau_hieu


def test_khong_du_dau_hieu_thi_de_trong():
    assert sk.nguoi_noi(["Phương án 1: nộp đơn trực tuyến"]) == (None, [])
    ben, dau_hieu = sk.nguoi_noi(["em ơi", "bên em"])  # một đối một
    assert ben is None and len(dau_hieu) == 2


# ── dựng kênh ──


def test_kenh_n_n_voi_ho_so_va_gop_ban_trung():
    rel_a2 = REL_A.replace("Tra cuu_011025", "Tra cuu ban sao_011025")
    ket_qua = [
        sk.nhan_dien(_tl("aaaa000000000001", REL_A, CHAT_A)),
        sk.nhan_dien(_tl("aaaa000000000002", REL_B, CHAT_B)),
        # cùng nội dung với tệp đầu, lưu ở hồ sơ thứ hai
        sk.nhan_dien(_tl("aaaa000000000003", REL_B.replace("Nop don_051025", "Ban sao_011025"), CHAT_A)),
        sk.nhan_dien(_tl("aaaa000000000004", rel_a2, GIAY_DKKD)),
    ]
    kenh = sk.dung_kenh(ket_qua)
    assert list(kenh) == [KID]
    k = kenh[KID]
    assert k["thuoc_ho_so"] == ["901.US", "902.US"]
    assert k["so_tin"] == {"truoc_gop": 3, "sau_gop": 2}
    gop = next(t for t in k["tin"] if t["ban_trung"])
    assert gop["ho_so"] == ["901.US", "902.US"]
    assert [b["doc_id"] for b in gop["ban_trung"]] == ["aaaa000000000003"]
    # xếp theo ngày tên tệp: 011025 trước 051025
    assert [t["thoi_diem"]["ngay"] for t in k["tin"]] == ["2025-10-01", "2025-10-05"]
    # tiêu đề hai biến thể OCR → ghi xung đột, không tự chọn im lặng
    assert any(x["loai"] == "tieu_de" for x in k["xung_dot"])
    assert k["tieu_de"] == "Mr. Alpha Demo × REFINY"


def test_nguoi_nhan_lay_tu_tieu_de_khi_at_mat_ten():
    kq = sk.nhan_dien(_tl("bbbb000000000001", REL_B, CHAT_B))
    k = sk.dung_kenh([kq])[KID]
    [d] = k["tin"][0]["doan"]
    assert d["nguoi_noi"] == "refiny" and d["at_mat_ten"] == 1
    assert d["nguoi_nhan"] == {"vai": "khach", "ten": "Mr. Alpha-Demo", "nguon": "tieu_de_kenh"}
    assert k["at_mat_ten"] == 1


def test_thanh_vien_lech_thi_ghi_xung_dot():
    b4 = CHAT_B.replace("3 thành viên", "4 thành viên")
    ket_qua = [
        sk.nhan_dien(_tl("c1", REL_A, CHAT_A)),
        sk.nhan_dien(_tl("c2", REL_B, b4)),
    ]
    k = sk.dung_kenh(ket_qua)[KID]
    assert k["thanh_vien"] == {"so": 4, "cac_gia_tri": [3, 4], "nhat_quan": False}
    assert {"loai": "thanh_vien", "gia_tri": [3, 4]} in k["xung_dot"]


def test_tieu_de_chi_lech_dau_van_mot_kenh_nhung_ghi_xung_dot():
    c1 = "Ms. Thử Mẫu x Refiny\n3 thành viên\nbên em đã nộp đơn ạ\n09:01\n"
    c2 = "Ms. Thứ Mẫu x Refiny\n3 thành viên\nbên em đã gửi bản dự thảo ạ\n09:05\n"
    kenh = sk.dung_kenh([
        sk.nhan_dien(_tl("d1", REL_A, c1)),
        sk.nhan_dien(_tl("d2", REL_B, c2)),
    ])
    [k] = kenh.values()
    assert k["so_tin"]["sau_gop"] == 2
    assert {"loai": "tieu_de_dau", "gia_tri": ["Ms. Thứ Mẫu × REFINY", "Ms. Thử Mẫu × REFINY"]} in k["xung_dot"]
    assert not any(x["loai"] == "tieu_de" for x in k["xung_dot"])


def test_tep_khong_ngay_lay_nam_kenh_cho_ngay_thieu_nam():
    khong_ngay = "Phòng Mẫu/2. Nhóm khác/902. US. Bản quyền mẫu/BQ902.US_Anh chup.docx"
    c = "Mr. Alpha Demo x Refiny\n3 thành viên\n20/12\nbên em đã nộp đơn ạ\n09:01\n"
    k = sk.dung_kenh([
        sk.nhan_dien(_tl("e1", REL_A, CHAT_A)),
        sk.nhan_dien(_tl("e2", khong_ngay, c)),
    ])[KID]
    tin = next(t for t in k["tin"] if t["doc_id"] == "e2")
    assert tin["thoi_diem"] is None
    assert tin["doan"][0]["moc"]["ngay"] == "2024-12-20"


def test_tin_rong_khong_bi_gop_nham():
    rong = "Mr. Alpha Demo x Refiny\n3 thành viên\n"
    k = sk.dung_kenh([
        sk.nhan_dien(_tl("f1", REL_A, rong)),
        sk.nhan_dien(_tl("f2", REL_B, rong)),
    ])[KID]
    assert k["so_tin"] == {"truoc_gop": 2, "sau_gop": 2}
    assert all(not t["ban_trung"] for t in k["tin"])


def test_nap_kho_va_ghi_so(tmp_path):
    kho = tmp_path / "ade_out"
    for doc_id, rel, md in (
        ("dddd000000000001", REL_A, CHAT_A),
        ("dddd000000000002", REL_B, GIAY_DKKD),
    ):
        d = kho / doc_id
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"source": rel}))
        (d / "parse_pro.json").write_text(json.dumps({"markdown": md}))
    ket_qua = [sk.nhan_dien(t) for t in sk.nap_kho(kho)]
    kenh = sk.dung_kenh(ket_qua, "2025-10-01T00:00:00+00:00")
    dich, so = tmp_path / "kenh", tmp_path / "so" / "nhan_dien_kenh.json"
    dich.mkdir()
    (dich / "k-refiny-00000000.json").write_text(json.dumps({"nguon_sinh": sk.NGUON_SINH}))
    (dich / "cua-so-khac.json").write_text("{}")  # tệp không do sổ này sinh: không được xoá
    sk.ghi_so(kenh, ket_qua, dich, so, "2025-10-01T00:00:00+00:00")
    assert sorted(p.name for p in dich.iterdir()) == ["cua-so-khac.json", f"{KID}.json"]
    ban_ghi = json.loads((dich / f"{KID}.json").read_text())
    assert ban_ghi["tin"][0]["doc_id"] == "dddd000000000001"
    nd = json.loads(so.read_text())
    assert [x["doc_id"] for x in nd["trung"]] == ["dddd000000000001"]
    assert nd["mot_dau_hieu"][0]["doc_id"] == "dddd000000000002"
