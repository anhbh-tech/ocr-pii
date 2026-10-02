"""Nhận ra nội dung thật nằm trong ảnh trên trang "digital".

Những test này khoá lại các ca ĐO ĐƯỢC trên kho thật, không phải ca tưởng
tượng: 312 trang digital, 32 trang có chữ trong ảnh, và hai nhóm hành xử
hoàn toàn khác nhau bên trong 32 trang đó.
"""

from ocr_lab.image_text import (
    ImageTextFinding, chuan_hoa, danh_gia_trang, loc_chan_trang,
)


# ── ca thật: nội dung nằm trong ảnh ─────────────────────────────────────

def test_noi_dung_that_trong_anh_thi_dang_ocr():
    # NH9001.US_Filing Receipt tr5: lớp text chỉ 175 ký tự (~35 từ), ảnh
    # chứa 73 từ mới ⇒ nội dung THẬT nằm trong ảnh.
    text = " ".join(f"tu{i}" for i in range(35))
    anh = text + " " + " ".join(f"moi{i}" for i in range(73))
    f = danh_gia_trang(text, anh)
    assert f.dang_ocr
    assert "nội dung thật" in f.ly_do


def test_chan_trang_thi_khong_dang_ocr():
    # TV9011: 969 ký tự text (~190 từ) nhưng chỉ 30 từ trong ảnh — đó là
    # logo + địa chỉ công ty, OCR nó tốn tiền để lấy về thứ đã biết.
    text = " ".join(f"tu{i}" for i in range(190))
    anh = text + " " + " ".join(f"diachi{i}" for i in range(20))
    f = danh_gia_trang(text, anh)
    assert not f.dang_ocr
    assert "chân trang" in f.ly_do


def test_nhieu_tu_logo_bi_bo_qua():
    # Vision hay đọc ra vài ký tự vô nghĩa từ hoa văn / con dấu.
    f = danh_gia_trang("một hai ba bốn năm", "một hai ba bốn năm xy")
    assert not f.dang_ocr
    assert "nhiễu" in f.ly_do


# ── lọc khung trang theo cả tệp ─────────────────────────────────────────

def _f(page, tu, n_text=100):
    return ImageTextFinding(page, len(tu), n_text, tu, True, "")


def test_tu_lap_tren_moi_trang_bi_coi_la_khung_trang():
    # Địa chỉ công ty xuất hiện y hệt ở cả 5 trang.
    chan = ["hanoi", "0243", "refinylaw", "com", "district"] * 1
    fs = [_f(i, list(chan)) for i in range(1, 6)]
    ra = loc_chan_trang(fs)
    assert all(not f.dang_ocr for f in ra)
    assert "khung trang" in ra[0].ly_do


def test_HAI_trang_giong_nhau_KHONG_bi_coi_la_khung_trang():
    """Ca đã sai thật một lần.

    `Filing Receipt` chỉ có 2 trang nghi ngờ, nội dung gần giống nhau, và
    bộ lọc bản đầu (ngưỡng `max(2, …)`) coi cả 73 từ nội dung là chân trang
    rồi loại oan. Khung trang chỉ nhận ra được khi có đủ trang để thấy nó
    LẶP — dưới 3 trang thì không kết luận.
    """
    tu = [f"noidung{i}" for i in range(40)]
    fs = [_f(5, list(tu), n_text=35), _f(6, list(tu), n_text=20)]
    ra = loc_chan_trang(fs)
    assert all(f.dang_ocr for f in ra)


def test_trang_co_noi_dung_rieng_van_duoc_giu_sau_khi_loc():
    chung = ["hanoi", "0243", "refinylaw"]
    fs = [_f(i, list(chung)) for i in range(1, 5)]
    fs.append(_f(5, chung + [f"rieng{i}" for i in range(30)], n_text=60))
    ra = loc_chan_trang(fs)
    assert not ra[0].dang_ocr          # trang chỉ có chân trang
    assert ra[-1].dang_ocr             # trang có nội dung riêng


# ── chuẩn hoá ───────────────────────────────────────────────────────────

def test_NFD_va_NFC_duoc_coi_la_mot():
    """macOS trả chuỗi NFD. Không chuẩn hoá thì MỌI từ có dấu đều bị coi là
    'mới', và trang nào cũng báo có chữ trong ảnh."""
    import unicodedata as ud
    nfc = "ký đăng"
    nfd = ud.normalize("NFD", nfc)
    assert nfc != nfd                       # khác nhau theo byte
    assert chuan_hoa(nfc) == chuan_hoa(nfd)  # nhưng cùng một tập từ


def test_bo_qua_khac_biet_hoa_thuong_va_dau_cau():
    assert chuan_hoa("Hà Nội, Việt Nam.") == chuan_hoa("hà nội việt nam")


# ── khung trang dùng chung TRÊN TOÀN KHO ────────────────────────────────

def test_letterhead_chung_bi_bat_du_moi_tep_chi_co_1_trang():
    """Ca đã lọt qua bộ lọc theo tệp.

    `loc_chan_trang` nhìn trong MỘT tệp nên chỉ bắt được chân trang của tài
    liệu nhiều trang. Letterhead công ty thì nằm trên mọi tài liệu công ty
    phát hành — mỗi tệp chỉ đóng góp 1-2 trang nghi ngờ, dưới ngưỡng "lặp
    lại", nên lọt hết.

    Đo thật: 32 trang nghi ngờ thuộc 21 tệp; địa chỉ công ty ("9th floor ·
    Prime Centre · 53 Trung Hoa · Ha Noi") xuất hiện ở 17 trang mà không tệp
    nào đủ 3 trang để bộ lọc theo tệp nhận ra. Bỏ sót = trả tiền OCR cho 19
    trang để lấy về một dòng địa chỉ đã biết.
    """
    from ocr_lab.image_text import tim_khung_trang_toan_kho

    letterhead = ["9th", "floor", "prime", "centre", "hanoi"]
    # 10 trang từ 10 TỆP khác nhau, mỗi trang chỉ có letterhead + 1 từ riêng
    trang = [letterhead + [f"rieng{i}"] for i in range(10)]
    khung = tim_khung_trang_toan_kho(trang)
    assert set(letterhead) <= khung
    assert not any(w.startswith("rieng") for w in khung)


def test_tu_rieng_cua_mot_tai_lieu_khong_bi_coi_la_khung():
    from ocr_lab.image_text import tim_khung_trang_toan_kho

    trang = [[f"noidung{i}_{j}" for j in range(8)] for i in range(10)]
    assert tim_khung_trang_toan_kho(trang) == set()


def test_danh_gia_lai_loai_trang_chi_co_letterhead():
    from ocr_lab.image_text import danh_gia_lai

    khung = {"9th", "floor", "prime", "centre", "hanoi"}
    f = ImageTextFinding(1, 6, 200, list(khung) + ["ten"], True, "")
    assert not danh_gia_lai(f, khung).dang_ocr


def test_danh_gia_lai_giu_trang_co_noi_dung_that():
    # Filing Receipt tr5: 73 từ nội dung trên 35 từ lớp text.
    from ocr_lab.image_text import danh_gia_lai

    khung = {"9th", "floor", "prime"}
    tu = list(khung) + [f"noidung{i}" for i in range(70)]
    f = ImageTextFinding(5, len(tu), 35, tu, True, "")
    assert danh_gia_lai(f, khung).dang_ocr


def test_kho_qua_nho_thi_khong_ket_luan():
    """Dưới 4 trang thì không đủ bằng chứng để gọi cái gì là 'dùng chung'."""
    from ocr_lab.image_text import tim_khung_trang_toan_kho

    assert tim_khung_trang_toan_kho([["a", "b"], ["a", "b"]]) == set()
