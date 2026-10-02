"""The first extraction step: candidate PII fields in free document text."""
from __future__ import annotations

import pytest

from pii_core.extract import extract, labelled_fields
from pii_core.labels import category_for_label


def found(text: str) -> list[tuple[str, str, str]]:
    return [(h.category, h.tier, text[h.start:h.end]) for h in extract(text)]


def found_seen(text: str, **seen) -> list[tuple[str, str, str]]:
    return [(h.category, h.tier, text[h.start:h.end]) for h in extract(text, **seen)]


def categories(text: str) -> dict[str, str]:
    return {text[h.start:h.end]: h.category for h in extract(text)}


def test_labelled_line_fields():
    text = "Họ và tên: Nguyễn Văn Mẫu    Sinh ngày: 05/03/1990\n"
    got = found(text)
    assert ("PERSON", "label", "Nguyễn Văn Mẫu") in got
    assert ("BIRTH_DATE", "exact", "05/03/1990") in got


def test_value_on_the_next_line():
    text = "Địa chỉ:\n12 Đường Hư Cấu, Phường Mẫu\n"
    assert ("ADDRESS", "label", "12 Đường Hư Cấu, Phường Mẫu") in found(text)


def test_several_labels_on_one_line():
    text = "Điện thoại: 0900 000 001; Email: mau.nguyen@example.test\n"
    got = categories(text)
    assert got["0900 000 001"] == "PHONE"
    assert got["mau.nguyen@example.test"] == "EMAIL"


def test_exact_patterns_inside_a_labelled_value_keep_their_own_category():
    text = "Người đại diện: Công ty TNHH Mẫu Thử, MST 0312345678\n"
    got = categories(text)
    assert got["0312345678"] == "TAX_CODE"
    assert "Công ty TNHH Mẫu Thử" in got


def test_cued_numbers():
    got = categories("Số CCCD: 001099000001 cấp ngày 01/01/2020")
    assert got["001099000001"] == "NATIONAL_ID"
    assert got["01/01/2020"] == "DATE"


@pytest.mark.parametrize("text, value, category", [
    ("Ông Trần Thị Thử liên hệ", "Trần Thị Thử", "PERSON"),
    ("liên hệ qua +84 900 000 002 nhé", "+84 900 000 002", "PHONE"),
    ("về hồ sơ NH1234.", "NH1234", "MATTER_REF"),
    ("Placeholder Holdings Ltd trả tiền", "Placeholder Holdings Ltd", "ORG"),
    ("trả $ 2,500.00 hôm nay", "$ 2,500.00", "MONEY"),
    ("phí 1,234,567 VND", "1,234,567 VND", "MONEY"),
    ("gửi mau.nguyen@example.test", "mau.nguyen@example.test", "EMAIL"),
])
def test_unlabelled_text(text, value, category):
    assert categories(text).get(value) == category


def test_markdown_table_pairs():
    text = ("| Trường | Giá trị |\n|---|---|\n| Họ tên | Lê Hư Cấu |\n"
            "| Nơi thường trú | Số 5 ngõ 12 phố Mẫu, Quận Thử |\n")
    got = categories(text)
    assert got["Lê Hư Cấu"] == "PERSON"
    assert got["Số 5 ngõ 12 phố Mẫu, Quận Thử"] == "ADDRESS"


def test_html_table_header_mode():
    text = ("<table><tr><th>Họ tên</th><th>Email</th></tr>"
            "<tr><td>Phạm Giả Định</td><td>dinh.pham@example.test</td></tr></table>")
    got = categories(text)
    assert got["Phạm Giả Định"] == "PERSON"
    assert got["dinh.pham@example.test"] == "EMAIL"


def test_boilerplate_and_register_spans_keep_their_category():
    text = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nSố đơn: 4-2024-12345\n"
    got = categories(text)
    assert got["CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"] == "BOILERPLATE"
    assert got["4-2024-12345"] == "APP_SERIAL"


@pytest.mark.parametrize("text, value", [
    ("79000001", "79000001"),                                   # standalone
    ("Số đơn 79000001, nộp ngày 01/02/2025.", "79000001"),      # before a comma
    ("Hồ sơ gồm đơn số 79000001.", "79000001"),                 # before a period
    ("Serial No. 90000001 was filed with the USPTO.", "90000001"),
    ("Các đơn 79000001 và 90000002 cùng chủ.", "90000002"),     # in prose
    ("Số đơn 4-2024-12345, nộp ngày 01/02/2025.", "4-2024-12345"),
    ("Hồ sơ gồm đơn số 4-2024-12345.", "4-2024-12345"),
])
def test_an_application_serial_is_found_beside_sentence_punctuation(text, value):
    """Gate 3 caught what gate 1 let through: the serial before a comma."""
    assert categories(text).get(value) == "APP_SERIAL"


@pytest.mark.parametrize("text", [
    "Tỷ lệ 0,79000001 theo bảng.",           # a decimal
    "Hệ số 3.79000001 đã làm tròn.",
    "Giá trị 79000001,5 và 79000001.25.",
    "Gọi 0900000001 hoặc 0900 000 001.",     # a phone-like run
    "Mã 790000011 dài chín chữ số.",          # a longer run
    "Mã 79000001-1 có gạch nối.",             # hyphenated
    "Tổng cộng 7.900.000.001 đồng.",          # money
])
def test_a_decimal_or_a_longer_run_is_not_an_application_serial(text):
    assert "APP_SERIAL" not in categories(text).values()


def test_a_labelled_mark_is_found_again_in_the_prose():
    text = ("Tên nhãn hiệu: HƯ CẤU\n"
            "Nhãn hiệu Hư Cấu bị phản đối; HƯ CẤU trùng với nhãn khác. "
            "Một câu chuyện hư cấu thì không phải nhãn hiệu.\n")
    got = [(text[h.start:h.end], h.category) for h in extract(text)
           if h.category == "MARK"]
    assert got == [("HƯ CẤU", "MARK"), ("Hư Cấu", "MARK"), ("HƯ CẤU", "MARK")]


def test_a_mark_seen_elsewhere_in_the_case_is_found_without_a_label():
    text = "Ý kiến về khả năng đăng ký của HƯ CẤU.\n"
    assert [text[h.start:h.end] for h in extract(text, marks_seen=["HƯ CẤU"])
            if h.category == "MARK"] == ["HƯ CẤU"]


def test_not_pii_label_shields_its_value():
    text = "Tên sản phẩm: HƯ CẤU\n"
    assert [h.category for h in extract(text) if text[h.start:h.end] == "HƯ CẤU"] \
        in ([], [None])


def test_times_and_urls_are_not_split_as_labels():
    text = "Họp lúc 10:30 tại https://example.test/a:b\n"
    assert not [h for h in extract(text) if h.tier == "label"]


def test_hits_never_overlap(case_text):
    hits = extract(case_text)
    for a, b in zip(hits, hits[1:]):
        assert a.end <= b.start


@pytest.mark.parametrize("text, value", [
    ("Chi phí: 12.500.000 đồng (mười hai triệu năm trăm nghìn đồng).",
     "mười hai triệu năm trăm nghìn đồng"),
    ("Bằng chữ Hai Mươi Triệu Đồng Chẵn.", "Hai Mươi Triệu Đồng Chẵn"),
])
def test_amounts_in_words(text, value):
    assert categories(text).get(value) == "MONEY"


@pytest.mark.parametrize("text", [
    "Trong năm hai đồng nghiệp đã nộp đơn.",
    "mười hai đồng thời nộp",
])
def test_dong_compounds_are_not_money(text):
    assert "MONEY" not in categories(text).values()


def test_bracketed_area_code_stays_inside_the_phone():
    text = "gọi (028) 3900 0001 nhé"
    assert categories(text).get("(028) 3900 0001") == "PHONE"


# -- the numbers the digit sieve used to stop a document over -------------------
#
# Every shape below stood, unrecognised, in a document the 2026-09-24 dry run
# refused to release. The values are invented; only the shapes are real.

@pytest.mark.parametrize("text, value", [
    ("Tổng đài hỗ trợ: 1-800-555-0199", "1-800-555-0199"),
    ("Call 800-555-0188 for the registry.", "800-555-0188"),
    ("Hotline (833) 555-0177 daily.", "(833) 555-0177"),
    ("Gọi +1 888 555 0166 nhé", "+1 888 555 0166"),
    ("Tổng đài 1900 0000 của Cục.", "1900 0000"),
    ("Miễn cước 1800 0000.", "1800 0000"),
])
def test_a_published_switchboard_is_a_hotline_not_a_phone(text, value):
    assert categories(text).get(value) == "HOTLINE"


@pytest.mark.parametrize("text, value", [
    ("gọi (028) 3900 0001 nhé", "(028) 3900 0001"),
    ("liên hệ (212) 555-0144", "(212) 555-0144"),
    ("liên hệ +1 212 555 0155", "+1 212 555 0155"),
    ("Điện thoại: 0900 000 001", "0900 000 001"),
])
def test_a_personal_number_is_still_a_phone(text, value):
    assert categories(text).get(value) == "PHONE"


def test_a_registry_e_seal_is_a_machine_trace_even_when_it_wraps():
    text = ("STAMP:USPTO/APPB-10.900.900.900-12345678901234567-79000001-11.1-\n"
            "1a900a1b-90a1-90a1-1a90-a90a900aa900-CARD-99000000000000000001\n")
    got = [(h.category, text[h.start:h.end]) for h in extract(text)]
    assert got and got[0][0] == "MACHINE_TRACE"
    # one value, not two: the hyphen before the line break continues it.
    assert got[0][1].startswith("USPTO/") and got[0][1].endswith("-CARD-"
        "99000000000000000001")
    assert "\n" in got[0][1]


def test_a_transaction_id_is_a_machine_trace():
    text = "Mã giao dịch: 99000000000000000001\n"
    assert categories(text).get("99000000000000000001") == "MACHINE_TRACE"


@pytest.mark.parametrize("text, value", [
    ("Số tài khoản: |  99000000000001\n", "99000000000001"),
    ("Routing Number: |  990000001\n", "990000001"),
    ("Routing Number: 990000001\n", "990000001"),
    ("ABA Routing Number: 990000001\n", "990000001"),
    ("Số thẻ: 9900 0000 0000 0001\n", "9900 0000 0000 0001"),
])
def test_an_account_or_routing_number_is_recognised(text, value):
    assert categories(text).get(value) == "OTHER_ID"


def test_a_bare_account_number_under_a_bank_name_is_recognised():
    text = "Thanh toán\nNGAN HANG MAU BANK\n99000000000001\n"
    assert categories(text).get("99000000000001") == "OTHER_ID"


def test_a_bare_long_number_with_no_bank_in_sight_is_not_an_account():
    text = "Số trang in: 99000000000001\n"
    assert "OTHER_ID" not in categories(text).values()


def test_two_amounts_glued_together_are_still_money():
    text = "Gói1,1234.567.89012.345.678  Gói2\n"
    assert categories(text).get("1234.567.89012.345.678") == "MONEY"


@pytest.mark.parametrize("text", [
    "phiên bản 1.2.3.4 của biểu mẫu",
    "IP 10.900.900.900 ghi trong log",
])
def test_a_dotted_run_that_is_not_two_amounts_is_left_alone(text):
    assert "MONEY" not in categories(text).values()


def test_a_table_cell_wall_after_the_colon_does_not_end_the_value():
    text = "Họ và tên: | Nguyễn Văn Mẫu | Chức vụ: | Giám đốc\n"
    assert ("PERSON", "label", "Nguyễn Văn Mẫu") in found(text)


def labelled(text: str) -> list[tuple[str, str]]:
    return [(c, v) for c, t, v in found(text) if t == "label"]


@pytest.mark.parametrize("text", [
    "Address:\nCorrespondent\n",                    # the next label
    "Date:\nForeign Registration\n",                # a heading: no date in it
    "Filing Date:\nPriority Claimed Flag: Yes\n",   # the next field
    "Country:\nGoods and Services\n",               # a section heading
    "Mã tra cứu:\nCần tra cứu tại trang của cơ quan thuế\n",
    "E-mail:\ne-mail Authorized\n",
    "Beneficiary Address:\nBENEFICIARY ACCOUNT\n",
])
def test_what_stands_under_an_empty_label_must_be_its_value(text):
    assert labelled(text) == []


@pytest.mark.parametrize("text, category, value", [
    ("Mã tra cứu:\nAB12CD34EF\n", "INVOICE_NO", "AB12CD34EF"),
    ("Họ và tên:\nNguyễn Văn Mẫu\n", "PERSON", "Nguyễn Văn Mẫu"),
    ("Country:\nViệt Nam\n", "ADDRESS", "Việt Nam"),
])
def test_a_real_value_under_an_empty_label_is_still_taken(text, category, value):
    assert (category, value) in labelled(text)


@pytest.mark.parametrize("text, category, value", [
    ("Địa chỉ\nSố 12 Hư Cấu\n", "ADDRESS", "Số 12 Hư Cấu"),
    ("*City\nMauville\n", "ADDRESS", "Mauville"),
    ("Zip/postal code\n00000\n", "ADDRESS", "00000"),
    ("Invoice Number\nHD-0000123\n", "INVOICE_NO", "HD-0000123"),
    ("Docket or reference number\nHC-0001\n", "MATTER_REF", "HC-0001"),
])
def test_a_form_label_without_a_colon_declares_the_next_line(text, category, value):
    assert (category, value) in labelled(text)


@pytest.mark.parametrize("text", [
    "Địa chỉ của công ty đã thay đổi\nTừ tháng sau\n",   # a sentence, no label
    "Email\nPhone\nmau.nguyen@example.test\n",            # a row of column heads
    "Tên\nSản phẩm mới\n",
    "Ngày\n05/03/2025\n",                                 # the date says so itself
])
def test_a_line_that_only_starts_like_a_label_declares_nothing(text):
    assert [c for c, _ in labelled(text) if c != "DATE"] == []


def test_a_label_glued_to_the_value_before_it_still_ends_that_value():
    text = "Legal Representative: John PlaceholderFirst Name: John\n"
    assert ("PERSON", "John Placeholder") in labelled(text)


@pytest.mark.parametrize("text, category, value", [
    ("Docket Number: 00123-4\n", "MATTER_REF", "00123-4"),
    ("Docket number: 00123\n", "MATTER_REF", "00123"),
    ("Mã CQT: 00AB12CD34EF56\n", "INVOICE_NO", "00AB12CD34EF56"),
    ("ROUTING # (for wire): 990000012\n", "OTHER_ID", "990000012"),
    ("Beneficiary Account: AC-0001\n", "OTHER_ID", "AC-0001"),
])
def test_more_labels_declare_their_category(text, category, value):
    assert (category, value) in labelled(text)


def test_a_spaced_dash_ends_a_compact_value():
    text = "Số tài khoản: 99000000000001 - Ngân hàng Mẫu\n"
    got = categories(text)
    assert got.get("99000000000001") == "OTHER_ID"
    assert "Ngân" not in " ".join(v for v, c in got.items() if c == "OTHER_ID"
                                  and v != "99000000000001")


@pytest.mark.parametrize("text, value", [
    ("Nhãn hiệu “MẪU THỬ”, văn bằng bảo hộ số 990001, đăng ký cho nhóm 3.",
     "990001"),
    ("Your United States trademark registration number is 9900001.", "9900001"),
    ("Reg. No. 9,900,001\nRegistered Jan. 05, 2021\n", "9,900,001"),
    ("Reg No.\n: 9900001\n", "9900001"),
    ("International Registration\n9900001\nNumber:\n", "9900001"),
    ("Claimed Ownership of US\n9900001\nRegistrations:\n", "9900001"),
    ("Page: 1 of 2 / RN # 9900001\n", "9900001"),
])
def test_a_registration_number_is_found_by_its_cue(text, value):
    assert categories(text).get(value) == "REG_NUMBER"


@pytest.mark.parametrize("text", [
    "Registration Date: Jan. 05, 2021\n",
    "Theo quy định sau cấp văn bằng, để duy trì hiệu lực bảo hộ 10 năm.",
])
def test_a_registration_cue_without_its_number_takes_nothing(text):
    assert "REG_NUMBER" not in categories(text).values()


@pytest.mark.parametrize("text, value", [
    ("Foreign Application\n9900001\nForeign Application Filing\n", "9900001"),
    ("REG. NO. 9,900,001, SER. NO. 99-000,001, FILED 01-05-2020", "99-000,001"),
])
def test_an_application_number_in_its_other_shapes(text, value):
    assert categories(text).get(value) == "APP_SERIAL"


@pytest.mark.parametrize("text", [
    "ROUTING # :\n \n \n \n990000013\nACCOUNT NAME:\n",
    "Bank of Mẫu Thử\n12 Mau Street, Mauville, NY 00000\n990000013\n",
])
def test_a_routing_number_that_lost_its_label_is_recognised(text):
    assert categories(text).get("990000013") == "OTHER_ID"


def test_nine_digits_that_fail_the_routing_checksum_are_no_routing_number():
    assert categories("Bank of Mẫu Thử\n990000012\n").get("990000012") is None


@pytest.mark.parametrize("text, value", [
    ("50K:\n/99000000000001\nMAU THU CO LTD\n", "99000000000001"),
    ("59:/99000000000001\nJOHN PLACEHOLDER\n", "99000000000001"),
    ("50K: Ordering Customer-Name & Address\n/99000000000001\n", "99000000000001"),
    ("59: Beneficiary Customer\n/99000000000001\n", "99000000000001"),
])
def test_a_swift_party_account_line_is_an_account(text, value):
    assert categories(text).get(value) == "OTHER_ID"


def test_a_swift_acknowledgement_reference_is_a_machine_trace():
    text = "10:15:00 UTC LocalSwiftAcks-9900-00001\n"
    assert categories(text).get("LocalSwiftAcks-9900-00001") == "MACHINE_TRACE"


@pytest.mark.parametrize("text, value", [
    ("Bảng phí\nHạng mục\nSố tiền\nPhí nộp đơn\n1.234.567\n", "1.234.567"),
    ("Bảng phí\nPhí thẩm định\n2,345,678.50\n", "2,345,678.50"),
    ("Fee calculation (USD)\n12345678.12345678\n", "12345678.12345678"),
])
def test_an_amount_with_no_currency_in_a_fee_table_is_money(text, value):
    assert categories(text).get(value) == "MONEY"


@pytest.mark.parametrize("text", [
    "Số lượng: 1,234 cái\n",
    "Nhóm 3, 5, 9\n",
    "Version 2.345.678 of the form\n",
])
def test_a_grouped_number_with_no_money_in_sight_is_not_money(text):
    assert "MONEY" not in categories(text).values()


def test_a_run_of_one_repeated_digit_is_treated():
    assert categories("Mã: 222 222222\n").get("222 222222") == "OTHER_ID"


@pytest.mark.parametrize("text, value", [
    ("12345 valley mau ct.\nMauville\n", "12345 valley mau ct"),
    ("1234 SW 8th St Unit 100\n", "1234 SW 8th St Unit 100"),
    ("1234 N Mau Ave\n", "1234 N Mau Ave"),
    ("100 East 68th Street\n", "100 East 68th Street"),
    ("12 South 3rd Street, Suite 1000\n", "12 South 3rd Street, Suite 1000"),
    ("100 1st Street SE\n", "100 1st Street SE"),
    ("1234 MAU THU AVENUE\nSUITE 1000\n", "1234 MAU THU AVENUE\nSUITE 1000"),
    ("P.O. Box 1234\n", "P.O. Box 1234"),
    ("PO BOX 123456\n", "PO BOX 123456"),
])
def test_a_us_street_line_is_an_address(text, value):
    assert categories(text).get(value) == "ADDRESS"


@pytest.mark.parametrize("text, value", [
    ("Mauville, NEW YORK UNITED STATES 00000\n", "Mauville, NEW YORK UNITED STATES 00000"),
    ("Mau Ville, CALIFORNIA United States 99001-0001\n",
     "Mau Ville, CALIFORNIA United States 99001-0001"),
    ("MAUVILLE, TEXAS UNITED STATES 990010001\n", "MAUVILLE, TEXAS UNITED STATES 990010001"),
    ("Mauville, NY 00000\n", "Mauville, NY 00000"),
])
def test_a_us_city_line_is_an_address(text, value):
    assert categories(text).get(value) == "ADDRESS"


@pytest.mark.parametrize("text, value", [
    ("Mauville, Alberta CANADA T9Z9Z9\n", "Mauville, Alberta CANADA T9Z9Z9"),
    ("Mau Ville, Ontario Canada T9Z 9Z9\n", "Mau Ville, Ontario Canada T9Z 9Z9"),
    ("Mauville UNITED KINGDOM W9Z 9ZZ\n", "Mauville UNITED KINGDOM W9Z 9ZZ"),
    ("Mauville, United Kingdom EC9A 9ZZ\n", "Mauville, United Kingdom EC9A 9ZZ"),
])
def test_a_city_line_with_a_canadian_or_british_postcode_is_an_address(text, value):
    assert categories(text).get(value) == "ADDRESS"


def test_a_country_alone_is_no_address():
    assert "ADDRESS" not in categories("State or Country Where Organized: CANADA\n").values()


@pytest.mark.parametrize("text", [
    "In 2020 the way forward was clear.\n",
    "Nhóm 35, 12 dịch vụ\n",
    "See Section 12, NY law.\n",
])
def test_prose_with_a_number_is_no_us_address(text):
    assert "ADDRESS" not in categories(text).values()


@pytest.mark.parametrize("text, value", [
    ("So 12, Ngach 3/4 Mau Thu, Phuong Mau, Ha Noi, Viet Nam, 100000\n",
     "So 12, Ngach 3/4 Mau Thu, Phuong Mau, Ha Noi, Viet Nam, 100000"),
    ("Số 12, Ngách 34/56 Hư Cấu, phường Mẫu, Hà Nội, Việt Nam 100000\n",
     "Số 12, Ngách 34/56 Hư Cấu, phường Mẫu, Hà Nội, Việt Nam 100000"),
    ("12 Duong Mau, Quan Thu, TP. Ho Chi Minh\n",
     "12 Duong Mau, Quan Thu, TP. Ho Chi Minh"),
])
def test_a_vn_address_in_its_unaccented_and_slashed_shapes(text, value):
    assert categories(text).get(value) == "ADDRESS"


def test_a_label_over_a_colon_led_line_labels_that_line():
    # The register's two-column rendering: the label on one line, ": value"
    # on the next.
    text = "Trademark\n: MAUMARK\nClass\n: 035\nOwner\n: Mau Thu Placeholder\n"
    got = labelled(text)
    assert ("MARK", "MAUMARK") in got
    assert ("PERSON", "Mau Thu Placeholder") in got
    assert not any(v == "035" for _, v in got if _ != "NICE_CLASS")


def test_a_colon_led_line_under_prose_is_no_field():
    text = "The applicant filed the response on time and the office agreed\n: MAUMARK\n"
    assert labelled(text) == []


def test_reg_no_with_its_period_is_a_label():
    assert category_for_label("Reg No.") == "REG_NUMBER"


def test_a_date_label_over_words_with_no_date_takes_nothing():
    # "Not Found" is the register's filler, not a date: masking it would only
    # lose it on the way back.
    assert labelled("Date in Location: Not Found\n") == []
    assert ("DATE", "05/03/2025") in labelled("Date in Location: 05/03/2025\n") \
        or "DATE" in categories("Date in Location: 05/03/2025\n").values()


def test_a_seen_mark_that_is_a_label_is_not_sought_again():
    # An older vault can hold a heading taken for a mark; seeking it again
    # would take the word from every later document.
    text = "Trademark: MAUMARK\nThe Trademark Office accepted MAUMARK.\n"
    got = found_seen(text, marks_seen=["Trademark", "Nhãn hiệu"])
    assert [v for c, _, v in got if c == "MARK"] == ["MAUMARK", "MAUMARK"]


@pytest.mark.parametrize("text, marks", [
    ("Nhãn hiệu “MAUMARK”, văn bằng bảo hộ số 990001.\n", ["MAUMARK"]),
    ("the trademark \"VIDU MARK\" and \"MAUTHU\" are ours\n", ["VIDU MARK", "MAUTHU"]),
    ("Note: it matches the mark «MTHU» on file\n", ["MTHU"]),
])
def test_a_quoted_name_after_a_mark_cue_is_a_mark(text, marks):
    assert [v for c, _, v in found(text) if c == "MARK"] == marks


def test_a_quoted_mark_is_sought_again_in_the_prose():
    text = "Nhãn hiệu “MAUMARK” đã được cấp. MAUMARK được dùng từ lâu.\n"
    assert [v for c, _, v in found(text) if c == "MARK"] == ["MAUMARK", "MAUMARK"]


@pytest.mark.parametrize("text", [
    "nhãn hiệu “nổi tiếng” theo luật\n",         # a legal term, lower case
    "please mark “Received” on the form\n",       # the verb
])
def test_a_quoted_word_that_is_no_mark_is_kept(text):
    assert "MARK" not in categories(text).values()


@pytest.mark.parametrize("text", [
    "Chủ đơn: MAU THU LIMITED COMPANY\n",
    "Chủ đơn: Công ty TNHH MAU THU\n",
    "Owner: MAU THU, LLC\n",
])
def test_the_legal_form_left_beside_a_known_name_is_no_value(text):
    # The name is the caller's own fact; what is left of the label's value is
    # the legal form alone, which names no one.
    from pii_core.casevars import CaseVar
    got = [(h.category, text[h.start:h.end])
           for h in extract(text, case_vars=[CaseVar("Tên KH", "MAU THU", "ORG")])]
    assert got == [("ORG", "MAU THU")]


def test_a_label_glued_to_a_token_is_parted_from_it():
    # A redacted page, read again: the next label sticks to the token's "]".
    text = "First Name: [PERSON-a1b2c3d4e5]Last Name: [PERSON-f6e5d4c3b2]\n"
    assert [h for h in labelled_fields(text) if "Last" in text[h.start:h.end]] == []


def test_the_long_numbers_of_a_table_with_a_total_row_are_money():
    text = ("DV | 99000001\n"
            "Bank | 99000.1234567890\n"
            "Cộng bank | 99000001.12345678\n"
            "1.02 | 9900001.1234567890\n"
            "Tổng | 99000002 | 99000002.123456789\n")
    got = categories(text)
    for v in ("99000001", "99000.1234567890", "99000001.12345678", "9900001.1234567890",
              "99000002", "99000002.123456789"):
        assert got.get(v) == "MONEY", v
    assert "1.02" not in got


def test_a_table_without_a_total_row_is_no_fee_table():
    assert categories("Mã | 99000001\nLoại | 99000002\n").get("99000001") != "MONEY"


@pytest.mark.parametrize("text, value", [
    ("Attorney Name: Mauricio Q. Placeholder\nDocket Number: X\n", "Mauricio Q. Placeholder"),
    ("Full name: Mau T. PLACEHOLDER\n", "Mau T. PLACEHOLDER"),
    ("Signed by: Mr. Mau T. PLACEHOLDER\n", "Mau T. PLACEHOLDER"),
    ("Họ và tên: Nguyễn Văn A. Hồ sơ đã nhận.\n", "Nguyễn Văn A"),
])
def test_a_middle_initial_does_not_end_the_name(text, value):
    assert [v for c, t, v in found(text) if c == "PERSON"] == [value]


@pytest.mark.parametrize("text, value", [
    ("Represented by Mr. John T. PLACEHOLDER\n", "John T. PLACEHOLDER"),
    ("Dear Mr. John T. Placeholder,\n", "John T. Placeholder"),
    ("Signed by: Mr. John T. Placeholder\n", "John T. Placeholder"),
])
def test_a_name_found_by_its_cue_runs_past_a_middle_initial(text, value):
    assert [v for c, t, v in found(text) if c == "PERSON"] == [value]


@pytest.mark.parametrize("text", [
    "Floor 09-01, Mau Centre Building, 53 Mau\nThu Street, Mau Ward, Ha Noi\n",
    "Address: Floor 09-01, Mau Centre Building, 53 Mau\nThu Street, Mau Ward, Ha Noi\n",
])
def test_a_street_name_wrapped_onto_the_next_line_stays_one_address(text):
    at = text.index("Thu")
    assert any(h.category == "ADDRESS" and h.start <= at < h.end for h in extract(text))


def test_the_words_left_beside_a_labelled_number_are_no_number():
    text = "telephone number: (555) 555-0100. If you have questions\n"
    assert found(text) == [("PHONE", "exact", "(555) 555-0100")]


@pytest.mark.parametrize("text, value", [
    ("*Bar membership or registration \nnumber\n9900001\n", "9900001"),
    ("Bar number: 9900001\n", "9900001"),
])
def test_a_lawyers_bar_number_is_an_identifier(text, value):
    assert categories(text).get(value) == "OTHER_ID"


@pytest.mark.parametrize("text, value", [
    ("HÓA ĐƠN GIÁ TRỊ GIA TĂNG\nNgày 01 tháng 02 năm 2026\nSố:\n99000001\nMã CQT: X\n",
     "99000001"),
    ("HOÁ ĐƠN GIÁ TRỊ GIA TĂNG\nKý hiệu: 1C26TMT\nSố: 99000001\n", "99000001"),
])
def test_the_number_under_an_e_invoice_heading_is_the_invoice_number(text, value):
    assert categories(text).get(value) == "INVOICE_NO"


def test_a_bare_so_far_from_an_invoice_heading_is_no_invoice_number():
    text = "HÓA ĐƠN GIÁ TRỊ GIA TĂNG\n" + "Dòng mô tả hàng hoá.\n" * 20 + "Số: 99000001\n"
    assert categories(text).get("99000001") != "INVOICE_NO"


@pytest.mark.parametrize("text, name", [
    # A table cell whose <br> the caller flattened to a space: the captions
    # of the row run on after the name on one line.
    ("Full name: Nguyễn Văn Mẫu Nationality: Vietnamese\n", "Nguyễn Văn Mẫu"),
    ("Full name: John Placeholder Nationality: American\n", "John Placeholder"),
    ("Full name: John Placeholder Address: 1 Main Street\n", "John Placeholder"),
    ("Full Name: Tran Thi Mau Position: Director\n", "Tran Thi Mau"),
    ("Họ và tên: Nguyễn Văn Mẫu Quốc tịch: Việt Nam\n", "Nguyễn Văn Mẫu"),
    ("Owner: Nguyễn Văn Mẫu Nationality Vietnamese\n", "Nguyễn Văn Mẫu"),
    ("Full Name: John Placeholder Country: Canada\n", "John Placeholder"),
    ("Họ và tên: Nguyễn Văn Mẫu Chức vụ: Giám đốc\n", "Nguyễn Văn Mẫu"),
])
def test_the_caption_after_a_labelled_name_is_no_name(text, name):
    assert [v for c, t, v in found(text) if c == "PERSON"] == [name]


def test_the_nationality_under_its_caption_is_no_person():
    text = "Nationality: Vietnamese\nCitizenship: American\n"
    assert [v for c, t, v in found(text) if c == "PERSON"] == []


def test_a_name_part_caption_is_the_whole_caption():
    text = "First Name: Van Mau Last Name: Nguyen Middle Name: Thi\n"
    assert [v for c, t, v in found(text) if c == "PERSON"] == ["Van Mau", "Nguyen", "Thi"]


@pytest.mark.parametrize("text, org", [
    ("Party A: Example - Law Firm\n", "Example - Law Firm"),
    ("Party A: EXAMPLE LAW FIRM\n", "EXAMPLE LAW FIRM"),
    ("signed with Example Law Offices today\n", "Example Law Offices"),
    ("Bên A: Văn phòng luật Mẫu Thử\n", "Văn phòng luật Mẫu Thử"),
    ("Bên A: VĂN PHÒNG LUẬT MẪU THỬ\n", "VĂN PHÒNG LUẬT MẪU THỬ"),
    ("gửi EXAMPLE COMPANY LIMITED hôm nay\n", "EXAMPLE COMPANY LIMITED"),
    ("gửi EXAMPLE CO., LTD hôm nay\n", "EXAMPLE CO., LTD"),
    ("paid to EXAMPLE IP (M) SDN BHD today\n", "EXAMPLE IP (M) SDN BHD"),
    ("paid to Example Berhad today\n", "Example Berhad"),
    ("engaged Example Partners S.r.l. as agent\n", "Example Partners S.r.l"),
    ("chuyển qua Ngân hàng TMCP Mẫu Thử Việt Nam\n", "Ngân hàng TMCP Mẫu Thử Việt Nam"),
    ("See Example Holdings Ltd v. Other Corp\n", "Example Holdings Ltd"),
])
def test_a_name_with_an_organisation_marker_is_an_organisation(text, org):
    assert ("ORG", org) in [(c, v) for c, t, v in found(text)]
    assert [v for c, t, v in found(text) if c == "PERSON"] == []


@pytest.mark.parametrize("text", [
    "The Law Firm shall keep records.\n",
    "Entity: LIMITED LIABILITY COMPANY\n",
    "một Công ty Luật Sở hữu trí tuệ tại Hoa Kỳ\n",
])
def test_a_legal_form_alone_names_no_organisation(text):
    assert [v for c, t, v in found(text) if c == "ORG"] == []


@pytest.mark.parametrize("text, org", [
    ("Applicant: EXAMPLE COMPANY LIMITED\n", "EXAMPLE COMPANY LIMITED"),
    ("Owner Name: Example Holdings LLC\n", "Example Holdings LLC"),
    ("Correspondent: Example Partners S.r.l\n", "Example Partners S.r.l"),
    ("Account Name: EXAMPLE IP (M) SDN BHD\n", "EXAMPLE IP (M) SDN BHD"),
    ("Chủ đơn: Công ty TNHH Mẫu Thử\n", "Công ty TNHH Mẫu Thử"),
    ("Company name: Example Co., Ltd\n", "Example Co., Ltd"),
])
def test_an_organisation_under_a_persons_label_is_an_organisation(text, org):
    assert [(c, v) for c, t, v in found(text)] == [("ORG", org)]


def test_a_company_name_wrapped_after_its_legal_form_is_one_organisation():
    text = "CÔNG TY TNHH SẢN XUẤT THƯƠNG MẠI\nMẪU THỬ VÀ HƯ CẤU\nTrụ sở: 1 Đường Mẫu\n"
    assert ("ORG", "CÔNG TY TNHH SẢN XUẤT THƯƠNG MẠI\nMẪU THỬ VÀ HƯ CẤU") in [
        (c, v) for c, t, v in found(text)]


@pytest.mark.parametrize("text, short", [
    ("Account Name: EXAMPLE IP (M) SDN BHD\nPlease pay Example IP by Friday.\n", "Example IP"),
    ("Party A: Example - Law Firm\nExample will file the application.\n", "Example"),
    ("Chủ đơn: Công ty TNHH Mẫu Thử\nMẪU THỬ đã ký hợp đồng.\n", "MẪU THỬ"),
    # A company named after a place is sought with the place.
    ("Chủ đơn: Công ty TNHH Mẫu Hà Nội\nMẪU HÀ NỘI đã ký.\n", "MẪU HÀ NỘI"),
])
def test_an_organisations_short_name_wears_its_token(text, short):
    at = text.rindex(short)
    hits = [h for h in extract(text) if h.start == at]
    assert [(h.category, text[h.start:h.end]) for h in hits] == [("ORG", short)]
    full = next(h for h in extract(text) if h.category == "ORG" and h.start < at)
    assert hits[0].canonical == text[full.start:full.end]


@pytest.mark.parametrize("text", [
    "Other Corp filed.\nThe other party agreed.\n",               # a common word, lower case
    "Vietnam Co., Ltd\nMade in Vietnam.\n",                      # a country
    "CORRESPONDENCE RECEIVED IN LAW OFFICE\nLAW OFFICE 101\n",   # a docket event
])
def test_a_short_name_that_names_no_one_is_not_sought_again(text):
    orgs = [text[h.start:h.end] for h in extract(text) if h.category == "ORG"]
    assert all(len(v.split()) > 1 for v in orgs), orgs
    assert "CORRESPONDENCE" not in " ".join(orgs)


@pytest.mark.parametrize("text, org", [
    # A colon-less form row: the caption is no part of the name.
    ("Name EXAMPLE TRADING COMPANY LIMITED\n", "EXAMPLE TRADING COMPANY LIMITED"),
    ("Applicant Example Holdings LLC\n", "Example Holdings LLC"),
    # Two companies on one line are two.
    ("CÔNG TY TNHH MẪU THỬ CÔNG TY LUẬT TNHH HƯ CẤU\n", "CÔNG TY TNHH MẪU THỬ"),
])
def test_an_organisation_starts_at_its_own_name(text, org):
    assert ("ORG", org) in [(c, v) for c, t, v in found(text)]


@pytest.mark.parametrize("text, org", [
    # The name wraps in the letterhead; the address line ends it.
    ("CÔNG TY TNHH THƯƠNG MẠI MẪU THỬ VẬN \nTẢI HƯ CẤU \nTrụ sở: 1 Đường Mẫu\n",
     "CÔNG TY TNHH THƯƠNG MẠI MẪU THỬ VẬN \nTẢI HƯ CẤU"),
    # A bank transfer prints it unaccented over three lines.
    ("↘\nCTY TNHH TM DV\nMAU THU\nHU CAU\n\n\n+ VND 1,000\n", "CTY TNHH TM DV\nMAU THU\nHU CAU"),
    ("+VND 1,000\nCTTNHH TMDV MAU THU HU CAU\n", "CTTNHH TMDV MAU THU HU CAU"),
    # A place is a name; only a country makes a kind of firm.
    ("CÔNG TY TNHH HOÀN KIẾM\n", "CÔNG TY TNHH HOÀN KIẾM"),
])
def test_a_capitals_company_name_is_read_whole(text, org):
    assert ("ORG", org) in [(c, v) for c, t, v in found(text)]


@pytest.mark.parametrize("text, org", [
    ("CÔNG TY TNHH MẪU THỬ\nHỢP ĐỒNG DỊCH VỤ PHÁP LÝ\n", "CÔNG TY TNHH MẪU THỬ"),
    ("CÔNG TY TNHH MẪU THỬ\nCỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n", "CÔNG TY TNHH MẪU THỬ"),
    ("CÔNG TY TNHH MẪU THỬ\nL18-11, TẦNG 18\n", "CÔNG TY TNHH MẪU THỬ"),
    ("CÔNG TY LUẬT TNHH HƯ CẤU\nLÊ GIẢ ĐỊNH\n", "CÔNG TY LUẬT TNHH HƯ CẤU"),
])
def test_the_line_after_a_company_is_not_its_name(text, org):
    assert [v for c, t, v in found(text) if c == "ORG"] == [org]


@pytest.mark.parametrize("text, org", [
    ("Các bên.\n\n[STAMPED]\nMAU THU TRADING\n\n", "MAU THU TRADING"),
    ("[SEALED][SIGNED]\nHƯ CẤU GIẢ ĐỊNH\n", "HƯ CẤU GIẢ ĐỊNH"),
])
def test_the_name_a_stamp_reads_is_an_organisation(text, org):
    assert ("ORG", org) in [(c, v) for c, t, v in found(text)]


@pytest.mark.parametrize("text", [
    "[STAMPED]\nS.Đ.K.H.Đ. 0100\n",
    "[STAMPED]\nNGUYỄN VĂN MẪU\n",
    "[STAMPED]\nCỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n",
    "[STAMPED]\nĐẠI DIỆN BÊN A\n",
    "[STAMPED]\nTM. ỦY BAN NHÂN DÂN\n",
    "[STAMP]\nSỞ KẾ HOẠCH VÀ ĐẦU TƯ\n",
])
def test_a_stamp_line_that_names_no_company_is_no_organisation(text):
    assert [v for c, t, v in found(text) if c == "ORG"] == []


def test_a_company_name_in_sentence_case_is_read_whole():
    text = "ủy quyền giữa Công ty TNHH\nThương mại dịch vụ vận tải và Công nghệ Mẫu Thử và Bên B.\n"
    assert ("ORG", "Công ty TNHH\nThương mại dịch vụ vận tải và Công nghệ Mẫu Thử") in [
        (c, v) for c, t, v in found(text)]


def test_the_line_under_two_companies_finishes_neither():
    text = "CÔNG TY TNHH MẪU THỬ CÔNG TY LUẬT TNHH HƯ CẤU\nVẬN TẢI GIẢ ĐỊNH\n"
    assert [v for c, t, v in found(text) if c == "ORG"] == [
        "CÔNG TY TNHH MẪU THỬ", "CÔNG TY LUẬT TNHH HƯ CẤU"]


def test_a_kind_of_firm_in_a_country_is_no_organisation():
    text = "Chúng tôi thuê một Công ty Luật Sở hữu trí tuệ Hoa Kỳ.\n"
    assert [v for c, t, v in found(text) if c == "ORG"] == []


@pytest.mark.parametrize("seed, prose", [
    ("MẪU THỬ VÀ HƯ CẤU\nTRADING COMPANY LIMITED\n", "TRADING hours are long.\n"),
    ("CÔNG TY TNHH SẢN XUẤT THƯƠNG MẠI MẪU\n", "Mẫu mới.\n"),
    ("CÔNG TY LUẬT TNHH HƯ CẤU Q\n", "Q là chữ cái.\n"),
])
def test_a_generic_word_left_of_an_organisation_is_not_sought_again(seed, prose):
    text = seed + prose
    at = len(seed)
    assert [h for h in extract(text) if h.start >= at] == []


@pytest.mark.parametrize("text, category, value", [
    ("(Last name): Placeholder\n", "PERSON", "Placeholder"),
    ("Họ (Last name): Placeholder\n", "PERSON", "Placeholder"),
    ("[Full name]: John Placeholder\n", "PERSON", "John Placeholder"),
    ("Address: 1 Mau Street, Hư Cấu, 700000 (Mailing address): 2 Mau Street\n",
     "ADDRESS", "2 Mau Street"),
])
def test_a_caption_in_brackets_is_still_a_caption(text, category, value):
    assert (category, value) in [(c, v) for c, t, v in found(text)]


@pytest.mark.parametrize("text", [
    "Type of Mark: TRADEMARK\n",
    "Mark Type: SERVICE MARK\n",
    "Tra cứu nhãn hiệu chữ: $500 tương đương với 12.345.600 VNĐ\n",
])
def test_a_caption_about_a_mark_is_no_mark(text):
    assert [v for c, t, v in found(text) if c == "MARK"] == []


def test_the_description_of_a_mark_still_hides_the_mark():
    text = "Mark: HƯ CẤU\nDescription of Mark: The mark consists of the words HƯ CẤU.\n"
    at = text.rindex("HƯ CẤU")
    assert any(h.category == "MARK" and h.start <= at and h.end >= at + 6
               for h in extract(text))


def test_a_parenthesis_closing_prose_is_no_caption():
    text = "Party A serves the client of Party B (Applicant): Seeking\nregistration.\n"
    assert [c for c, t, v in found(text) if c == "PERSON"] == []


@pytest.mark.parametrize("text, name", [
    ("To: J. Mau Placeholder(mau.placeholder@example.com)\n", "J. Mau Placeholder"),
    ("From: Mau Placeholder <mau.placeholder@example.com>\n", "Mau Placeholder"),
])
def test_the_name_an_email_header_gives_its_address_is_a_person(text, name):
    assert ("PERSON", name) in [(c, v) for c, t, v in found(text)]


def test_a_name_with_a_middle_initial_is_found_again_whole():
    text = "Attorney Name: Mau T. Placeholder\nPlease ask Mau T. Placeholder today.\n"
    at = text.rindex("Mau T.")
    assert [(c, v) for c, t, v in found(text) if c == "PERSON"][-1] == ("PERSON", "Mau T. Placeholder")
    assert any(h.start == at and h.category == "PERSON" for h in extract(text))


def test_a_printed_timestamp_is_a_date():
    text = "Generated on: This page was generated on Tue Mar 5 09:12:30 ET 2024\n"
    assert ("DATE", "Tue Mar 5 09:12:30 ET 2024") in [(c, v) for c, t, v in found(text)]
