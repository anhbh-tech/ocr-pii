"""Kiểm bộ đo bằng những cặp chuỗi ĐÃ BIẾT ĐÁP ÁN.

Tệp này quan trọng hơn vẻ ngoài của nó. Bộ đo là thứ duy nhất ta dùng để nói
engine nào tốt hơn engine nào. Nếu nó sai, mọi kết luận về sau đều sai — và
cái sai đó không lộ ra: nó vẫn cho ra những con số trông hợp lý, vẫn xếp hạng
được, chỉ là xếp nhầm.

Nên mỗi test ở đây có đáp án tính được BẰNG TAY, viết rõ trong docstring.
"""

import unicodedata as ud

import pytest

from ocr_lab.metrics import (
    accent_share,
    canonical_vi,
    cer,
    identifier_preservation,
    identifiers,
    levenshtein,
    normalize_for_compare,
    one_minus_edit_distance,
    score,
    stroke_letter_share,
    wer,
    _levenshtein_py,
)


# ── khoảng cách sửa ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("a, b, expected", [
    ("", "", 0),
    ("abc", "abc", 0),
    ("abc", "", 3),            # xoá 3
    ("", "abc", 3),            # thêm 3
    ("kitten", "sitting", 3),  # ca kinh điển: k→s, e→i, thêm g
    ("flaw", "lawn", 2),       # xoá f, thêm n
])
def test_levenshtein_matches_hand_computed_answers(a, b, expected):
    assert levenshtein(a, b) == expected


def test_fast_backend_agrees_with_the_readable_reference_implementation():
    """rapidfuzz (C++) phải cho cùng kết quả với bản thuần Python.

    Ta dùng rapidfuzz cho nhanh, nhưng bản Python mới là bản đọc hiểu được.
    Test này canh chỗ nối: nếu rapidfuzz đổi hành vi ở phiên bản sau, hoặc ta
    hiểu sai API của nó, test đỏ ngay chứ không âm thầm cho số khác.
    """
    import random

    rng = random.Random(20260911)
    alphabet = "abcđêôơư 0123456789"
    for _ in range(200):
        a = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        b = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        assert levenshtein(a, b) == _levenshtein_py(a, b), (a, b)


def test_levenshtein_on_word_lists_counts_words_not_characters():
    """Truyền list ⇒ đếm theo phần tử. Đây là cách `wer` dùng nó."""
    assert levenshtein(["xin", "chào", "bạn"], ["xin", "chao", "bạn"]) == 1


# ── bẫy Unicode 1: NFC và NFD ───────────────────────────────────────────────

def test_the_same_word_in_nfc_and_nfd_scores_zero_error():
    """"Điều" viết NFC và NFD là CÙNG MỘT TỪ — CER phải bằng 0.

    Không chuẩn hoá thì so byte sẽ thấy độ dài khác nhau và báo sai gần hết.
    Đây là bẫy hay gặp nhất khi ghép ground truth của bên khác với đầu ra của
    engine của mình.
    """
    nfc_form = ud.normalize("NFC", "Điều 56 quy định")
    nfd_form = ud.normalize("NFD", "Điều 56 quy định")

    assert nfc_form != nfd_form, "hai dạng phải khác nhau ở mức byte"
    assert len(nfd_form) > len(nfc_form), "NFD phải dài hơn"
    assert cer(nfc_form, nfd_form) == 0.0
    assert one_minus_edit_distance(nfc_form, nfd_form) == 1.0


# ── bẫy Unicode 2: vị trí dấu thanh ─────────────────────────────────────────

@pytest.mark.parametrize("old_style, new_style", [
    ("hòa", "hoà"),
    ("thủy", "thuỷ"),
    ("hóa", "hoá"),
    ("khỏe", "khoẻ"),
    ("tòa án", "toà án"),
])
def test_both_vietnamese_tone_placement_conventions_compare_equal(
        old_style, new_style):
    """"hòa" và "hoà" là cùng một từ, chỉ khác quy ước đặt dấu.

    Cả hai đều đúng chính tả. Ground truth gõ kiểu này mà engine xuất kiểu kia
    thì bị tính sai một ký tự mỗi âm tiết có dấu — với văn bản tiếng Việt đặc
    dấu, đủ để đảo thứ hạng giữa hai engine.
    """
    assert old_style != new_style, "hai kiểu phải khác nhau ở mức byte"
    assert canonical_vi(old_style) == canonical_vi(new_style)
    assert cer(old_style, new_style) == 0.0


def test_canonicalisation_does_not_erase_letter_forming_diacritics():
    """Mũ, trăng, móc là BỘ PHẬN CỦA CHỮ CÁI — không được di dời hay bỏ đi.

    "â" mất mũ thì thành "a", một chữ khác hẳn. Nếu `canonical_vi` gộp luôn
    những dấu này thì nó sẽ che mất lỗi thật của engine: engine đọc "cam" thay
    vì "câm" sẽ được chấm là đúng.
    """
    assert canonical_vi("ăn") != canonical_vi("an")
    assert canonical_vi("cân") != canonical_vi("can")
    assert canonical_vi("tư") != canonical_vi("tu")
    assert canonical_vi("cơm") != canonical_vi("com")
    assert cer("câm", "cam") > 0, "mất mũ là lỗi thật, phải bị tính"


def test_canonicalisation_still_distinguishes_different_tones():
    """Đổi dấu thanh là ĐỔI NGHĨA — phải bị tính là sai.

    "má" (mẹ) · "mà" (liên từ) · "mả" (mồ) là ba từ khác nhau. Nếu chuẩn hoá
    làm chúng bằng nhau thì ta đã xoá mất chính thứ cần đo.
    """
    for a, b in [("má", "mà"), ("mà", "mả"), ("mả", "mã"), ("mã", "mạ")]:
        assert canonical_vi(a) != canonical_vi(b), f"{a} và {b} phải khác nhau"
        assert cer(a, b) > 0


def test_dropping_a_tone_entirely_is_counted_as_an_error():
    """Mất dấu là lỗi — đây chính là lỗi chủ yếu của tesseract."""
    assert cer("Nghị định", "Nghi dinh") > 0.2


# ── bẫy Unicode 3: ký tự trông giống nhau ───────────────────────────────────

def test_typographic_lookalikes_are_not_counted_as_reading_errors():
    """Gạch nối en-dash và nháy cong: OCR đổi qua lại, người đọc không thấy khác."""
    assert cer("NĐ-CP “trích dẫn”", "NĐ\u2013CP \u201ctrích dẫn\u201d") == 0.0


def test_line_wrapping_differences_are_not_counted_as_reading_errors():
    """Ngắt dòng là trình bày, không phải đọc đúng hay sai.

    Engine ngắt dòng khác ground truth sẽ bị phạt như đọc sai chữ nếu ta không
    gộp khoảng trắng.
    """
    assert cer("Điều 1. Phạm vi\nđiều chỉnh",
               "Điều 1. Phạm vi điều   chỉnh") == 0.0
    assert normalize_for_compare("  a\n\nb\t c ") == "a b c"


# ── CER / WER ───────────────────────────────────────────────────────────────

def test_cer_equals_edits_divided_by_reference_length():
    """"abcde" → "abXde": 1 phép thay trên 5 ký tự = 0,2. Tính tay được."""
    assert cer("abcde", "abXde") == pytest.approx(0.2)


def test_cer_of_empty_output_is_total_failure():
    """Engine trả rỗng = đọc trượt hoàn toàn, không phải "không có lỗi"."""
    assert cer("Điều 56", "") == pytest.approx(1.0)


def test_cer_is_not_clamped_when_the_engine_hallucinates_extra_text():
    """Sinh thừa gấp nhiều lần phải cho CER > 1,0.

    Cắt về 1,0 sẽ làm một model ảo giác trông ngang bằng một model chỉ đọc
    trượt. Chúng không giống nhau: ảo giác nguy hiểm hơn vì văn bản bịa vẫn
    đọc trôi chảy.
    """
    assert cer("Điều 1", "Điều 1 " + "bịa thêm " * 20) > 1.0


def test_wer_counts_whole_words():
    """4 từ, sai 1 = 0,25."""
    assert wer("một hai ba bốn", "một hai XX bốn") == pytest.approx(0.25)


def test_wer_is_harsher_than_cer_for_a_single_letter_slip():
    """Sai một chữ cái hỏng cả từ. Hai chỉ số nhìn hai khía cạnh khác nhau."""
    ref = "Nghị định số năm"
    hyp = "Nghị đinh số năm"
    assert cer(ref, hyp) < wer(ref, hyp)


# ── tỉ lệ dấu ───────────────────────────────────────────────────────────────

def test_accent_share_is_zero_for_plain_ascii():
    assert accent_share("Nghi dinh so 56") == 0.0


def test_accent_share_counts_combining_marks_regardless_of_input_form():
    """Phải ra cùng một số dù đầu vào là NFC hay NFD.

    `accent_share` cố ý làm việc trên NFD, nên nếu quên chuẩn hoá thì bản NFC
    sẽ ra 0 — và ta sẽ kết luận engine mất hết dấu trong khi nó đọc đúng.
    """
    text = "Điều khoản thi hành"
    assert accent_share(ud.normalize("NFC", text)) == pytest.approx(
        accent_share(ud.normalize("NFD", text)))
    assert accent_share(text) > 0.15


def test_accent_share_is_blind_to_the_d_stroke_letter():
    """`đ` KHÔNG phải dấu tổ hợp — điểm mù đã biết, viết ra để khỏi quên.

    U+0111 không phân rã: Unicode coi nét gạch ngang là bộ phận của chữ cái.
    Nên engine đọc "đường" thành "dường" không làm tụt `accent_share` chút
    nào, dù đó là lỗi tesseract hay mắc. CER mới bắt được nó.

    Test này tồn tại để người sau không "sửa" `accent_share` cho đếm luôn `đ`
    — làm vậy là đổi định nghĩa và mốc hiệu chuẩn 0,217 mất giá trị so sánh.
    """
    assert accent_share("đường") == accent_share("dường")
    assert cer("đường", "dường") > 0, "CER phải bắt được, và nó bắt được"


def test_stroke_letter_share_covers_that_blind_spot_separately():
    """Trục riêng cho `đ`, để theo dõi được mà không đụng vào định nghĩa cũ."""
    assert stroke_letter_share("đường") > 0
    assert stroke_letter_share("dương") == 0.0
    assert stroke_letter_share("abc") == 0.0


def test_accent_share_lands_near_the_calibration_constant_for_real_vietnamese():
    """Mốc hiệu chuẩn 0,217 đo trên ground truth MDPBench.

    Đây là cái thước để trả lời "engine này có thật sự đọc được tiếng Việt
    không". Tesseract trên kho thật chỉ đạt 0,080–0,102.
    """
    real = ("Căn cứ Nghị định số 56/2026/NĐ-CP của Chính phủ quy định chi "
            "tiết một số điều của Luật Đầu tư về điều kiện kinh doanh")
    assert 0.15 <= accent_share(real) <= 0.35


def test_accent_share_exposes_an_engine_that_silently_strips_diacritics():
    """Đây là hình dạng của lỗi tesseract, viết ra thành test."""
    ref = "Ủy ban nhân dân Thành phố Hà Nội"
    stripped = "Uy ban nhan dan Thanh pho Ha Noi"
    assert accent_share(ref) > 0.2
    assert accent_share(stripped) == 0.0


# ── định danh ───────────────────────────────────────────────────────────────

def test_a_vietnamese_legal_document_number_is_extracted_as_one_unit():
    """`56/2026/NĐ-CP` phải ra NGUYÊN CỤM, không bị xé thành "56" và "2026".

    Nếu bị xé, một engine làm vỡ số hiệu vẫn được chấm "còn nguyên" vì các
    mảnh số vẫn còn — đúng kiểu hỏng im lặng mà cổng chặn này sinh ra để bắt.
    """
    got = identifiers("Căn cứ Nghị định số 56/2026/NĐ-CP ngày 12/03/2026")
    assert "56/2026/NĐ-CP" in got
    assert "12/03/2026" in got


@pytest.mark.parametrize("text, expected", [
    ("Quyết định 1656/QĐ-TTg", "1656/QĐ-TTg"),
    ("Thông tư 03/2025/TT-BTC", "03/2025/TT-BTC"),
    ("liên hệ thongtinchinhphu@chinhphu.vn", "thongtinchinhphu@chinhphu.vn"),
    ("hồ sơ NQ9001 đính kèm", "NQ9001"),
    ("tổng cộng 1.234.567 đồng", "1.234.567"),
    ("ngày 2026-03-12", "2026-03-12"),
])
def test_each_identifier_shape_survives_extraction(text, expected):
    assert expected in identifiers(text)


def test_an_email_is_not_shredded_into_smaller_identifiers():
    """Email phải khớp trước các mẫu khác, nếu không nó vỡ thành nhiều mảnh."""
    got = identifiers("gửi tới info@congty.com.vn trước ngày")
    assert got == ["info@congty.com.vn"]


def test_repeated_identifiers_are_counted_by_occurrence_not_by_uniqueness():
    """Bản gốc có "56" ba lần, bản OCR giữ một lần ⇒ mất hai.

    Dùng set sẽ báo 100% còn nguyên. Đó là lý do `identifiers` trả list.
    """
    ref = "mục 56, khoản 56, điểm 56"
    hyp = "mục 56, khoản XX, điểm YY"
    assert identifier_preservation(ref, hyp) == pytest.approx(1 / 3)


def test_perfect_output_preserves_every_identifier():
    ref = "Nghị định 56/2026/NĐ-CP ngày 12/03/2026, liên hệ a@b.vn"
    assert identifier_preservation(ref, ref) == 1.0


def test_the_exact_failure_that_disqualified_the_mbart_corrector():
    """Model sửa lỗi sinh chữ từng nuốt email và làm sai số — đạt 86%, bị loại.

    Viết ca đó thành test để ngưỡng 99% không bị hạ xuống cho model mới chỉ vì
    nó "hứa là không viết lại văn bản".
    """
    ref = "Liên hệ info@chinhphu.vn hoặc gọi 0243.123.456 theo NĐ 56/2026/NĐ-CP"
    rewritten = "Liên hệ hoặc gọi 0243.123.455 theo NĐ 56/2026/NĐ-CP"
    assert identifier_preservation(ref, rewritten) < 0.99


def test_latex_typesetting_commands_are_not_treated_as_identifiers():
    """`\\[8pt]` là lệnh GIÃN DÒNG, không phải nội dung tài liệu.

    Ca thật: ground truth MDPBench giữ công thức ở dạng LaTeX, nên `\\[8pt]`
    bị rút thành định danh `8pt`. Model đọc đúng công thức nhưng xuống dòng
    theo cách khác ⇒ bị trừ điểm oan, kéo `vi_exampaper_3.png` từ 1,000
    xuống 0,952. 44/160 trang có ký hiệu LaTeX nên đây không phải ca hiếm.

    Cổng định danh phải phạt engine làm mất SỐ LIỆU, không phạt nó vì chọn
    cách trình bày công thức khác ground truth.
    """
    latex = r"$x = \dfrac{\pi}{6} + k\pi \\[8pt] x = \dfrac{5\pi}{6} + k\pi$"
    assert "8pt" not in identifiers(latex)
    assert "10pt" not in identifiers(r"a \\[10pt] b")


def test_real_numbers_inside_formulas_are_still_extracted():
    """Chỉ bỏ mã TRÌNH BÀY. Hệ số và chỉ số trong công thức là nội dung thật.

    Bỏ quá tay sẽ làm cổng kiểm mù với engine đọc sai công thức — mà đề thi
    toán thì toàn bộ nội dung nằm trong công thức.
    """
    got = identifiers(r"$x = \frac{2\pi}{3} + k2\pi$")
    assert "2" in got and "3" in got

    # Số hiệu văn bản không được đụng tới.
    assert "56/2026/NĐ-CP" in identifiers(
        r"Nghị định 56/2026/NĐ-CP \\[8pt] ban hành")


def test_a_formula_typeset_differently_still_preserves_its_identifiers():
    """Cùng công thức, hai cách xuống dòng ⇒ định danh phải còn nguyên 100%."""
    ref = r"$x = \dfrac{\pi}{6} + k\pi \\[8pt] x = \dfrac{5\pi}{6}$"
    hyp = r"$x = \frac{\pi}{6} + k\pi, x = \frac{5\pi}{6}$"
    assert identifier_preservation(ref, hyp) == 1.0


def test_text_without_identifiers_does_not_fail_the_gate():
    """Không có gì để mất thì không thể coi là thất bại."""
    assert identifier_preservation("Xin chào các bạn", "Xin chào các bạn") == 1.0
    assert identifier_preservation("Xin chào", "") == 1.0


def test_identifier_matching_ignores_diacritic_typing_convention_but_not_digits():
    """Chữ trong số hiệu vẫn theo quy ước dấu; CHỮ SỐ thì phải khớp tuyệt đối."""
    assert identifier_preservation("mã 56/2026", "mã 56/2O26") < 1.0


# ── tổng hợp ────────────────────────────────────────────────────────────────

def test_score_reports_raw_counts_so_pages_can_be_pooled_by_weight():
    """Tổng hợp nhiều trang phải cộng dồn, không lấy trung bình các tỉ lệ.

    Một trang 5 ký tự sai hết sẽ kéo trung bình xuống ngang một trang 2 000 ký
    tự sai hết. Nên `score` giữ lại số đếm thô để cộng dồn đúng trọng số.
    """
    s = score("Nghị định 56/2026/NĐ-CP ngày 12/03/2026",
              "Nghi dinh 56/2026/NĐ-CP ngày 12/03/2026")
    assert s.identifiers_total == 2
    assert s.identifiers_kept == 2
    assert s.identifier_preservation == 1.0
    assert s.ref_chars > 0
    assert s.accent_ref > s.accent_hyp, "bản OCR mất dấu, phải thấy được"
    assert s.passes_identifier_gate


def test_score_flags_a_page_that_fails_the_identifier_gate():
    s = score("Nghị định 56/2026/NĐ-CP và 1656/QĐ-TTg", "Nghị định và")
    assert not s.passes_identifier_gate
    assert s.identifiers_kept == 0


def test_a_fast_engine_that_loses_accents_still_fails_on_the_accent_axis():
    """Tình huống thật: tesseract nhanh 0,3 s/ảnh nhưng đọc mất dấu.

    CER còn chấp nhận được, nhưng `accent_hyp` tụt sâu dưới mốc 0,217. Nhanh
    mà đọc sai vẫn là đọc sai.
    """
    ref = "Ủy ban nhân dân Thành phố Hà Nội quyết định"
    hyp = "Uy ban nhan dan Thanh pho Ha Noi quyet dinh"
    s = score(ref, hyp)
    assert s.identifier_preservation == 1.0, "không có định danh nào để mất"
    assert s.accent_hyp == 0.0
    assert s.accent_ref > 0.2
    assert s.cer > 0.2
