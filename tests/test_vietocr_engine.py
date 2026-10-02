"""VietOCR engine: những bẫy đã gặp thật, khoá lại bằng test."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_pillow10_co_hang_so_ANTIALIAS():
    """vietocr gọi `Image.ANTIALIAS`, bị bỏ từ Pillow 10.

    Đã hỏng thật và hỏng theo kiểu tệ nhất: MỌI lượt đọc dòng ném
    AttributeError, vòng gọi có `except` nuốt hết, engine trả về 0 dòng —
    trông y hệt "trang này không có chữ".
    """
    from ocr_lab.engines.vietocr_engine import _va_pillow10
    _va_pillow10()
    from PIL import Image
    assert hasattr(Image, "ANTIALIAS")


def test_doc_anh_khong_nuot_loi_im_lang():
    """Dò ra hộp mà đọc hỏng HẾT thì phải ném, không trả danh sách rỗng.

    Trả rỗng là nói dối: trang có chữ, chỉ là bộ đọc không chạy. Đây chính
    là cái làm mất một vòng gỡ lỗi.
    """
    import inspect
    from ocr_lab.engines.vietocr_engine import VietOcrEngine
    src = inspect.getsource(VietOcrEngine.doc_anh)
    assert "self.loi_doc += 1" in src, "lỗi đọc dòng không được đếm"
    assert "raise RuntimeError" in src, "đọc hỏng hết vẫn trả rỗng im lặng"


def test_sap_theo_thu_tu_doc():
    """Hộp phải sắp trên→dưới, trái→phải.

    Bộ dò trả theo thứ tự PHÁT HIỆN. Không sắp thì văn bản xáo trộn và mọi
    phép so với ground truth đều sai — mà sai một cách trông rất giống
    "engine đọc kém".
    """
    import inspect
    from ocr_lab.engines.vietocr_engine import VietOcrEngine
    src = inspect.getsource(VietOcrEngine.doc_anh)
    assert "ra.sort(" in src and "ymin" in src and "xmin" in src


def test_hop_chuan_hoa_0_1():
    """Hộp trả về phải là phân số [0,1] — cùng quy ước ADE.

    Trả pixel thô thì `box_to_pixels` dùng chung sẽ vẽ lệch, và lệch âm thầm.
    """
    import inspect
    from ocr_lab.engines.vietocr_engine import VietOcrEngine
    src = inspect.getsource(VietOcrEngine.doc_anh)
    assert "x0 / W" in src and "y0 / H" in src


@pytest.mark.skipif(
    not (Path(__file__).parent.parent / "models" / "vgg_seq2seq.pth").is_file(),
    reason="chưa tải weights VietOCR")
def test_doc_duoc_anh_that(tmp_path):
    """Chạy thật trên một ảnh dựng tại chỗ — không đụng dữ liệu khách hàng."""
    pymupdf = pytest.importorskip("pymupdf")
    from ocr_lab.engines.vietocr_engine import VietOcrEngine

    f = tmp_path / "a.png"
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=200)
    page.insert_text((40, 90), "Cong hoa xa hoi chu nghia", fontsize=26)
    page.get_pixmap(dpi=150).save(f)
    doc.close()

    dong = VietOcrEngine().doc_anh(f)
    assert dong, "không đọc được dòng nào từ ảnh có chữ rõ"
    for d in dong:
        for k in ("xmin", "ymin", "xmax", "ymax"):
            assert 0.0 <= d.box[k] <= 1.0
