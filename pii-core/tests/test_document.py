"""The document-level entry point, end to end on an invented case document."""
from __future__ import annotations

import json
import re
import stat

import pytest

from pii_core import Policy, Vault, VaultError, redact_case, redact_document, restore
from pii_core.parties import Roster

from conftest import KEY


def test_nothing_on_the_register_survives(policy, case_text, register):
    result = redact_document(case_text, policy, group="CASE-1")
    for value in register["must_not_survive"]:
        assert value not in result.text, value
    for value in register["must_survive"]:
        assert value in result.text, value
    assert result.residue == [] and result.summary["ok"]


def test_the_audit_carries_no_original_value(policy, case_text, register):
    result = redact_document(case_text, policy, group="CASE-1")
    audit = json.dumps(result.as_dict(include_vault=False), ensure_ascii=False)
    for value in register["must_not_survive"]:
        assert value not in audit, value


def test_every_field_says_what_and_why(policy, case_text):
    result = redact_document(case_text, policy, group="CASE-1")
    assert result.fields
    for f in result.fields:
        assert f.action in {"KEEP", "PSEUDONYMISE", "ANONYMISE", "REMOVE"}
        assert f.reason and f.matched_by
        assert case_text[f.start:f.end]            # spans index the INPUT
    labels = {f.label for f in result.fields if f.matched_by == "label"}
    assert "Họ và tên" in labels


def test_round_trip_restores_all_but_the_irreversible(policy, case_text, register):
    result = redact_document(case_text, policy, group="CASE-1")
    back = restore(result.text, result.vault)
    for value in register["must_not_survive"]:
        if value in register["irreversible"]:
            assert value not in back
        else:
            assert value in back, value
    assert back == case_text.replace("001099000001", "[NATIONAL_ID]") \
        .replace("05/03/1990", "[BIRTH_DATE]")


def test_the_vault_holds_only_pseudonymised_values(policy, case_text):
    vault = redact_document(case_text, policy, group="CASE-1").vault
    values = {row["value"] for row in vault.tokens.values()}
    assert "001099000001" not in values          # anonymised: never stored
    assert "Nguyễn Văn Mẫu" in values
    assert vault.group == "CASE-1"
    # Dates are tokens now (P1): nothing was shifted, so no offset is kept.
    assert (vault.date_shift_days, vault.dates) == (0, {})
    assert "05/03/1990" not in values            # a birth date: anonymised


def test_procedural_dates_are_tokens_and_birth_dates_are_gone(policy):
    text = ("Ông Mẫu, sinh ngày 05/03/1990, nộp đơn ngày 02/02/2024; "
            "thông báo ngày 2 tháng 2 năm 2024. Khoản phí phát sinh ngày 03/03/2024.\n")
    result = redact_document(text, policy, group="CASE-1")
    assert "[BIRTH_DATE]" in result.text
    for real in ("1990", "2024"):
        assert real not in result.text
    date_tokens = [t for t, row in result.vault.tokens.items() if row["category"] == "DATE"]
    # 02/02/2024 written two ways is one token; the fee date is another.
    assert len(date_tokens) == 2
    assert result.text.count(date_tokens[0]) + result.text.count(date_tokens[1]) == 3
    # One token restores one form: the one the case wrote first.
    assert restore(result.text, result.vault) == text.replace(
        "05/03/1990", "[BIRTH_DATE]").replace("ngày 2 tháng 2 năm 2024", "02/02/2024")


def test_a_literal_date_in_the_answer_is_left_alone(policy):
    # No shift: a date the agent wrote itself is not moved anywhere.
    vault = redact_document("Ngày nộp: 05/03/2024\n", policy, group="CASE-1").vault
    assert restore("hạn chót 04/04/2024", vault) == "hạn chót 04/04/2024"


def test_a_vault_from_before_the_ruling_still_restores(policy):
    shift = policy.date_shift("CASE-1")
    legacy = Vault(group="CASE-1", date_shift_days=shift,
                   dates={"15/03/2024": "05/03/2024"})
    assert restore("nộp 15/03/2024", legacy) == "nộp 05/03/2024"
    # And a case may carry on with it: new dates become tokens beside it.
    later = redact_document("Ngày nộp: 06/03/2024\n", policy, group="CASE-1",
                            vault=legacy)
    assert later.vault.date_shift_days == shift and "[DATE-" in later.text
    assert restore(later.text, later.vault) == "Ngày nộp: 06/03/2024\n"
    with pytest.raises(VaultError):
        redact_document("x", policy, group="CASE-1",
                        vault=Vault(group="CASE-1", date_shift_days=shift + 1))


def test_one_case_across_documents_shares_a_vault(policy):
    first = redact_document("Họ và tên: Nguyễn Văn Mẫu\n", policy, group="CASE-1")
    second = redact_document("Ông Nguyễn Văn Mẫu đã ký.\n", policy, group="CASE-1",
                             vault=first.vault)
    token = next(iter(first.vault.tokens))
    assert token in first.text and token in second.text
    assert len(second.vault.tokens) == 1


def test_a_mark_wears_one_token_across_the_case(policy):
    docs = ["Ý kiến: Hư Cấu trùng với nhãn đã đăng ký.\n",
            "Tên nhãn hiệu: HƯ CẤU\nSố đơn: 4-2024-12345\n"]
    first, second = redact_case(docs, policy, group="CASE-1")
    mark = [t for t, row in second.vault.tokens.items() if row["category"] == "MARK"]
    assert len(mark) == 1 and mark[0] in first.text and mark[0] in second.text
    assert "Hư Cấu" not in first.text and "4-2024-12345" not in second.text
    assert restore(first.text, second.vault) == docs[0]


def test_a_matter_code_in_the_vault_is_sought_again(policy):
    lead = redact_document("Mã hồ sơ: MAU.THU-7\n", policy, group="CASE-1")
    (token,) = lead.vault.tokens
    later = redact_document("Về hồ sơ MAU.THU-7 và mau.thu-7, xin xem lại.\n", policy,
                            group="CASE-1", vault=lead.vault)
    assert later.text == f"Về hồ sơ {token} và {token}, xin xem lại.\n"
    assert set(later.vault.tokens) == {token}
    assert restore(later.text, later.vault) == "Về hồ sơ MAU.THU-7 và MAU.THU-7, xin xem lại.\n"


def test_a_matter_code_wears_one_token_across_the_case(policy):
    docs = ["Kính gửi, về hồ sơ MAU.THU-7.\n", "Số hồ sơ: MAU.THU-7\n"]
    first, second = redact_case(docs, policy, group="CASE-1")
    (token,) = second.vault.tokens
    assert token in first.text and "MAU.THU-7" not in first.text


def test_a_token_under_a_label_is_not_wrapped_again(policy):
    lead = redact_document("Tên chủ đơn: Nguyễn Văn Mẫu\n", policy, group="CASE-1")
    (token,) = lead.vault.tokens
    for text in (f"Người nhận: {token}\n", f"Người nhận: {token}, Hà Thử\n",
                 f"| Người nhận | {token} |\n"):
        later = redact_document(text, policy, group="CASE-1", vault=lead.vault)
        assert "[[" not in later.text and token in later.text, later.text
        back = restore(later.text, later.vault)
        assert "Nguyễn Văn Mẫu" in back and "PERSON" not in back, back
        # An extra pass, as a caller that once needed several makes, changes nothing.
        assert restore(back, later.vault, unshift_dates=False) == back


def test_a_text_that_ends_on_a_known_given_name_is_redacted(policy):
    result = redact_document("Họ và tên: Nguyễn Thị Vân\nCảm ơn chị Vân", policy)
    assert "Vân" not in result.text


def test_a_guess_in_one_document_is_not_sought_in_the_next(policy):
    # A heading read as a two-word name is a guess: in the case it must not
    # become a name to look for, or every later "phạm vi" (scope) is one.
    docs = ["PHẠM VI\n", "Trong phạm vi hợp đồng này.\n"]
    first, second = redact_case(docs, policy, group="CASE-1")
    assert second.text == docs[1]


def test_the_callers_vault_still_seeds_the_case(policy):
    lead = redact_document("Họ và tên: Nguyễn Văn Mẫu\n", policy, group="CASE-1")
    (token,) = lead.vault.tokens
    (later,) = redact_case(["gửi anh Mẫu hôm nay.\n"], policy, group="CASE-1",
                           vault=lead.vault)
    assert later.text == f"gửi anh {token} hôm nay.\n"


def test_an_organisations_short_name_wears_its_token_across_the_case(policy):
    docs = ["Mẫu Thử đã ký.\n", "Chủ đơn: Công ty TNHH Mẫu Thử\n"]
    first, second = redact_case(docs, policy, group="CASE-1")
    (token,) = second.vault.tokens
    assert first.text == f"{token} đã ký.\n"
    assert restore(first.text, second.vault) == "Công ty TNHH Mẫu Thử đã ký.\n"


def test_a_vault_from_another_case_is_refused(policy):
    vault = redact_document("x", policy, group="CASE-1").vault
    with pytest.raises(VaultError):
        redact_document("x", policy, group="CASE-2", vault=vault)


def test_colliding_tokens_are_refused():
    vault = Vault(tokens={"[PERSON-0000000000]": {"category": "PERSON", "value": "A"}})
    with pytest.raises(VaultError):
        vault.add_tokens({"[PERSON-0000000000]": {"category": "PERSON", "value": "B"}})


def test_vault_file_round_trip_is_private(policy, case_text, tmp_path):
    vault = redact_document(case_text, policy, group="CASE-1").vault
    path = tmp_path / "case.vault.json"
    vault.save(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert Vault.load(path).as_dict() == vault.as_dict()


def test_source_file_name_is_treated(policy):
    result = redact_document("x", policy, source="Nguyen_Van_Mau_CCCD.pdf")
    assert result.source == "[SOURCE_FILE]"


def test_residue_flags_untreated_long_digit_runs(policy):
    result = redact_document("tham chiếu nội bộ 9876 5432 1098\n", policy)
    assert [r["matched_by"] for r in result.residue] == ["residue:digits"]
    assert not result.summary["ok"]


def test_a_price_under_a_mark_caption_leaves_no_residue(policy):
    # The second look reads the MONEY token where the price was.
    result = redact_document("Tra cứu nhãn hiệu chữ: $500 tương đương với 12.345.600 VNĐ\n",
                             policy)
    assert result.residue == []
    assert "tương đương với" in result.text


FIRM_TEXT = ("Party A: Hư Cấu - Law Firm\n"
             "HƯ CẤU LAW FIRM will file the application. Hư Cấu invoices monthly.\n")


def test_a_law_firm_on_the_roster_as_firm_stays_readable():
    roster = Roster.from_rows([{"name": "Hư Cấu", "category": "FIRM",
                                "why": "SYNTHETIC TEST DATA, not a real firm",
                                "aliases": ["Hư Cấu - Law Firm"]}])
    result = redact_document(FIRM_TEXT, Policy(KEY, roster=roster))
    assert result.text == FIRM_TEXT
    assert {f.as_dict()["action"] for f in result.fields} == {"KEEP"}


def test_a_law_firm_with_no_roster_is_one_organisation_token(policy):
    result = redact_document(FIRM_TEXT, policy)
    tokens = set(re.findall(r"\[ORG-[0-9a-f]+\]", result.text))
    assert len(tokens) == 1
    assert "Hư Cấu" not in result.text and "HƯ CẤU" not in result.text


def test_a_seal_naming_the_district_after_the_firm_wears_the_firms_token(policy):
    text = ("CÔNG TY LUẬT TNHH HƯ CẤU Q. HOÀN KIẾM - TP HÀ NỘI\n"
            "CÔNG TY LUẬT TNHH HƯ CẤU HOÀN KIẾM - HÀ NỘI\n")
    result = redact_document(text, policy)
    assert len(set(re.findall(r"\[ORG-[0-9a-f]+\]", result.text))) == 1


def test_the_firm_stays_readable_and_the_other_side_does_not(roster):
    # P2: the firm is kept; the opposing party and the agency are tokenised.
    policy = Policy(KEY, roster=roster)
    text = ("Bên bị: Công ty Cổ phần Công Khai Mẫu\nĐại diện: VPLS Hư Cấu và Cộng Sự\n"
            "Kính gửi: Cục Thẩm Định Hư Cấu\n")
    result = redact_document(text, policy, group="CASE-1")
    assert "VPLS Hư Cấu và Cộng Sự" in result.text
    assert "Công ty Cổ phần Công Khai Mẫu" not in result.text
    assert "Cục Thẩm Định Hư Cấu" not in result.text
    assert "[PARTY-" in result.text and "[AGENCY-" in result.text
    assert result.residue == []
    assert restore(result.text, result.vault) == text


def test_roster_names_are_found_in_running_text(roster):
    policy = Policy(KEY, roster=roster)
    text = ("Ông Trần Thị Thử kiện CONG TY CO PHAN CONG KHAI MAU (Cong Khai Mau JSC) "
            "hôm 05/03/2024 trước CTĐHC.\n")
    result = redact_document(text, policy, group="CASE-1")
    assert "CONG KHAI MAU" not in result.text and "Trần Thị Thử" not in result.text
    by_roster = [(f.category, f.action) for f in result.fields if f.matched_by == "roster"]
    assert by_roster == [("PARTY", "PSEUDONYMISE")] * 2 + [("AGENCY", "PSEUDONYMISE")]
    # Two spellings of one party: one token, restored as the roster name.
    party = [t for t, row in result.vault.tokens.items() if row["category"] == "PARTY"]
    assert len(party) == 1 and result.text.count(party[0]) == 2


def test_residue_stops_text_whose_font_map_garbled_it(policy):
    # A PDF text layer with a broken Vietnamese font map: Cyrillic letters
    # inside Latin words. No detector can read a name in it.
    result = redact_document("Tên thành viên\n4XӕFWӏFK WUөVӣFKtQK\n", policy)
    assert {r["matched_by"] for r in result.residue} == {"residue:garbled"}
    assert not result.summary["ok"]


def test_a_cyrillic_word_of_its_own_is_no_garbling(policy):
    result = redact_document("Văn phòng tại Москва, xem đơn.\n", policy)
    assert result.residue == []
