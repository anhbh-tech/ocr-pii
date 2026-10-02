"""Danh mục ảnh nhúng: ba nhóm, và vì sao thứ tự kiểm quan trọng."""
from __future__ import annotations

from ocr_lab.embedded_images import (
    NGUONG_LAP_KHO, AnhNhung, DanhMuc, bam_noi_dung, phan_nhom,
)


def _anh(**kw) -> AnhNhung:
    goc = dict(tep="a.pdf", trang=1, xref=1, rong=800, cao=600,
               ti_le_trang=0.3, bam_anh="aaa")
    goc.update(kw)
    return AnhNhung(**goc)


def test_logo_co_chu_van_la_logo():
    """Thứ tự kiểm: LẶP trước, CÓ-CHỮ sau.

    Một logo công ty có chữ (tên công ty, địa chỉ) vẫn là logo. Đảo thứ tự
    thì mọi chân trang đều rơi vào nhóm 'nội dung' và ta trả tiền để đọc
    lại cùng một dòng địa chỉ hàng trăm lần.
    """
    a = _anh(n_vung_chu=9, bam_anh="logo")
    phan_nhom(a, {"logo": NGUONG_LAP_KHO})
    assert a.nhom == "khung"
    assert "lần" in a.ly_do


def test_anh_it_vung_chu_la_minh_hoa():
    a = _anh(n_vung_chu=1, bam_anh="x")
    phan_nhom(a, {"x": 1})
    assert a.nhom == "trong"


def test_anh_nhieu_chu_khong_lap_la_noi_dung():
    a = _anh(n_vung_chu=12, ti_le_dien_tich_chu=0.34, bam_anh="y")
    phan_nhom(a, {"y": 1})
    assert a.nhom == "noi_dung"
    assert "lớp text KHÔNG chứa" in a.ly_do


def test_dem_lap_tren_TOAN_KHO_khong_trong_mot_tep():
    """Chân trang xuất hiện một lần mỗi tệp — đếm trong phạm vi tệp không thấy.

    Đây là lý do `phan_nhom` nhận `dem_bam` của cả kho thay vì tự đếm.
    """
    chan = [_anh(tep=f"{i}.pdf", n_vung_chu=6, bam_anh="chan") for i in range(6)]
    dem = {"chan": len(chan)}
    for a in chan:
        phan_nhom(a, dem)
    assert all(a.nhom == "khung" for a in chan)


def test_duy_nhat_gop_ban_sao():
    """Kho có bản sao cùng tài liệu ở nhiều thư mục.

    Đo thật: 59 lượt xuất hiện nhưng chỉ 38 ảnh khác nhau. Chạy engine trên
    bản sao là trả tiền hai lần cho cùng một câu trả lời.
    """
    dm = DanhMuc(anh=[
        _anh(tep="x/a.pdf", bam_anh="same", nhom="noi_dung"),
        _anh(tep="y/a.pdf", bam_anh="same", nhom="noi_dung"),
        _anh(tep="z/b.pdf", bam_anh="other", nhom="noi_dung"),
    ])
    assert len(dm.theo_nhom("noi_dung")) == 3
    assert len(dm.duy_nhat("noi_dung")) == 2


def test_bam_on_dinh_va_phan_biet():
    assert bam_noi_dung(b"abc") == bam_noi_dung(b"abc")
    assert bam_noi_dung(b"abc") != bam_noi_dung(b"abd")
