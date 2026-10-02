"""Chấm OCR với ground truth từ VLM — hai bên không cùng loại."""
from __future__ import annotations

from ocr_lab.vlm_scoring import bo_phan_vlm, cham, gop, tu_co_nghia


def test_bo_mo_ta_vlm():
    """`<description>` là VLM nói VỀ bức ảnh, không phải chữ TRÊN ảnh.

    Đo trên kho thật: 80% markdown thô của Pro là khối này. Không bỏ thì
    mọi bộ OCR bị tính sai trên toàn bộ phần đó, và CER ra 0,89-0,96 cho
    cả ba engine — con số nói về phép đo, không nói về engine.
    """
    md = ('<figure type="ILLUSTRATION">\n<description>A stylized logo with '
          'three bars</description></figure>\n\nZLATKIN\n<!-- doc_id=abc -->')
    assert bo_phan_vlm(md) == "ZLATKIN"


def test_bo_nhan_tuong_trung():
    """`[SEARCH_ICON]` là biểu tượng VLM đặt tên, OCR không sinh ra được."""
    assert "search_icon" not in tu_co_nghia(
        bo_phan_vlm("Home [SEARCH_ICON] [CART_ICON] Catalog"))


def test_emoji_khong_tinh_la_tu():
    """Engine không bị phạt vì thiếu emoji — nó không phải chữ."""
    t = tu_co_nghia("⭐⭐⭐⭐⭐ 4.8 🚚 Get it")
    assert "4.8" in t and "get" in t
    assert not any(any(ord(c) > 0x2500 for c in w) for w in t)


def test_thu_hoi_va_do_sach_tach_roi():
    """Đọc THIẾU và BỊA THÊM là hai lỗi khác hẳn nhau về mức nghiêm trọng.

    CER gộp chúng thành một con số. Ở đây tách: thu hồi bắt bỏ sót, độ sạch
    bắt bịa chữ — mà bịa là kiểu hỏng nguy hiểm vì bản chép vẫn trôi chảy.
    """
    k = cham("alpha beta gamma delta", "alpha beta omega")
    assert k["thu_hoi"] == 0.5          # 2/4 từ chuẩn đọc được
    assert round(k["do_sach"], 3) == round(2 / 3, 3)   # 1/3 từ trả về là bịa
    assert "omega" in k["bia_them"]
    assert "gamma" in k["thieu"]


def test_ma_so_dem_rieng():
    """Mã số là cổng quyết định — phải đếm tách khỏi từ thường."""
    k = cham("Hợp đồng NH9004/2025 ngày 17", "Hop dong NH9004/2025 ngay 17")
    assert k["ma_so_chuan"] >= 1
    assert k["ma_so_giu"] == k["ma_so_chuan"]


def test_gop_cong_tu_so_mau_so_khong_trung_binh_ti_le():
    """Ảnh 3 từ và ảnh 300 từ không được đóng góp ngang nhau.

    Lấy trung bình của các tỉ lệ cho một ảnh tí hon trọng số bằng một ảnh
    dày đặc chữ, và con số tổng sẽ do những ảnh ít chữ nhất quyết định.
    """
    nho = {"tu_chuan": 2, "tu_doc": 2, "tu_trung": 2,
           "ma_so_chuan": 0, "ma_so_giu": 0}
    lon = {"tu_chuan": 100, "tu_doc": 100, "tu_trung": 50,
           "ma_so_chuan": 0, "ma_so_giu": 0}
    g = gop([nho, lon])
    # Trung bình tỉ lệ sẽ là (1.0 + 0.5)/2 = 0.75; đúng phải là 52/102.
    assert g["thu_hoi"] == round(52 / 102, 3)


def test_nfc_truoc_khi_tach_tu():
    """macOS trả NFD; `ký` NFD khác `ký` NFC theo từng byte."""
    import unicodedata
    nfc = unicodedata.normalize("NFC", "ký hiệu")
    nfd = unicodedata.normalize("NFD", "ký hiệu")
    assert tu_co_nghia(nfc) == tu_co_nghia(nfd)
