"""Sổ hình thức: luật rẻ bắt ảnh chụp chat trong ô sản phẩm, chấm ba mức.

Toàn bộ dữ liệu ở đây là bịa — hồ sơ, nhãn hiệu, số văn bằng đều không có
thật. Test không đọc kho khách hàng.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _nap():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "so_hinh_thuc_test", ROOT / "scripts" / "so_hinh_thuc.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["so_hinh_thuc_test"] = m
    spec.loader.exec_module(m)
    return m


sht = _nap()

KHOA = "<Mã TV>_Ket qua tra cuu_<ddmmyy>.docx"
MAU = "<Mã TV>_Ket qua tra cuu_<ddmmyy>.docx"

CHROME = "[ảnh nhóm]\nNhóm ZZ tư vấn\n👤 4 thành viên | 🔲\n👥 📹 🔍\n"
DU = ("Chị ơi, bên em đã tra cứu sơ bộ khả năng bảo hộ trên cơ sở dữ liệu miễn phí "
      "(cập nhật 65% lượng đơn đăng ký).\n"
      "Nhãn hiệu “ZETA” cho nhóm 099 có khả năng bảo hộ khoảng 40% do phát hiện "
      "đối chứng sau:\n- Đối chứng “ZETTA”, văn bằng bảo hộ số 1234567\n")
THIEU = "Em gửi chị kết quả tra cứu trong tệp đính kèm 📎\n"
BAO_CAO = "# Báo cáo tra cứu\n\nKhả năng bảo hộ khoảng 40%.\n\n<table><tr><td>ZETTA</td></tr></table>"


# ── mệnh đề ──────────────────────────────────────────────────────────────

def test_khong_dau_thay_d_truoc_nfd():
    assert sht.khong_dau("Đối chứng đã") == "doi chung da"
    assert sht.khong_dau("40%") == "40%"


def test_emoji_chi_lay_mat_phang_phu():
    """★ ✓ ➡ là ký hiệu văn bản gõ, không phải emoji khung chat."""
    assert sht.tin_hieu("Đánh giá ★★★★ ✓ ➡ xong")["so_emoji"] == 0
    assert sht.tin_hieu("ok 👍")["so_emoji"] == 1


def test_luat_re_can_du_bon_menh_de():
    th = {"so_khung_anh": 1, **sht.tin_hieu(CHROME + DU)}
    assert sht.luat_re(sht.menh_de(th))
    for doi in ({"so_khung_anh": 2}, {"so_khung_anh": 0}, {"so_tieu_de": 1},
                {"so_bang": 1}, {"so_emoji": 0}):
        assert not sht.luat_re(sht.menh_de({**th, **doi})), doi


def test_ti_le_cap_nhat_co_so_du_lieu_khong_tinh_la_ket_luan():
    """`65% lượng đơn` nằm sau `khả năng bảo hộ` nhưng không phải kết luận."""
    chi_co_65 = DU.split("\n")[0]
    nd = sht.kiem_noi_dung("ket qua tra cuu", chi_co_65)
    assert {x["ma"] for x in nd["thieu"]} == {"ket_luan", "doi_chung"}
    assert sht.kiem_noi_dung("ket qua tra cuu", DU)["du"]


def test_khong_co_doi_chung_van_la_du():
    t = "Nhãn hiệu có khả năng bảo hộ khoảng 90%, chưa phát hiện nhãn hiệu tương tự."
    assert sht.kiem_noi_dung("ket qua tra cuu", t)["du"]


def test_so_don_co_gach_noi_va_ti_le_thap_phan_la_du():
    t = 'Khả năng bảo hộ 40.5%. Đối chứng "QWX", đơn đăng ký số 4-2099-00001.'
    assert sht.kiem_noi_dung("ket qua tra cuu", t)["du"]


def test_o_chua_co_luat_noi_dung():
    assert sht.kiem_noi_dung("hop dong", DU) is None
    muc, _, nd = sht.cham_o(True, "hop dong", DU)
    assert muc is None and nd is None


def test_cham_o_ba_muc():
    assert sht.cham_o(False, "ket qua tra cuu", BAO_CAO)[0] == "dat"
    assert sht.cham_o(True, "ket qua tra cuu", CHROME + DU)[0] == "du_noi_dung_sai_hinh_thuc"
    assert sht.cham_o(True, "ket qua tra cuu", CHROME + THIEU)[0] == "khong_dat"
    assert set(sht.MUC) == {"dat", "du_noi_dung_sai_hinh_thuc", "khong_dat"}


# ── đầu cuối trên kho bịa ────────────────────────────────────────────────

def _docx(p: Path, chu: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:t>{chu}</w:t></w:document>")


def _tai_lieu(ade: Path, kho: Path, i: str, rel: str, md: str) -> None:
    f = kho / rel
    if f.suffix == ".docx":
        _docx(f, "Báo cáo tra cứu gõ tay " * 20)
    else:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"\x89PNG\r\n\x1a\n")
    d = ade / i
    d.mkdir(parents=True)
    (d / "meta_pro.json").write_text(json.dumps(
        {"source": rel, "model": "dpt-3-pro", "parsed_at": "2026-09-15T00:00:00+00:00"}))
    (d / "parse_pro.json").write_text(json.dumps(
        {"markdown": md, "metadata": {"page_count": 1}}, ensure_ascii=False))


def _ho_so(n: str) -> str:
    return f"{n}.US. ZETA in Class 099"


def _rel(n: str, ten: str) -> str:
    return f"Phòng IP/1. Nhóm dịch vụ/{_ho_so(n)}/0. Info/{ten}"


def _dung_kho(tmp: Path) -> dict:
    ade, kho = tmp / "ade_out", tmp / "kho"
    ca = {
        # hồ sơ 001: chỉ có ảnh chụp chat đủ nội dung → mức giữa, cổng giữ xanh + cờ
        "a1": (_rel("001", "ZZ001_Tin nhan ket qua tra cuu_010199.png"), CHROME + DU, True),
        # hồ sơ 002: ảnh chụp chat thiếu nội dung → không đạt, cổng đỏ
        "b2": (_rel("002", "ZZ002_Ket qua tra cuu_010199.png"), CHROME + THIEU, True),
        # hồ sơ 003: ảnh chụp chat + bản báo cáo gõ đạt cùng ô → không còn nợ
        "c3": (_rel("003", "ZZ003_Tin nhan ket qua tra cuu_010199.png"), CHROME + DU, True),
        "d3": (_rel("003", "ZZ003_Ket qua tra cuu_010199.docx"), BAO_CAO, True),
        # hồ sơ 004: có khung chat nhưng có bảng → luật không bắn → đạt; vênh
        # chỉ ghi vào khong_quyet_duoc, không đổi mức
        "e4": (_rel("004", "ZZ004_Ket qua tra cuu_010199.png"),
               CHROME + DU + "<table><tr><td>x</td></tr></table>", True),
        # ảnh chụp chat ngoài mọi ô sản phẩm → đạt
        "f5": (_rel("005", "Bao khach 1.png"), CHROME + DU, False),
        # hồ sơ 006: ảnh chụp chat thiếu nội dung, nhưng ô còn một nguồn chưa parse
        "g6": (_rel("006", "ZZ006_Ket qua tra cuu_010199.png"), CHROME + THIEU, True),
        # hồ sơ 007: ảnh chụp chat giữ ô chưa có luật nội dung → không mức
        "h7": (_rel("007", "ZZ007_Hop dong_010199.png"), CHROME + DU, False),
    }
    nguon = [_rel("006", "ZZ006_Ket qua tra cuu_010199.docx")]
    for i, (rel, md, trong_o) in ca.items():
        # Tên trong meta ghi NFD như Path.rglob trả trên macOS; sổ q1 ghi NFC.
        _tai_lieu(ade, kho, i, unicodedata.normalize("NFD", rel), md)
        if trong_o:
            nguon.append(rel)
    q1 = {
        "anh_xa": {KHOA: {
            "muc_bat_buoc": [{"ten": "ket qua tra cuu", "nguyen_van": MAU}],
            "hoat_dong": [{"id": "N_2_3", "ten": "Lập báo cáo tra cứu"}],
            "ten_goi_chap_nhan": [{"ten": "ket qua tra cuu", "cho_muc": "ket qua tra cuu",
                                   "phuong_phap": "exact", "nguon": nguon}],
        }, "<Mã TV>_Hop dong_<ddmmyy>.pdf": {
            "muc_bat_buoc": [{"ten": "hop dong", "nguyen_van": "<Mã TV>_Hop dong_<ddmmyy>.pdf"}],
            "hoat_dong": [{"id": "N_1_1", "ten": "Ký hợp đồng"}],
            "ten_goi_chap_nhan": [{"ten": "hop dong", "cho_muc": "hop dong",
                                   "phuong_phap": "exact", "nguon": [ca["h7"][0]]}],
        }},
        "do_luong": {"chi_tiet": [
            {"ho_so": _ho_so(n), "hoat_dong": "N_2_3", "khoa": KHOA,
             "so_do": "quy-trinh.bpmn", "truoc": "do", "sau": "xanh"}
            for n in ("001", "002", "003", "004", "006")]},
    }
    (tmp / "q1.json").write_text(json.dumps(q1, ensure_ascii=False))
    (tmp / "nhan.json").write_text(json.dumps({"nhan": {
        "a1": {"chat": True}, "b2": {"chat": True}, "d3": {"chat": False},
        "e4": {"chat": True}, "f5": {"chat": True}}}))
    return sht.lap_so(ade, kho, tmp / "q1.json", tmp / "nhan.json")


def test_dau_cuoi_muc_va_bang_viec(tmp_path):
    so = _dung_kho(tmp_path)
    muc = {t["id"]: t["muc"] for t in so["tai_lieu"]}
    assert muc == {"a1": "du_noi_dung_sai_hinh_thuc", "b2": "khong_dat",
                   "c3": "du_noi_dung_sai_hinh_thuc", "d3": "dat",
                   "e4": "dat", "f5": "dat", "g6": "khong_dat",
                   "h7": None}
    assert so["tong"]["lo_199"]["muc"] == {"dat": 3, "du_noi_dung_sai_hinh_thuc": 2,
                                           "khong_dat": 2}
    assert so["tong"]["lo_199"]["khong_muc"] == 1
    assert [g["id"] for g in so["muc_giua"]] == ["a1", "c3"]

    bv = {b["ho_so"]: b for b in so["bang_viec"]}
    # 003 có bản đạt; 004 luật không bắn; 006 còn nguồn chưa parse; 007 không mức
    assert set(bv) == {_ho_so("001"), _ho_so("002")}
    a = bv[_ho_so("001")]
    assert (a["cong_q1"], a["cong_sau_hinh_thuc"], a["co"]) == ("xanh", "xanh", ["nợ hình thức"])
    assert MAU in a["viec_con_no"]
    b = bv[_ho_so("002")]
    assert (b["cong_sau_hinh_thuc"], b["co"]) == ("do", [])
    assert {x["trang_thai"] for x in so["bang_viec"]} <= {"no_hinh_thuc", "khong_dat"}


def test_dau_cuoi_hinh_thuc_va_khong_mo_tep_thua(tmp_path):
    t = {x["id"]: x for x in _dung_kho(tmp_path)["tai_lieu"]}
    assert t["a1"]["hinh_thuc"] == "anh_chup_chat"
    assert t["e4"]["venh"] and t["e4"]["hinh_thuc"] != "anh_chup_chat"
    # d3 có tiêu đề, có bảng, không khung chat → không mở tệp gốc
    assert t["d3"]["tin_hieu"]["cau_truc"] == "khong_xet"
    assert t["d3"]["menh_de"]["mot_khung_anh"] is None
    assert t["d3"]["hinh_thuc"] == "khong_xet" and not t["d3"]["luat_re"]


def test_dau_cuoi_khong_quyet_duoc_va_do_chinh_xac(tmp_path):
    so = _dung_kho(tmp_path)
    kq = {k["id"]: k for k in so["khong_quyet_duoc"]}
    assert set(kq) == {"e4", "g6", "h7"}
    assert "khong_bang" in kq["e4"]["ly_do"][0]
    assert "ZZ006_Ket qua tra cuu_010199.docx" in kq["g6"]["ly_do"][0]
    assert "chưa có luật nội dung cho 'hop dong'" in kq["h7"]["ly_do"]
    assert kq["h7"]["muc"] is None

    d = so["do_chinh_xac"]
    assert d["co_mau"] == 5
    assert d["luat_re"]["dung_duong"] == 3 and d["luat_re"]["sot_id"] == ["e4"]
    assert d["luat_re"]["do_chinh_xac"] == 1.0
    assert d["khung_chat"]["do_phu"] == 1.0


def test_so_khong_mang_toan_van(tmp_path):
    so = json.dumps(_dung_kho(tmp_path), ensure_ascii=False)
    assert "1234567" not in so and "ZETTA" not in so
