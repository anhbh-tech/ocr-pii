"""Person names beyond the labelled field: lexicon, cues, propagation, residue.

Every name here is invented; see tests/name_bench.py for the measured rates.
"""
from __future__ import annotations

import pytest

from pii_core import Policy, names, redact_case, redact_document
from pii_core.extract import extract

KEY = "synthetic-test-key-not-a-secret"


def persons(text: str) -> list[str]:
    return [text[h.start:h.end] for h in extract(text) if h.category == "PERSON"]


@pytest.fixture()
def pol() -> Policy:
    return Policy(KEY)


@pytest.mark.parametrize("text, name", [
    ("tin nhắn: tôi là trần thị mẫu, xin xác nhận.", "trần thị mẫu"),     # lowercase
    ("Cam on, Tran Thi Mau se gui lai ban scan.", "Tran Thi Mau"),         # unaccented
    ("goi lai cho le van cau truoc thu sau", "le van cau"),
    ("Hợp đồng do Lã Hữu Toản ký ngày 05/03/2024.", "Lã Hữu Toản"),        # rarer surname
    ("Theo đề nghị của Giám đốc Mẫu Minh Khang, chúng tôi gửi lại.", "Mẫu Minh Khang"),
    ("Chị Thử nhắn là đã nhận được.", "Thử"),                              # kin cue
    ("John Placeholder confirmed the instructions.", "John Placeholder"),  # Western
])
def test_unlabelled_names(text, name):
    assert name in persons(text)


@pytest.mark.parametrize("text", [
    "Văn phòng nằm trên đường Võ Văn Tần gần chợ.",
    "Chi nhánh đặt tại Hà Lan từ năm ngoái.",
    "Sản phẩm đạt tiêu chuẩn quốc tế.",
    "Giá thị trường biến động mạnh.",
    "Tài liệu viết bằng tiếng Anh và tiếng Việt.",
    "We received an Office Action last week.",
])
def test_places_and_phrases_are_not_names(text):
    assert persons(text) == []


def test_a_labelled_name_is_masked_in_every_shape_with_one_token(pol):
    text = ("Họ và tên: Đặng Công Cấu\n"
            "tin nhắn: tôi là đặng công cấu, cảm ơn.\n"
            "goi lai cho dang cong cau nhe\n")
    out = redact_document(text, pol, group="T").text
    tokens = {t for t in out.split() if t.startswith("[PERSON-")}
    assert "cấu" not in out.casefold() and "cau" not in out.casefold()
    assert len({t.strip(",.") for t in tokens}) == 1


def test_a_given_name_follows_its_full_name_only_after_a_cue(pol):
    text = "Họ và tên: Ung Thị Mẫu\nchị Mẫu nhắn lại. Mẫu đơn số 01 đính kèm.\n"
    out = redact_document(text, pol, group="T").text
    assert "chị [PERSON-" in out and "Mẫu đơn số 01" in out
    assert out.count(out.split("Họ và tên: ")[1].split("\n")[0]) == 2


def test_a_case_carries_names_across_its_documents(pol):
    docs = ["Họ và tên: Khảo Minh Toản\n", "Khảo Minh Toản đã ký.\n"]
    assert redact_document(docs[1], pol, group="T").text == docs[1]     # alone: missed
    first, second = (r.text for r in redact_case(docs, pol, group="T"))
    token = first.split(": ")[1].strip()
    assert second == f"{token} đã ký.\n"


def test_a_vault_seeds_the_names_of_the_next_document(pol):
    first = redact_document("Họ và tên: Khảo Minh Toản\n", pol, group="T")
    second = redact_document("Khảo Minh Toản đã ký.\n", pol, group="T", vault=first.vault)
    assert second.text.startswith("[PERSON-")


def test_a_name_shaped_residue_stops_the_document(pol):
    r = redact_document("Hợp đồng do Nhan Hải Hoa ký.\n", pol, group="T")
    assert not r.summary["ok"]
    assert [x["matched_by"] for x in r.residue] == ["residue:name"]


def test_a_not_pii_label_shields_its_value_from_the_residue_check(pol):
    assert redact_document("Tên sản phẩm: KIM LONG\n", pol, group="T").summary["ok"]


@pytest.mark.parametrize("text, name", [
    ("ĐẠI DIỆN BÊN A\nBà\nThử Mẫu\n", "Thử Mẫu"),             # signature block
    ("Ông\nNGUYỄN VĂN MẪU\n", "NGUYỄN VĂN MẪU"),
    ("Mr\nJohn Placeholder\n", "John Placeholder"),
    ("Kính gửi bà Thử Mẫu,", "Thử Mẫu"),                      # same line, as before
    ("Kính gửi Bà Trần Thị Mẫu,", "Trần Thị Mẫu"),
    ("Theo đề nghị của ông Cấu Toản, hồ sơ gửi lại.", "Cấu Toản"),
])
def test_an_honorific_carries_its_name_across_one_line_break(text, name):
    assert name in persons(text)


@pytest.mark.parametrize("text", [
    "Kính gửi bà\n\nThử Mẫu đã ký.",           # a blank line parts them
    "Kính gửi bà\nVăn phòng đã nhận.",       # an accented stop word
    "Bà\nHà Nội, ngày 01 tháng 02 năm 2025",   # the place under a signature
    "Bà\nHa Noi, ngay 01 thang 02",            # the same, OCR without marks
    "Ông\nHoà Bình\n",                        # the old tone placement
    "đã gửi cho bà\nHôm nay trời mưa.",         # the next line of prose
])
def test_an_honorific_does_not_reach_past_its_line_break(text):
    assert persons(text) == []


def test_a_form_label_under_an_honorific_is_not_a_name():
    text = "Ông/Bà\nHọ và tên: Nguyễn Văn Mẫu\n"
    assert persons(text) == ["Nguyễn Văn Mẫu"]


@pytest.mark.parametrize("text", [
    "Chủ đơn:\nĐơn đã nộp ngày 05/03/2025.\n",  # measured: "Đơn" as PERSON
    "Tác giả: Đơn này chưa có.\n",
    "Đại diện chủ đơn:\nĐơn đăng ký nhãn hiệu đã nộp.\n",
    "chủ đơn Đơn đăng ký nhãn hiệu",
    "Người nhận: Chưa có.\n",
    "Chủ đơn NH đã nộp đủ phí.",                # an abbreviation after a role
])
def test_a_common_word_after_a_person_label_or_role_is_not_a_name(text):
    assert persons(text) == []


def test_a_name_inside_a_sentence_under_a_person_label_stays_treated():
    """The label is dropped only when nothing else in it is capitalised."""
    assert any("Cấu Mẫu" in p for p in persons("Chủ đơn:\nĐơn do Cấu Mẫu nộp.\n"))
    assert "Nguyễn Văn Mẫu" in persons("Chủ đơn: Nguyễn Văn Mẫu\n")


@pytest.mark.parametrize("text, name", [
    ("Hồ sơ do Khánh Linh chuẩn bị.", "Khánh Linh"),
    ("Thu Hà đã ký biên bản.", "Thu Hà"),
    ("Theo Thu Hà, hạn nộp là thứ sáu.", "Thu Hà"),
    ("Khánh Anh đã nộp tờ khai.", "Khánh Anh"),  # a kinship word may end it
])
def test_a_bare_two_syllable_name_is_found(text, name):
    assert name in persons(text)


@pytest.mark.parametrize("text", [
    "Bộ Tài Chính ban hành thông tư.",
    "Cục Hải Quan đã kiểm tra lô hàng.",
    "Nhãn hiệu Minh Anh đã được nộp.",
    "Công ty Minh Anh đã ký hợp đồng.",
    "Độc Lập - Tự Do - Hạnh Phúc",
    "Hàng hóa nhập từ Nam Phi.",
    "Báo Cáo Tài Chính Năm",
    "Bản dịch sang Tiếng Anh đính kèm.",
    "Tôi gặp Khánh\nAnh ấy nói đã nộp.",     # a pair never spans a line
])
def test_two_name_syllables_that_make_a_word_or_a_mark_are_not_a_name(text):
    assert persons(text) == []


def test_the_common_words_are_no_name_syllable():
    from pii_core import names
    syllables = names.SURNAMES | names.MIDDLE.accented | names.GIVEN.accented
    assert not names.COMMON & syllables
    assert not names.COMMON & {"mẫu", "thử", "cấu", "giả"}
    assert all(not names._plain(w) for w in names.COMMON)


def test_a_name_glued_to_the_role_after_it_is_parted_from_it():
    # OCR lost the line break between the name and the next field's role.
    assert persons("Chức vụ:\nBà Trần Thị Mẫu LanGiám đốc\n") == ["Trần Thị Mẫu Lan"]


def test_a_western_name_with_an_inner_capital_stays_whole():
    assert persons("Signed by John McDonald today.\n") == ["John McDonald"]


@pytest.mark.parametrize("text", [
    "LƯU Ý: nộp đơn trước hạn.\n",
    "DỊCH VỤ PHÁP LÝ\n",
    "VỤ PHÁP LÝ\n",
    "Dịch Vụ Pháp Lý Mẫu\n",
    "PETITION TO DIRECTOR GRANTED\n",
    "TEAS PETITION TO DIRECTOR RECEIVED\n",
    "Chúng tôi chờ mã xác nhận từ Luật sư Hoa Kỳ, rồi nộp.\n",
    "12 Mau Street, Nguyen Du Ward, Mau District\n",
    "12 Mau Street, Nguyen Du\nWard Mau, Mau District\n",
])
def test_phrases_led_by_a_surname_or_a_cue_are_no_names(text):
    assert persons(text) == []


def test_a_seen_phrase_that_is_no_name_is_not_sought_again():
    # An older vault can hold one; it would take "dịch vụ pháp lý" from prose.
    text = "Công ty cung cấp dịch vụ pháp lý. LƯU Ý: lưu ý hạn nộp.\n"
    got = [text[h.start:h.end] for h in extract(text, names_seen=["VU PHÁP LÝ", "LƯU Ý"])
           if h.category == "PERSON"]
    assert got == []


def test_the_honorific_before_a_labelled_name_stays_out_of_its_token():
    text = "Người đại diện: Bà Trần Thị Mẫu\n"
    assert persons(text) == ["Trần Thị Mẫu"]


def test_a_name_glued_to_the_next_english_label_is_parted_from_it():
    assert persons("Signed Trần Thị Mẫu LanFirst\n") == ["Trần Thị Mẫu Lan"]


def test_a_western_surname_with_a_syllable_prefix_stays_whole():
    assert persons("Signed by John LeBlanc today.\n") == ["John LeBlanc"]


@pytest.mark.parametrize("text", ["THB\nTHAI BAHT\n", "Tỷ giá Thai Baht hôm nay\n"])
def test_a_currency_led_by_a_surname_is_no_name(text):
    assert persons(text) == []
    assert list(names.residue_names(text)) == []


def test_a_street_named_after_a_known_name_is_no_mention_of_it():
    case = names.CaseNames(["Nguyễn Văn Mẫu"])
    for text in ("số 1 đường Nguyễn Văn Mẫu, Hà Nội", "1 Nguyen Van Mau Street",
                 "Nguyen Van Mau Ward, District 1"):
        assert case.find(text) == [], text
    assert case.find("Ông Nguyễn Văn Mẫu đã ký") != []


def test_a_guessed_name_is_found_again_only_in_a_names_shape():
    case = names.CaseNames(guesses=["PHẠM VI", "DANG KY"])
    assert case.find("trong phạm vi hợp đồng") == []
    assert case.find("Phạm vi công việc") == []
    assert case.find("Đăng ký nhãn hiệu, đăng ký lại") == []
    assert case.find("PHAM VI") != [] and case.find("pham vi") != []


def test_a_short_name_after_a_cue_keeps_its_accents():
    case = names.CaseNames(["Nguyễn Thị Vân"])
    assert case.find("anh vẫn chưa gửi") == []
    assert [text[s:e] for text in ["chị Vân đã gửi", "chi van da gui", "chị Vân"]
            for s, e, _ in case.find(text)] == ["Vân", "van", "Vân"]
    assert names.CaseNames(["Trần Thị Hòa"]).find("chị Hoà đã gửi") != []
