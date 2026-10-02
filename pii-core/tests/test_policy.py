"""The field-level API: (label, value) -> action + reason."""
from __future__ import annotations

import pytest

from pii_core import Policy, Roster
from pii_core.labels import category_for_label

from conftest import KEY


@pytest.mark.parametrize("label, category", [
    ("Họ và tên", "PERSON"), ("Ho va ten", "PERSON"), ("Full name", "PERSON"),
    ("Số CCCD", "NATIONAL_ID"), ("Địa chỉ", "ADDRESS"), ("Email", "EMAIL"),
    ("Điện thoại", "PHONE"), ("Mã số thuế", "TAX_CODE"), ("Ngày sinh", "BIRTH_DATE"),
    ("Sinh ngày", "BIRTH_DATE"), ("Ngày, tháng, năm sinh", "BIRTH_DATE"),
    ("Ngày sinh / Date of birth", "BIRTH_DATE"), ("Date of birth", "BIRTH_DATE"),
    ("DOB", "BIRTH_DATE"), ("Năm sinh", "BIRTH_DATE"), ("Ngày nộp đơn", "DATE"),
    ("Filing date", "DATE"), ("Ngày cấp", "DATE"),
    ("Số đơn", "APP_SERIAL"), ("Ghi chú", None),
])
def test_label_declares_category(label, category):
    assert category_for_label(label) == category


def test_person_is_pseudonymised_with_a_stable_token(policy):
    a = policy.field("Họ và tên", "Nguyễn Văn Mẫu", "c1")
    b = policy.field("Full name", "NGUYỄN  VĂN MẪU", "c2")
    assert a.action == "PSEUDONYMISE" and a.category == "PERSON"
    assert a.after.startswith("[PERSON-") and a.after == b.after
    assert a.tokens == {a.after: {"category": "PERSON", "value": "Nguyễn Văn Mẫu"}}
    assert "Họ và tên" in a.reason and "PERSON" in a.reason


def test_a_different_key_gives_unrelated_tokens(policy):
    other = Policy(KEY + "-other")
    assert (policy.field("Họ và tên", "Nguyễn Văn Mẫu").after
            != other.field("Họ và tên", "Nguyễn Văn Mẫu").after)


def test_same_string_as_two_categories_gets_two_tokens(policy):
    assert policy.token("PERSON", "Mẫu Thử") != policy.token("ORG", "Mẫu Thử")


def test_national_id_is_anonymised_and_leaves_no_vault_row(policy):
    r = policy.field("Số CCCD", "001099000001")
    assert (r.action, r.after, r.tokens) == ("ANONYMISE", "[NATIONAL_ID]", {})


def test_a_procedural_date_is_tokenised_not_shifted(policy):
    # The firm, 2026-09-28 (P1): one known pair of real dates gives away a
    # case-wide shift, so a procedural date wears a token instead.
    r = policy.field("Ngày nộp đơn", "05/03/2024", "c1")
    assert (r.action, r.category) == ("PSEUDONYMISE", "DATE")
    assert r.after.startswith("[DATE-") and "2024" not in r.after
    assert r.tokens == {r.after: {"category": "DATE", "value": "05/03/2024"}}


def test_one_date_wears_one_token_however_it_is_written(policy):
    tokens = {policy.field("Ngày nộp đơn", v, "c1").after
              for v in ("05/03/2024", "5.3.2024", "ngày 5 tháng 3 năm 2024",
                        "2024-03-05", "March 5, 2024")}
    assert len(tokens) == 1
    assert policy.field("Ngày nộp đơn", "06/03/2024").after not in tokens


def test_an_unparseable_procedural_date_is_still_restorable(policy):
    r = policy.field("Ngày nộp đơn", "đầu năm ngoái")
    assert r.after.startswith("[DATE-") and r.tokens[r.after]["value"] == "đầu năm ngoái"


def test_a_birth_date_is_anonymised(policy):
    # P1: no stage reads a date of birth back, so it leaves no vault row.
    for label in ("Ngày sinh", "Date of birth", "Năm sinh"):
        r = policy.field(label, "05/03/1990", "c1")
        assert (r.category, r.action, r.after, r.tokens) == \
            ("BIRTH_DATE", "ANONYMISE", "[BIRTH_DATE]", {}), label


def test_a_residence_is_anonymised(policy):
    # P3: GEO stays ANONYMISE; ocr-lab's PSEUDONYMISE override is not adopted.
    r = policy.apply_as("GEO", "Phường Mẫu, Quận Thử")
    assert (r.action, r.after, r.tokens) == ("ANONYMISE", "[GEO]", {})


def test_register_numbers_are_tokenised(policy):
    for label, value, code in (("Số đơn", "4-2024-12345", "APP_SERIAL"),
                               ("Số văn bằng", "VB-00001", "REG_NUMBER")):
        r = policy.field(label, value)
        assert (r.action, r.category) == ("PSEUDONYMISE", code)
        assert r.after.startswith(f"[{code}-") and value not in r.after


def test_a_mark_name_is_tokenised(policy):
    for label in ("Tên nhãn hiệu", "Nhãn hiệu", "Trademark name", "Brand"):
        r = policy.field(label, "HƯ CẤU")
        assert (r.action, r.category) == ("PSEUDONYMISE", "MARK"), label
        assert r.after.startswith("[MARK-")


def test_blank_and_token_values_pass_unchanged(policy):
    assert policy.field("Họ và tên", "N/A").after == "N/A"
    token = policy.field("Họ và tên", "Nguyễn Văn Mẫu").after
    again = policy.field("Họ và tên", token)
    assert again.after == token and again.tokens == {}


def test_unknown_category_fails_closed(policy):
    r = policy.apply_as("NOT_A_CATEGORY", "anything")
    assert (r.action, r.after) == ("REMOVE", "")


def test_unlabelled_value_is_still_scanned(policy):
    r = policy.field("Ghi chú", "gọi 0900 000 001 hoặc mau.nguyen@example.test")
    assert r.action == "PSEUDONYMISE" and r.matched_by == "pattern"
    assert "0900 000 001" not in r.after and "example.test" not in r.after
    assert r.after.startswith("gọi [PHONE-")
    assert {row["category"] for row in r.tokens.values()} == {"PHONE", "EMAIL"}


def test_unlabelled_harmless_value_is_kept(policy):
    r = policy.field("Ghi chú", "nộp bổ sung tài liệu")
    assert (r.action, r.category, r.after) == ("KEEP", None, "nộp bổ sung tài liệu")


def test_not_pii_label_keeps_the_value(policy):
    r = policy.field("Tên sản phẩm", "HƯ CẤU")
    assert (r.action, r.after, r.matched_by) == ("KEEP", "HƯ CẤU", "label:not-pii")


def test_roster_wins_over_the_label(roster):
    policy = Policy(KEY, roster=roster)
    r = policy.field("Họ và tên", "cong khai mau jsc")
    # P2: an opposing party is tokenised, under its roster name, so the alias
    # and the full name are one token and restore as the roster name.
    assert (r.action, r.category, r.matched_by) == ("PSEUDONYMISE", "PARTY", "roster")
    full = policy.field("Tên công ty", "Công ty Cổ phần Công Khai Mẫu")
    assert r.after == full.after and r.after.startswith("[PARTY-")
    assert r.tokens[r.after] == {"category": "PARTY",
                                 "value": "Công ty Cổ phần Công Khai Mẫu"}
    assert "roster" in r.reason
    # Whole-value only: a client whose name CONTAINS a public name is a client.
    r = policy.field("Tên công ty", "Công ty Cổ phần Công Khai Mẫu Miền Nam")
    assert r.action == "PSEUDONYMISE"


def test_internal_staff_on_the_roster_are_not_clients(roster):
    # Dry run 2026-09-24, finding 6: with no roster every internal name is
    # treated as a client's and tokenised out of the firm's own memo.
    policy = Policy(KEY, roster=roster)
    assert policy.field("Luật sư phụ trách", "Lê Giả Định").action == "KEEP"
    assert Policy(KEY).field("Luật sư phụ trách", "Lê Giả Định").action \
        == "PSEUDONYMISE"


def test_an_agency_is_tokenised_as_itself(roster):
    # P2: the agency is pseudonymised too, as AGENCY and not as a client ORG.
    policy = Policy(KEY, roster=roster)
    r = policy.field("Nơi nhận", "Cục Thẩm Định Hư Cấu")
    assert (r.action, r.category) == ("PSEUDONYMISE", "AGENCY")
    assert r.after == policy.field("Nơi nhận", "CTĐHC").after


def test_a_roster_path_that_does_not_load_says_so():
    with pytest.raises(ValueError, match="roster file"):
        Roster.load("/nonexistent/roster.json")


def test_empty_roster_is_the_default(policy):
    assert len(policy.roster) == 0


def test_roster_rejects_other_categories():
    with pytest.raises(ValueError):
        Roster.from_rows([{"name": "Ai Đó", "category": "PERSON"}])


def test_key_is_required():
    with pytest.raises(ValueError):
        Policy("")


def test_provisional_categories_say_so(policy):
    r = policy.field("Số hoá đơn", "0000123")
    assert r.provisional and "ĐỀ XUẤT" in r.reason
    assert not policy.field("Ngày sinh", "05/03/1990").provisional


def test_an_invoice_lookup_code_is_an_invoice_identifier(policy):
    r = policy.field("Mã tra cứu", "QXMAUTHU")
    assert (r.category, r.action) == ("INVOICE_NO", "PSEUDONYMISE")
    assert "QXMAUTHU" not in r.after
