"""Case variables: the matter's own facts, matched in whatever shape the
document wrote them. Every value here is invented."""
from __future__ import annotations

import pytest

from pii_core import Policy, redact_document
from pii_core.casevars import CaseVar, find_vars, parse_vars

VARS = {
    "Tên KH": "Thị Mộng Vân Quách",
    "Mã hồ sơ": "hc1023.test",
    "Nhãn hiệu": "MAUMAUOI",
}


def spans(text: str, raw=VARS) -> list[tuple[str, str]]:
    return [(text[s:e], var.name) for s, e, var in find_vars(text, parse_vars(raw))]


def test_the_label_names_the_category():
    got = {v.name: v.category for v in parse_vars(VARS)}
    assert got == {"Tên KH": "PERSON", "Mã hồ sơ": "MATTER_REF",
                   "Nhãn hiệu": "MARK"}


def test_the_caller_may_say_the_category():
    (var,) = parse_vars([{"name": "X", "value": "Mẫu Thử", "category": "ORG"}])
    assert (var.category, var.value) == ("ORG", "Mẫu Thử")


def test_a_value_with_no_useful_label_is_read_by_its_own_shape():
    (var,) = parse_vars({"Ghi chú": "mau.nguyen@example.test"})
    assert var.category == "EMAIL"


@pytest.mark.parametrize("written", [
    "Thị Mộng Vân Quách",       # as the caller gave it
    "THỊ MỘNG VÂN QUÁCH",       # shouted
    "thi mong van quach",       # OCR dropped the diacritics
    "Thi  Mong  Van  Quach",    # and doubled the spaces
    "Thị Mộng Vân Quách,",      # with punctuation after
])
def test_a_client_name_is_found_in_every_shape(written):
    text = f"Kính gửi {written} về hồ sơ."
    assert [name for _, name in spans(text)] == ["Tên KH"]


def test_a_joined_unaccented_mention_is_found():
    # The leak of 2026-09-24: an OCR'd chat line writing the name joined,
    # without diacritics, after an @.
    assert spans("Chào @Mongvan Quach, đã nhận.") == [("Mongvan Quach", "Tên KH")]


def test_one_typo_in_a_mark_is_still_the_mark():
    assert spans("Nhãn hiệu MAUMAUOL đã nộp.") == [("MAUMAUOL", "Nhãn hiệu")]


def test_a_code_is_never_fuzzed():
    # One digit apart, two matter codes are two different matters.
    assert spans("Hồ sơ HC1024.TEST của khách khác.") == []
    assert spans("Hồ sơ HC1023.TEST của ta.") == [("HC1023.TEST", "Mã hồ sơ")]


@pytest.mark.parametrize("text", [
    "vân gỗ tự nhiên",                 # a word of the name, alone
    "giấc mộng giữa trưa",
    "quyết định thi hành án",          # two words, near a part of the name
    "gửi mail cho văn phòng",
    "mẫu mã sản phẩm",
])
def test_everyday_words_are_not_the_client(text):
    assert spans(text) == []


def test_a_short_value_is_not_looked_for():
    # "Lý" alone would match every third line.
    assert spans("lý do nộp đơn", {"Tên KH": "Lý"}) == []


def test_a_part_of_a_name_needs_three_words():
    raw = {"Tên KH": "Thành Công Nguyễn"}
    # "Thành Công" on its own is an everyday phrase, and two words of a
    # three-word name are not looked for.
    assert spans("dự án thành công rực rỡ", raw) == []
    assert spans("ông Thành Công Nguyễn ký", raw) == [("Thành Công Nguyễn", "Tên KH")]


def test_every_shape_of_one_variable_wears_one_token():
    policy = Policy("synthetic-test-key-not-a-secret")
    text = ("Kính gửi Thị Mộng Vân Quách.\nChào @Mongvan Quach.\n"
            "Nhãn hiệu MAUMAUOI và MAUMAUOL.\n")
    result = redact_document(text, policy, group="CASE",
                             case_vars=parse_vars(VARS))
    assert "Mongvan" not in result.text and "Mộng" not in result.text
    assert "MAUMAUOI" not in result.text and "MAUMAUOL" not in result.text
    # one PERSON token for both mentions, one MARK token for both spellings
    persons = {t for t in _tokens(result.text) if t.startswith("PERSON")}
    marks = {t for t in _tokens(result.text) if t.startswith("MARK")}
    assert len(persons) == 1 and len(marks) == 1


def _tokens(text: str) -> list[str]:
    import re
    return re.findall(r"\[([A-Z_]+-[0-9a-f]+)\]", text)


def test_the_vault_restores_the_form_the_caller_gave():
    policy = Policy("synthetic-test-key-not-a-secret")
    result = redact_document("Chào @Mongvan Quach.", policy, group="CASE",
                             case_vars=parse_vars(VARS))
    (token,) = _tokens(result.text)
    assert result.vault.tokens[f"[{token}]"]["value"] == "Thị Mộng Vân Quách"


def test_the_roster_still_wins():
    # An opposing party passed as a case variable wears its roster token, not
    # the variable's: the roster is pinned above the case variables.
    from pii_core import Roster
    roster = Roster.from_rows([{"name": "Công ty Cổ phần Công Khai Mẫu",
                                "category": "PARTY"}])
    policy = Policy("synthetic-test-key-not-a-secret", roster=roster)
    text = "Bên bị: Công ty Cổ phần Công Khai Mẫu."
    result = redact_document(text, policy, group="CASE", case_vars=parse_vars(
        {"Đối thủ": "Công ty Cổ phần Công Khai Mẫu"}))
    assert "Công ty Cổ phần Công Khai Mẫu" not in result.text
    assert "[PARTY-" in result.text
    assert [f.matched_by for f in result.fields] == ["roster"]


def test_bad_input_is_refused():
    with pytest.raises(ValueError):
        parse_vars(["no-equals-sign"])
    assert parse_vars(None) == () and parse_vars({}) == ()
    assert parse_vars([CaseVar("X", "Mẫu Thử Mãi", "PERSON")])[0].category == "PERSON"
