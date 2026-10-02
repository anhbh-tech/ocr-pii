"""The decision table: pii-lab's model, pii-lab's frozen outcome."""
from __future__ import annotations

import pytest

from pii_core.categories import BasisKind, Category, Harm, category
from pii_core.decide import (Action, Need, Reidentification, Risk, decide,
                             decisions, need_score, risk_of)

#: pii-lab's table as frozen at commit 3102d30 (`pii-lab decisions`).
PII_LAB_ACTIONS = {
    "MRZ": "REMOVE",
    "NATIONAL_ID": "ANONYMISE", "SOURCE_FILE": "ANONYMISE", "GEO": "ANONYMISE",
    "MONEY": "PSEUDONYMISE", "ADDRESS": "PSEUDONYMISE", "EMAIL": "PSEUDONYMISE",
    "ORG": "PSEUDONYMISE", "PERSON": "PSEUDONYMISE", "PHONE": "PSEUDONYMISE",
    "TAX_CODE": "PSEUDONYMISE", "DATE": "PSEUDONYMISE",
    "INVOICE_NO": "PSEUDONYMISE", "MATTER_REF": "PSEUDONYMISE",
    "OTHER_ID": "PSEUDONYMISE",
    "APP_SERIAL": "KEEP", "FIRM": "KEEP", "NICE_CLASS": "KEEP", "PARTY": "KEEP",
    "REG_NUMBER": "KEEP", "URL": "KEEP",
}

#: Where pii-core departs from that table, and why (docs/RECONCILIATION.md).
#: The firm, 2026-09-23: the register is public, but a number or a mark on it
#: leads to the applicant, and the lawyer–client relationship before filing is
#: not (Luật Luật sư Điều 25). L 0 -> 1; N was already 3.
DEPARTURES = {"APP_SERIAL": "PSEUDONYMISE", "REG_NUMBER": "PSEUDONYMISE",
              # The firm, 2026-09-28 (P2): which side the firm acts against is
              # information about the matter (Luật Luật sư Điều 25). L 0 -> 2,
              # N 0 -> 2 by declaration.
              "PARTY": "PSEUDONYMISE"}

#: The firm's 2026-09-28 rulings on the pipeline report (§2.3, §6), as rows
#: pii-lab never had.
RULED_2026_09_28 = {
    "BIRTH_DATE": "ANONYMISE", "AGENCY": "PSEUDONYMISE",
    "FACE_PHOTO": "REMOVE", "SIGNATURE": "REMOVE", "FINGERPRINT": "REMOVE",
    "SCAN_CODE": "REMOVE", "MARK_IMAGE": "REMOVE", "LOGO": "REMOVE",
}


def test_table_matches_pii_lab_but_for_the_departures():
    table = decisions()
    got = {code: d.action.name for code, d in table.items() if code in PII_LAB_ACTIONS}
    assert got == {**PII_LAB_ACTIONS, **DEPARTURES}


def test_the_additions_are_boilerplate_and_mark():
    extra = set(decisions()) - set(PII_LAB_ACTIONS) - set(RULED_2026_09_28)
    assert extra == {"BOILERPLATE", "MARK", "HOTLINE", "MACHINE_TRACE"}
    assert decisions()["BOILERPLATE"].action is Action.KEEP
    assert decisions()["MARK"].action is Action.PSEUDONYMISE
    # The two number kinds the digit sieve used to stop documents over: a
    # published switchboard stays readable, a machine trace does not.
    assert decisions()["HOTLINE"].action is Action.KEEP
    assert decisions()["MACHINE_TRACE"].action is Action.ANONYMISE


def test_register_values_cite_client_confidence():
    for code in ("APP_SERIAL", "REG_NUMBER", "MARK"):
        d = decisions()[code]
        assert "Điều 25" in d.harm_basis and d.settled, code
        assert (d.harm, d.n, d.risk) == (Harm.INTERNAL, 3 if code != "MARK" else 2,
                                          Risk.LOW), code


def test_a_mark_is_searchable_by_declaration_not_by_count():
    d = decisions()["MARK"]
    assert "KEEP_SEARCHABLE" in d.n_basis and "mất 0 dòng fact" in d.n_basis


def test_every_row_explains_itself():
    for d in decisions().values():
        assert d.why and d.harm_basis


def _cat(harm: Harm) -> Category:
    return Category("TEST", "test", True, harm, "invented basis", BasisKind.PROPOSED)


def _reid(distinct: int, singletons: int) -> Reidentification:
    return Reidentification("TEST", "test", distinct, singletons, 1)


@pytest.mark.parametrize("r, harm, risk", [
    (1.0, Harm.NONE, Risk.NONE), (0.9, Harm.INTERNAL, Risk.LOW),
    (0.9, Harm.PERSONAL, Risk.MEDIUM), (0.5, Harm.SENSITIVE, Risk.MEDIUM), (0.3, Harm.SENSITIVE, Risk.LOW),
    (0.8, Harm.SENSITIVE, Risk.HIGH), (0.0, Harm.SENSITIVE, Risk.NONE),
])
def test_risk_buckets(r, harm, risk):
    assert risk_of(r, harm) is risk


@pytest.mark.parametrize("need, n", [
    (Need("T"), 0), (Need("T", facts_lost=1), 1), (Need("T", links=49), 1),
    (Need("T", links=50), 2), (Need("T", facts_lost=100), 2),
    (Need("T", declared_searchable=True), 2), (Need("T", sole_anchor_for=1), 3),
])
def test_need_score(need, n):
    assert need_score(need) == n


def test_zero_harm_keeps_whatever_r_says():
    assert decide(_cat(Harm.NONE), _reid(100, 100), Need("T")).action is Action.KEEP


def test_strong_need_pseudonymises_even_at_high_risk():
    d = decide(_cat(Harm.SENSITIVE), _reid(100, 100), Need("T", links=60))
    assert (d.risk, d.action) == (Risk.HIGH, Action.PSEUDONYMISE)


def test_high_risk_weak_need_anonymises():
    d = decide(_cat(Harm.SENSITIVE), _reid(100, 100), Need("T", links=3))
    assert d.action is Action.ANONYMISE


def test_high_risk_no_need_removes():
    assert decide(_cat(Harm.SENSITIVE), None, Need("T")).action is Action.REMOVE


def test_moderate_risk_no_need_anonymises():
    assert decide(_cat(Harm.INTERNAL), None, Need("T")).action is Action.ANONYMISE


def test_unreliable_r_takes_the_worst_case():
    # 5 distinct values, 1 singleton: R would read 20%, but 5 < R_MIN_DISTINCT.
    d = decide(_cat(Harm.SENSITIVE), _reid(5, 1), Need("T", links=3))
    assert not d.r_measured and d.risk is Risk.HIGH
    assert "trường hợp xấu nhất" in d.why


#: L re-ranked against Nghị định 13; the actions stay pii-lab's
#: (docs/RECONCILIATION.md, "L departures from pii-lab").
@pytest.mark.parametrize("code, harm, risk, article", [
    ("BIRTH_DATE", Harm.PERSONAL, Risk.MEDIUM, "Điều 2.3(b)"),
    ("FACE_PHOTO", Harm.SENSITIVE, Risk.HIGH, "Điều 2.3(e)"),
    ("FINGERPRINT", Harm.SENSITIVE, Risk.HIGH, "Điều 2.4(đ)"),
    ("SCAN_CODE", Harm.SENSITIVE, Risk.HIGH, "Điều 2.3"),
    ("GEO", Harm.PERSONAL, Risk.MEDIUM, "Điều 2.3(d)"),
    ("OTHER_ID", Harm.SENSITIVE, Risk.HIGH, "Điều 2.4(h)"),
    ("MRZ", Harm.SENSITIVE, Risk.HIGH, "Điều 2.3"),
])
def test_re_ranked_l_cites_its_article(code, harm, risk, article):
    d = decisions()[code]
    assert (d.harm, d.risk, d.settled) == (harm, risk, True)
    assert article in d.harm_basis


def test_only_the_operational_ids_stay_proposed():
    proposed = {code for code, d in decisions().items() if not d.settled}
    assert proposed == {"INVOICE_NO", "MATTER_REF", "MACHINE_TRACE"}
    assert all(decisions()[c].risk is Risk.LOW for c in proposed)


def test_an_account_number_is_pseudonymised_only_because_it_is_searched():
    # L 3 makes the risk HIGH; without the declared search N falls to 1.
    d = decide(category("OTHER_ID"), None, Need("OTHER_ID", facts_lost=1))
    assert (d.risk, d.action) == (Risk.HIGH, Action.ANONYMISE)


def test_the_rulings_of_2026_09_28():
    got = {code: decisions()[code].action.name for code in RULED_2026_09_28}
    assert got == RULED_2026_09_28
    for code in RULED_2026_09_28:
        assert "2026-09-28" in decisions()[code].harm_basis + category(code).note


def test_a_procedural_date_cites_client_confidence_not_the_birth_date():
    # P1: with dates of birth split out, DATE no longer takes their L.
    d = decisions()["DATE"]
    assert "Điều 25" in d.harm_basis and d.settled
    assert (d.harm, d.risk, d.action) == (Harm.INTERNAL, Risk.LOW, Action.PSEUDONYMISE)


def test_agencies_and_parties_are_searched_by_declaration():
    # P2: no count reaches a roster category; the declaration buys N = 2.
    for code in ("PARTY", "AGENCY"):
        d = decisions()[code]
        assert d.n == 2 and "KEEP_SEARCHABLE" in d.n_basis, code
        assert "Điều 25" in d.harm_basis
    # Without the declaration a party would be ANONYMISE: its links lost.
    d = decide(category("PARTY"), None, Need("PARTY"))
    assert d.action is Action.ANONYMISE


def test_image_rows_are_flagged_and_removed():
    image = {code for code, d in decisions().items() if d.image}
    assert image == {"FACE_PHOTO", "SIGNATURE", "FINGERPRINT", "SCAN_CODE",
                     "MARK_IMAGE", "LOGO"}
    for code in image:
        d = decisions()[code]
        assert (d.harm, d.n, d.risk, d.action) == \
            (Harm.SENSITIVE, 0, Risk.HIGH, Action.REMOVE), code
        assert d.as_dict()["image"] is True
    # P4: the figurative mark and the logo are the firm's own statement.
    for code in ("MARK_IMAGE", "LOGO", "SIGNATURE"):
        assert category(code).basis_kind is BasisKind.FIRM_STATED


def test_every_new_row_has_its_evidence_row():
    from pii_core.decide import load_evidence
    data = load_evidence()
    for code in (*RULED_2026_09_28, ):
        assert code in data["need"] and code in data["pii_core_rows"]["rows"], code
