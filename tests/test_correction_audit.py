"""Phân loại thay đổi của corrector.

Những test này tồn tại vì một kết luận SAI đã suýt được chốt: `accent_share`
báo 0,241 → 0,240 ("không cải thiện") trong khi model đang sửa `điện tứ` →
`điện tử` hoàn toàn đúng. Thước đo đếm SỐ LƯỢNG dấu thì mù với lỗi SAI dấu.
"""

from ocr_lab.correction_audit import (
    ChangeKind, classify_change, diff_words, strip_tone,
)


# ── ca đã suýt bị bỏ sót ────────────────────────────────────────────────

def test_sua_thanh_dieu_duoc_nhan_ra():
    # Đây là ca người dùng chỉ ra. accent_share cho chênh lệch ĐÚNG BẰNG 0.
    #
    # Model vừa sửa `tứ`→`tử` vừa xoá ký tự nhiễu `<`, nên nhãn trội là
    # CHAR_EDIT — nhưng `is_improvement` vẫn phải là True. Đây chính là chỗ
    # bản đầu sai: gán một nhãn duy nhất rồi kết luận theo nhãn đó đã giấu
    # mất phần model làm đúng.
    c = classify_change("< Căn cước điện tứ", " Căn cước điện tử")
    assert c.n_tone == 1
    assert c.is_improvement


def test_sua_thanh_dieu_thuan_tuy():
    c = classify_change("Căn cước điện tứ", "Căn cước điện tử")
    assert c.kind is ChangeKind.TONE_FIX
    assert c.n_tone == 1 and c.n_char == 0


def test_accent_share_mu_voi_ca_nay():
    # Khoá lại chính lý do phải có module này: thước đo cũ không phân biệt
    # được, nên không được dùng nó để kết luận corrector vô dụng.
    from ocr_lab.metrics import accent_share
    assert accent_share("Căn cước điện tứ") == accent_share("Căn cước điện tử")


# ── phân biệt ba loại ───────────────────────────────────────────────────

def test_nuot_xuong_dong_bi_bao_la_thiet_hai():
    # Trên biểu mẫu, xuống dòng phân tách các TRƯỜNG. Nuốt nó là mất ranh
    # giới trường, không phải dọn dẹp.
    c = classify_change("[STAMPED]\nBỘ CÔNG AN\nCỤC CẢNH SÁT",
                        "[STAMPED] BỘ CÔNG AN CỤC CẢNH SÁT")
    assert c.damages_structure
    assert not c.is_improvement          # không sửa được thanh điệu nào


def test_vua_sua_dau_vua_nuot_dong_thi_bao_CA_HAI():
    # Thay đổi hỗn hợp phải giữ được cả hai mặt: có cải thiện VÀ có thiệt hại.
    # Một nhãn duy nhất buộc phải vứt đi một trong hai.
    c = classify_change("điện tứ\nBỘ CÔNG AN", "điện tử BỘ CÔNG AN")
    assert c.is_improvement          # sửa được tứ -> tử
    assert c.damages_structure       # nhưng nuốt mất xuống dòng


def test_xoa_ky_tu_la_loai_rieng():
    c = classify_change(".all 4G ▪", ".all 4G ")
    assert c.kind is ChangeKind.CHAR_EDIT
    # Không tự kết luận tốt/xấu: phải xem bằng mắt.
    assert not c.is_improvement


def test_khong_doi_thi_bao_khong_doi():
    assert classify_change("y nguyên", "y nguyên").kind is ChangeKind.NONE


# ── ground truth người dùng chỉ ra, trên dữ liệu CCCD thật ──────────────

def test_rac_OCR_duoc_coi_la_thanh_dieu_doc_nham():
    # Tiếng Việt KHÔNG có ogonek (U+0328) hay chấm-trên (U+0307). Khi OCR
    # sinh ra chúng thì đó là dấu thanh bị đọc sai, không phải chữ khác.
    #
    #   'Sęo' ogonek     ← đọc nhầm của 'Sẹo' (nặng)
    #   'thė' chấm-trên  ← đọc nhầm của 'thẻ' (hỏi)
    assert strip_tone("Sęo") == strip_tone("Sẹo") == "Seo"
    assert strip_tone("thė") == strip_tone("thẻ") == "the"


def test_the_la_sua_thanh_dieu_dung_khong_phai_doi_chu():
    # Bản trước xếp nhầm ca này thành "đổi chữ" nên đếm THIẾU số lần model
    # làm đúng.
    c = classify_change("thė", "thẻ")
    assert c.kind is ChangeKind.TONE_FIX
    assert c.is_improvement


def test_Seo_thanh_Sao_la_SAI_phai_bi_xep_vao_doi_chu():
    # Người dùng chỉ ra: 'Sęo' phải sửa thành 'Sẹo', không phải 'Sao'.
    # Model đổi nguyên âm ⇒ khác khung xương ⇒ CHAR_EDIT ⇒ bị chặn.
    c = classify_change("Sęo chấm đuôi", "Sao chấm đuôi")
    assert c.kind is ChangeKind.CHAR_EDIT
    assert not c.is_improvement


def test_Seo_thanh_Seo_dung_thi_duoc_nhan():
    c = classify_change("Sęo chấm đuôi", "Sẹo chấm đuôi")
    assert c.kind is ChangeKind.TONE_FIX
    assert c.is_improvement


def test_zen_trong_dia_chi_khong_duoc_doi_thanh_tren():
    # 'căn hộ số ZA0310 tòa zen dự án Feliz Homes' — Zen là TÊN TOÀ NHÀ.
    # Đổi thành 'trên' là phá địa chỉ. Khác khung xương ⇒ CHAR_EDIT ⇒ chặn.
    c = classify_change("tòa zen dự án", "tòa trên dự án")
    assert c.kind is ChangeKind.CHAR_EDIT
    assert not c.is_improvement


def test_bia_them_chu_la_doi_chu():
    # 'Sex:' → 'SexV:' — model bịa thêm ký tự.
    c = classify_change("Sex:", "SexV:")
    assert c.kind is ChangeKind.CHAR_EDIT
    assert not c.is_improvement


# ── strip_tone: thanh điệu vs dấu tạo chữ cái ───────────────────────────

def test_bo_dau_thanh_giu_dau_tao_chu_cai():
    # `tứ` và `tử` cùng khung xương `tư` — chỉ khác thanh điệu.
    assert strip_tone("tứ") == strip_tone("tử")


def test_mu_va_moc_KHONG_bi_coi_la_thanh_dieu():
    # `tư` và `tu` là hai chữ KHÁC NHAU. Nếu strip_tone bỏ luôn móc thì
    # "đổi chữ" sẽ bị xếp nhầm thành "sửa thanh điệu" và ta mất khả năng
    # phát hiện model viết lại chữ.
    assert strip_tone("tư") != strip_tone("tu")
    assert strip_tone("â") != strip_tone("a")


def test_doi_chu_that_van_la_char_edit():
    # Đổi `cước` thành `cuộc` là đổi chữ, không phải sửa dấu.
    c = classify_change("Căn cước công dân", "Căn cuộc công dân")
    assert c.kind is ChangeKind.CHAR_EDIT


# ── diff_words ──────────────────────────────────────────────────────────

def test_diff_chi_ra_dung_tu_da_doi():
    # Báo cáo phải chỉ thẳng vào `tứ → tử`, không bắt đọc lại cả câu.
    pairs = diff_words("Căn cước điện tứ hôm nay", "Căn cước điện tử hôm nay")
    assert pairs == [("tứ", "tử")]


def test_diff_bat_duoc_nhieu_cho_doi():
    pairs = diff_words("mot hai ba bon", "một hai bà bốn")
    assert ("mot", "một") in pairs
    assert len(pairs) >= 2


# ── lớp lọc: chỉ nhận sửa dấu, chặn viết lại chữ ────────────────────────

def test_loc_giu_sua_dau_chan_doi_chu():
    from ocr_lab.correction_audit import filter_to_tone_fixes as f
    # 'Sęo'->'Sao' bị chặn (đổi nguyên âm), phần còn lại giữ nguyên.
    assert f("Sęo chấm đuôi", "Sao chấm đuôi") == "Sęo chấm đuôi"


def test_loc_giu_nguyen_ten_rieng_trong_dia_chi():
    from ocr_lab.correction_audit import filter_to_tone_fixes as f
    got = f("tòa zen dự án Feliz", "tòa trên dự án Feliz")
    assert "zen" in got and "trên" not in got


def test_loc_khoi_phuc_xuong_dong():
    from ocr_lab.correction_audit import filter_to_tone_fixes as f
    got = f("[STAMPED]\nBỘ CÔNG AN\nCỤC", "[STAMPED] BỘ CÔNG AN CỤC")
    assert got.count("\n") == 2


# ── hai chế độ lọc, theo tình trạng dấu của văn bản ─────────────────────

def test_mat_dau_hoan_toan_can_restore_all():
    """Đầu ra tesseract mất cả mũ lẫn thanh: 'Noi' -> 'Nơi' cần thêm móc.

    Chế độ mặc định cố ý chặn việc thêm móc (để `tư` != `tu` bảo vệ văn bản
    đã có dấu), nên nó chặn nhầm ở đây. Hai bài toán, hai thước.
    """
    from ocr_lab.correction_audit import filter_to_tone_fixes as f
    b, a = "Noi thuong tru tai xa Hu Cau", "Nơi thường trú tại xã Hư Cấu"
    assert f(b, a) != a                        # mặc định: chặn bớt
    assert f(b, a, restore_all=True) == a      # restore_all: nhận hết


def test_ten_rieng_duoc_bao_ve_trong_CA_HAI_che_do():
    """'tòa zen dự án Feliz Homes' — Zen là tên toà nhà.

    Nới lỏng sang restore_all KHÔNG được phép mở đường cho model viết lại
    tên riêng, vì đó là ca phá địa chỉ trên hồ sơ pháp lý.
    """
    from ocr_lab.correction_audit import filter_to_tone_fixes as f
    for mode in (False, True):
        assert "zen" in f("tòa zen dự án", "tòa trên dự án", restore_all=mode)


def test_strip_all_marks_bo_ca_mu_va_moc():
    from ocr_lab.correction_audit import strip_all_marks as s
    assert s("Nơi") == s("Noi") == "Noi"
    assert s("tư") == s("tu") == "tu"
