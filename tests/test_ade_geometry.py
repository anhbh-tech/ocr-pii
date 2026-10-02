"""Khoá phép đổi toạ độ ADE — chỗ sai âm thầm nhất của cả dự án.

VÌ SAO NHỮNG TEST NÀY VIẾT TRƯỚC
────────────────────────────────
Sai toạ độ không làm chương trình chết. Nó vẽ ra những khung trông hoàn toàn
hợp lý ở sai chỗ, và người soát — vốn tin vào công cụ — sẽ đọc chữ ở khung này
mà tưởng là của vùng kia. Một lỗi không có triệu chứng thì chỉ có test mới bắt
được.
"""

import pytest

from ocr_lab.ade_store import box_to_pixels


def test_box_chuan_hoa_nhan_voi_kich_thuoc_anh_da_render():
    # ADE trả phân số [0,1]; ảnh hiển thị 1000x1400 px.
    px = box_to_pixels({"xmin": 0.1, "ymin": 0.2, "xmax": 0.5, "ymax": 0.4},
                       width=1000, height=1400)
    assert px == (100, 280, 500, 560)


def test_box_thieu_truong_thi_bao_loi_chu_khong_coi_la_0():
    # Trường vắng nghĩa là ADE không ground được phần tử đó. Coi như 0 sẽ vẽ
    # một khung ở góc trên-trái trông y như một kết quả thật.
    with pytest.raises(ValueError, match="thiếu"):
        box_to_pixels({"xmin": 0.1, "ymin": 0.2}, width=1000, height=1400)


def test_box_ngoai_khoang_0_1_bi_tu_choi():
    # Dấu hiệu kinh điển của việc đọc nhầm cây `grounding` cũ, vốn dùng đơn vị
    # PIXEL và format [left, top, right, bottom].
    with pytest.raises(ValueError, match="ngoài khoảng"):
        box_to_pixels({"xmin": 12.0, "ymin": 40.0, "xmax": 300.0, "ymax": 90.0},
                      width=1000, height=1400)


def test_box_dao_nguoc_bi_tu_choi():
    # xmax < xmin cho ra chiều rộng ÂM. Canvas vẽ im lặng không báo gì, ra một
    # khung vô hình — phần tử biến mất khỏi overlay mà không ai biết tại sao.
    with pytest.raises(ValueError, match="đảo ngược"):
        box_to_pixels({"xmin": 0.8, "ymin": 0.2, "xmax": 0.3, "ymax": 0.4},
                      width=1000, height=1400)


def test_box_sat_bien_van_hop_le():
    # Phần tử tràn sát mép trang là chuyện thường (header, footer, ảnh nền).
    # 0.0 và 1.0 phải đi qua được, nếu không ta gạt nhầm dữ liệu đúng.
    assert box_to_pixels({"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0},
                         width=800, height=600) == (0, 0, 800, 600)
