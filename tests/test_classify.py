"""Test cho `classify` — phân loại nguồn theo TỪNG TRANG.

Vì sao phân loại theo trang, không theo tệp: một `.pdf` có thể là text thuần,
ảnh quét, hoặc lai cả hai. Phân loại sai ở bước đầu làm hỏng mọi bước sau —
trang quét bị xếp "born_digital" thì không ai OCR nó, và nội dung mất im lặng.

Ngưỡng ở đây ĐO TỪ 1 163 TRANG PDF THẬT, không phải đoán.
"""

import warnings

import pytest

warnings.filterwarnings("ignore")
import pymupdf  # noqa: E402

from ocr_lab.classify import (  # noqa: E402
    _IMAGE_DOMINANT_COVER,
    PageKind,
    SourceKind,
    classify_page,
    classify_pdf,
)


# ── fixture: dựng PDF thật bằng pymupdf, không dùng tệp mẫu ngoài ────────────

def _text_page(doc, body: str):
    pg = doc.new_page(width=595, height=842)          # A4
    pg.insert_text((72, 100), body, fontsize=11)
    return pg


def _image_page(doc, caption: str = "", cover: float = 1.0):
    """Trang chủ yếu là ẢNH, kèm chút chữ (chú thích/chữ ký số/số trang)."""
    pg = doc.new_page(width=595, height=842)
    w, h = 595 * cover, 842 * cover
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 560))
    pix.set_rect(pix.irect, (200, 200, 200))
    pg.insert_image(pymupdf.Rect(0, 0, w, h), pixmap=pix)
    if caption:
        pg.insert_text((72, 820), caption, fontsize=9)
    return pg


@pytest.fixture
def born_digital_pdf(tmp_path):
    doc = pymupdf.open()
    for _ in range(3):
        _text_page(doc, "Hợp đồng nguyên tắc. " * 40)
    p = tmp_path / "born.pdf"
    doc.save(p); doc.close()
    return p


@pytest.fixture
def scanned_pdf(tmp_path):
    doc = pymupdf.open()
    for _ in range(3):
        _image_page(doc)
    p = tmp_path / "scan.pdf"
    doc.save(p); doc.close()
    return p


@pytest.fixture
def hybrid_pdf(tmp_path):
    doc = pymupdf.open()
    _text_page(doc, "Đơn đăng ký nhãn hiệu. " * 40)
    _image_page(doc)
    _text_page(doc, "Phụ lục kèm theo. " * 40)
    p = tmp_path / "hybrid.pdf"
    doc.save(p); doc.close()
    return p


# ── phân loại từng trang ────────────────────────────────────────────────────

def test_a_text_heavy_page_is_born_digital(born_digital_pdf):
    doc = pymupdf.open(born_digital_pdf)
    assert classify_page(doc[0]).kind is PageKind.BORN_DIGITAL
    doc.close()


def test_a_page_with_no_text_layer_is_scanned(scanned_pdf):
    doc = pymupdf.open(scanned_pdf)
    assert classify_page(doc[0]).kind is PageKind.SCANNED
    doc.close()


def test_a_full_page_image_with_only_a_digital_signature_is_scanned(tmp_path):
    """CA THẬT, và là lý do ngưỡng "≥100 ký tự ⇒ born_digital" SAI.

    `NQ9001 sap nhap dia gioi hanh chinh.pdf` trang 1 có **148 ký tự** text
    layer — nhưng toàn bộ 148 ký tự đó chỉ là CHỮ KÝ SỐ:

        'Người ký: CỔNG THÔNG TIN ĐIỆN TỬ CHÍNH PHỦ
         Email: thongtinchinhphu@chinhphu.vn ...'

    Nội dung nghị quyết nằm trong ảnh phủ 100% trang. Theo ngưỡng đoán ban đầu
    (≥100 ⇒ born_digital) trang này bị xếp là văn bản số, KHÔNG được OCR, và
    toàn bộ nội dung mất im lặng — không lỗi, không cảnh báo.

    Tín hiệu quyết định phải là **ảnh phủ gần hết trang + chữ thưa**, không
    phải số ký tự đơn thuần.
    """
    doc = pymupdf.open()
    _image_page(doc, caption=(
        "Người ký: CỔNG THÔNG TIN ĐIỆN TỬ CHÍNH PHỦ "
        "Email: thongtinchinhphu@chinhphu.vn Cơ quan: Văn phòng Chính phủ"))
    p = tmp_path / "signed_scan.pdf"
    doc.save(p); doc.close()

    doc = pymupdf.open(p)
    r = classify_page(doc[0])
    assert r.kind is PageKind.SCANNED, (
        f"trang quét có chữ ký số bị xếp nhầm thành {r.kind}: {r.reason}")
    doc.close()


def test_a_figure_page_with_a_short_caption_is_scanned(tmp_path):
    """CA THẬT: `TV9011...huong dan chuan bi website` trang 5-8.

    Mỗi trang chỉ có 6 ký tự text (`Hình 2`, `Hình 3`…) và ảnh phủ ~55%. Nội
    dung hướng dẫn nằm trong ảnh chụp màn hình.
    """
    doc = pymupdf.open()
    _image_page(doc, caption="Hình 2", cover=0.75)
    p = tmp_path / "figure.pdf"
    doc.save(p); doc.close()

    doc = pymupdf.open(p)
    assert classify_page(doc[0]).kind is PageKind.SCANNED
    doc.close()


def test_a_nearly_empty_page_is_sparse_not_scanned(tmp_path):
    """Trang gần trống KHÔNG có ảnh thì không phải trang quét.

    Trang chỉ có `Page 4 of 4` mà không có ảnh thì OCR cũng chẳng thu được gì.
    Gọi nó là `SCANNED` khiến pipeline tốn công OCR một trang trắng, rồi báo
    "OCR thất bại" — nhiễu giả trong thống kê chất lượng.

    LƯU Ý VỀ MỘT CA THẬT DỄ NHẦM: `PRINCIPLE CONTRACT.pdf` trang 4 cũng chỉ có
    `'D\\nD\\nPage 4 of 4'`, nhưng nó CÓ một ảnh quét 2550×3300 phủ kín trang
    (độ lệch màu 3,5/255 — gần trắng, nhưng là bản quét thật của trang ký).
    Trang đó được xếp `SCANNED` là ĐÚNG: ta không thể biết ảnh trắng hay có
    chữ mờ nếu không OCR nó. Phân biệt nằm ở CÓ ẢNH hay không, không nằm ở số
    ký tự.
    """
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=842)
    pg.insert_text((72, 800), "Page 4 of 4", fontsize=9)
    p = tmp_path / "empty.pdf"
    doc.save(p); doc.close()

    doc = pymupdf.open(p)
    assert classify_page(doc[0]).kind is PageKind.SPARSE
    doc.close()


def test_a_screenshot_pasted_into_a_page_is_scanned(tmp_path):
    """Ảnh chụp màn hình dán vào PDF: KHÔNG chữ, ảnh phủ chưa tới nửa trang.

    CA THẬT bị bỏ sót, người dùng chỉ ra:
        `NH9001.US_Anh chup man hinh nhan hieu_011025.pdf` — 0 ký tự, ảnh 46%
        `NH9001.US_Tin nhan ket qua tra cuu_190925.pdf`    — 0 ký tự, ảnh 44%

    Cả hai bị xếp `SPARSE` ("trang gần trống") rồi định tuyến sang engine
    thường, nên toàn bộ chữ trong ảnh không bao giờ được đọc. Quét lại 234 PDF
    thật: **69 trang** cùng dạng bị bỏ sót.

    Vì sao lọt: ảnh chụp màn hình điện thoại dán vào khổ A4 thì tỉ lệ khác
    nhau, ảnh chỉ phủ 40–47% — dưới ngưỡng `_IMAGE_DOMINANT_COVER` (50%) vốn
    được hiệu chỉnh cho ca "trang quét kèm chữ ký số". Rơi tiếp xuống nhánh
    `chars < _SPARSE_CHARS` và bị gọi là gần trống, dù trang có hẳn một tấm
    ảnh.

    Nguyên tắc phân biệt đã được phát biểu đúng ở
    `test_a_nearly_empty_page_is_sparse_not_scanned`: *"Phân biệt nằm ở CÓ ẢNH
    hay không, không nằm ở số ký tự."* Trang KHÔNG một ký tự nào mà có ảnh thật
    thì mọi nội dung chỉ có thể nằm trong ảnh.
    """
    doc = pymupdf.open()
    _image_page(doc, cover=0.68)        # 0,68² ≈ 46% diện tích — đúng ca thật
    p = tmp_path / "screenshot.pdf"
    doc.save(p); doc.close()

    doc = pymupdf.open(p)
    kq = classify_page(doc[0])
    assert kq.chars == 0, "ca này phải là trang không có lớp text"
    assert kq.image_cover < _IMAGE_DOMINANT_COVER, (
        "ca này phải nằm DƯỚI ngưỡng ảnh-lấn-át, nếu không thì test không "
        "kiểm đúng lỗ hổng")
    assert kq.kind is PageKind.SCANNED
    doc.close()


def test_a_truly_empty_page_stays_sparse(tmp_path):
    """Hàng rào cho bản sửa trên: không ảnh, không chữ thì vẫn là gần trống.

    Nếu bản sửa nới rộng thành "cứ 0 ký tự là SCANNED" thì trang trắng thật sẽ
    bị đẩy qua OCR, sinh "OCR thất bại" giả trong thống kê chất lượng.
    """
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)          # trắng hoàn toàn
    p = tmp_path / "trang_trang.pdf"
    doc.save(p); doc.close()

    doc = pymupdf.open(p)
    assert classify_page(doc[0]).kind is PageKind.SPARSE
    doc.close()


def test_a_decorative_hairline_does_not_make_a_page_scanned(tmp_path):
    """Hàng rào phía kia: trang trắng có mỗi đường kẻ mảnh vẫn là SPARSE.

    CA THẬT đã kết xuất ra ảnh và xem bằng mắt: `NH9002.US. Non-Final Office
    Action` trang 17 — ảnh 1717×4 px, phủ 0,14% trang, nhìn ra là một đường kẻ
    mờ trên nền trắng, không có chữ nào.

    Đối chiếu với trang 48 cùng tệp (ảnh 1717×70, phủ 2,45%) thì lại CÓ chữ đọc
    được (dòng bản quyền, logo thanh toán) — nên ngưỡng phải nằm giữa hai mốc
    này, và `_MIN_REAL_IMAGE_COVER` đặt 1%.
    """
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=842)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 2))
    pix.set_rect(pix.irect, (120, 120, 120))
    pg.insert_image(pymupdf.Rect(40, 60, 555, 62), pixmap=pix)   # ~0,2% trang
    p = tmp_path / "hairline.pdf"
    doc.save(p); doc.close()

    doc = pymupdf.open(p)
    kq = classify_page(doc[0])
    assert kq.image_cover < 0.01, "ca này phải nằm dưới ngưỡng ảnh-thật"
    assert kq.kind is PageKind.SPARSE
    doc.close()


def test_a_blank_looking_scan_is_still_scanned(tmp_path):
    """Ảnh quét trông trắng vẫn phải OCR — ta chưa biết nó trắng thật không.

    Ca thật `PRINCIPLE CONTRACT.pdf` trang 4: ảnh 2550×3300 px, độ lệch màu
    chỉ 3,5/255. Nhìn thì trắng, nhưng chữ ký mờ hoặc dấu mộc nhạt cũng cho độ
    lệch thấp như vậy. Bỏ qua nó là đánh cược rằng trang ký không có gì.
    """
    doc = pymupdf.open()
    _image_page(doc, caption="D D Page 4 of 4")
    p = tmp_path / "blankish_scan.pdf"
    doc.save(p); doc.close()

    doc = pymupdf.open(p)
    assert classify_page(doc[0]).kind is PageKind.SCANNED
    doc.close()


def test_a_text_rich_page_with_a_large_banner_image_is_born_digital(tmp_path):
    """DƯƠNG TÍNH GIẢ tìm được khi kiểm chéo trên 300 PDF thật.

    `Ty gia VCB_*.pdf` trang 1 (6 tệp cùng dạng): **456 ký tự đọc tốt**
    (`'Chuyển đổi ngoại tệ Mua tiền mặt Mua chuyển khoản…'`) nhưng ảnh phủ 67%
    — trang web tỷ giá in ra PDF, ảnh là banner/biểu đồ, chữ là nội dung thật.

    Ngưỡng cũ `_TEXT_WINS_OVER_IMAGE_CHARS = 600` quá cao nên trang này bị gọi
    `SCANNED`. Hậu quả không phải mất dữ liệu (OCR vẫn đọc được) mà là **lãng
    phí**: OCR lại một trang đã có text hoàn hảo, và OCR ảnh biểu đồ thì kết
    quả tệ hơn text gốc.

    Ranh giới thật nằm giữa 148 ký tự (chữ ký số trên bản quét — phải OCR) và
    456 ký tự (nội dung thật — không OCR). Ngưỡng 300 nằm giữa hai ca thật.
    """
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=842)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 400))
    pix.set_rect(pix.irect, (180, 180, 180))
    pg.insert_image(pymupdf.Rect(0, 0, 595, 560), pixmap=pix)   # phủ ~67%
    pg.insert_textbox(pymupdf.Rect(30, 580, 565, 820),
                      "Chuyển đổi ngoại tệ Mua tiền mặt Mua chuyển khoản "
                      "Bán Mã ngoại tệ Tên ngoại tệ Đô la Mỹ Euro Yên Nhật "
                      "Bảng Anh Đô la Úc Đô la Canada Franc Thụy Sĩ " * 3,
                      fontsize=7)
    p = tmp_path / "tygia.pdf"
    doc.save(p); doc.close()

    doc = pymupdf.open(p)
    r = classify_page(doc[0])
    assert r.kind is PageKind.BORN_DIGITAL, (
        f"trang nhiều chữ + banner bị xếp nhầm thành {r.kind}: {r.reason}")
    doc.close()


def test_the_digital_signature_case_still_wins_over_the_new_threshold(tmp_path):
    """Hạ ngưỡng cho ca "Tỷ giá" KHÔNG được làm hỏng ca "chữ ký số".

    Hai ca kéo ngược chiều nhau:
        148 ký tự + ảnh 100%  → SCANNED  (nội dung trong ảnh)
        456 ký tự + ảnh  67%  → BORN_DIGITAL (nội dung là chữ)
    Test này khoá đầu thấp để lần chỉnh ngưỡng sau không âm thầm phá nó.
    """
    doc = pymupdf.open()
    _image_page(doc, caption=(
        "Người ký: CỔNG THÔNG TIN ĐIỆN TỬ CHÍNH PHỦ "
        "Email: thongtinchinhphu@chinhphu.vn Cơ quan: Văn phòng Chính phủ"))
    p = tmp_path / "sig.pdf"
    doc.save(p); doc.close()

    doc = pymupdf.open(p)
    assert classify_page(doc[0]).kind is PageKind.SCANNED
    doc.close()


# ── phân loại cả tệp ────────────────────────────────────────────────────────

def test_a_pdf_of_only_text_pages_is_born_digital(born_digital_pdf):
    r = classify_pdf(born_digital_pdf)
    assert r.kind is SourceKind.BORN_DIGITAL_PDF
    assert len(r.pages) == 3


def test_a_pdf_of_only_image_pages_is_scanned(scanned_pdf):
    assert classify_pdf(scanned_pdf).kind is SourceKind.SCANNED_PDF


def test_a_mixed_pdf_is_hybrid_and_keeps_per_page_detail(hybrid_pdf):
    """Tệp lai phải giữ chi tiết TỪNG TRANG, không chỉ một nhãn chung.

    Gọi cả tệp là "lai" rồi OCR sạch mọi trang là lãng phí; bỏ OCR mọi trang
    là mất nội dung. Bước định tuyến cần biết chính xác trang nào cần gì.
    """
    r = classify_pdf(hybrid_pdf)
    assert r.kind is SourceKind.HYBRID_PDF
    kinds = [p.kind for p in r.pages]
    assert kinds[0] is PageKind.BORN_DIGITAL
    assert kinds[1] is PageKind.SCANNED
    assert kinds[2] is PageKind.BORN_DIGITAL


def test_pages_needing_ocr_are_listed_explicitly(hybrid_pdf):
    """`pages_needing_ocr` là thứ bước định tuyến thực sự dùng."""
    r = classify_pdf(hybrid_pdf)
    assert r.pages_needing_ocr == [1], "chỉ trang giữa (chỉ số 1) cần OCR"


def test_an_image_file_is_classified_without_opening_it_as_pdf(tmp_path):
    """Ảnh rời (.jpg/.png) — nơi 100% lỗi OCR của ta đang nằm."""
    img = tmp_path / "cccd.jpg"
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 800, 600))
    pix.set_rect(pix.irect, (128, 128, 128))
    pix.save(img)

    r = classify_pdf(img)
    assert r.kind is SourceKind.IMAGE
    assert r.pages_needing_ocr == [0]


def test_a_corrupt_file_is_reported_not_crashed(tmp_path):
    """Tệp hỏng phải báo `UNREADABLE`, không được ném ngoại lệ.

    Một tệp hỏng giữa mẻ 566 tệp không được phép giết cả mẻ.
    """
    bad = tmp_path / "hong.pdf"
    bad.write_bytes(b"%PDF-1.4 rac khong phai pdf that")
    r = classify_pdf(bad)
    assert r.kind is SourceKind.UNREADABLE
    assert r.error
