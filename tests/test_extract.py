"""Trích xuất cục bộ: cùng khuôn ADE, hai kiểu neo vị trí."""
from __future__ import annotations

import pytest

from ocr_lab.extract import trich_xuat


def _phan_tu(kq):
    return [e for p in kq["structure"]["children"] for e in p["children"]]


def test_duoi_khong_doc_duoc_thi_nem_loi(tmp_path):
    """Tệp rỗng và tệp không đọc được là HAI chuyện khác nhau.

    Trả về cây rỗng cho cả hai thì phía web không phân biệt nổi, và người
    dùng thấy một danh sách trắng không biết vì sao.
    """
    f = tmp_path / "a.zip"
    f.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValueError, match="chưa trích xuất được"):
        trich_xuat(f)


def test_van_ban_neo_theo_dong_va_range_tro_dung_markdown(tmp_path):
    """`range` là hợp đồng giữa structure và markdown — phải khớp từng ký tự.

    Mọi thứ phía web (tô sáng chunk, cắt span, vẽ diff) đọc chữ bằng cách
    cắt `markdown[start:end]`. Lệch một ký tự là hiện sai chữ mà KHÔNG báo
    lỗi — kiểu sai người soát không phát hiện được.
    """
    f = tmp_path / "a.txt"
    f.write_text("Đoạn một.\n\nĐoạn hai dài hơn.\n", "utf-8")
    kq = trich_xuat(f)

    pt = _phan_tu(kq)
    assert len(pt) == 2
    for e in pt:
        g = e["grounding"]
        assert g["kind"] == "path"
        r = g["range"]
        # Chính là phép cắt mà phía web dùng.
        assert kq["markdown"][r["start"]:r["end"]] == kq["markdown"][
            r["start"]:r["end"]].strip()
        assert r["end"] > r["start"]

    assert kq["markdown"][pt[0]["grounding"]["range"]["start"]:
                          pt[0]["grounding"]["range"]["end"]] == "Đoạn một."
    assert kq["markdown"][pt[1]["grounding"]["range"]["start"]:
                          pt[1]["grounding"]["range"]["end"]] == "Đoạn hai dài hơn."


def test_moi_phan_tu_deu_co_dung_mot_kieu_neo(tmp_path):
    """Neo phải là `box` HOẶC `path`, không được thiếu cả hai.

    Phần tử không có neo nào lọt qua `collectChunks` rồi biến mất khỏi danh
    sách — nội dung có trong markdown mà không có chunk nào trỏ tới.
    """
    f = tmp_path / "a.md"
    f.write_text("# Tiêu đề\n\nNội dung.\n", "utf-8")
    for e in _phan_tu(trich_xuat(f)):
        g = e["grounding"]
        assert g["kind"] in {"box", "path"}
        assert ("box" in g) or ("path" in g), "phần tử không có neo nào"


def test_pdf_toa_do_luon_nam_trong_0_1(tmp_path):
    """Toạ độ phải chuẩn hoá [0,1] đúng quy ước ADE.

    Cùng một `box_to_pixels` phục vụ cả ADE lẫn nguồn cục bộ; trả pixel thô
    ở đây thì khung vẽ lệch, và nó lệch ÂM THẦM.
    """
    pymupdf = pytest.importorskip("pymupdf")
    f = tmp_path / "a.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Xin chao")
    doc.save(f)
    doc.close()

    pt = _phan_tu(trich_xuat(f))
    assert pt, "PDF có chữ mà không trích ra phần tử nào"
    for e in pt:
        b = e["grounding"]["box"]
        for k in ("xmin", "ymin", "xmax", "ymax"):
            assert 0.0 <= b[k] <= 1.0, f"{k}={b[k]} ngoài [0,1]"
        assert b["xmax"] > b["xmin"] and b["ymax"] > b["ymin"]


def test_pdf_scan_bao_can_ocr(tmp_path):
    """PDF không có lớp chữ phải tự nói ra, thay vì trả danh sách rỗng."""
    pymupdf = pytest.importorskip("pymupdf")
    f = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()          # trang trắng, không chữ
    doc.save(f)
    doc.close()
    assert trich_xuat(f)["meta"]["can_ocr"] is True
