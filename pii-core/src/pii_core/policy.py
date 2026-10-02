"""The field-level API: ``(label, value) -> action + reason``.

The body is pii-lab's ``Policy.apply_as`` (`src/pii_lab/policy.py`), in the
same order, because the order is what makes it correct:

1. **Roster first, on the value.** The roster's category wins whatever the
   label says; the label cannot know whether a name is the client, the
   opposing party, the agency or the firm. The firm is kept. An opposing
   party (PARTY) or an agency (AGENCY) is tokenised under its roster name, so
   every alias wears one token (the firm's ruling of 2026-09-28, P2; pii-lab
   kept both).
2. Blank, or already a token: unchanged. Never token a token.
3. PSEUDONYMISE: ``[CATEGORY-hex10]``, stable across documents and reversible
   through the vault. A DATE's token is computed over its ISO form
   (:func:`pii_core.dates.canonical`), so one date is one token however it is
   written. pii-lab shifts dates instead; pii-core did too until the firm's
   ruling of 2026-09-28 (P1). ANONYMISE: ``[CATEGORY]``, irreversible, no
   key. REMOVE: the empty string.
4. An unknown category fails closed at REMOVE; ``None`` (the label declares
   nothing) is KEEP.

New in pii-core: every result carries a human-readable ``reason``, and when a
label declares nothing the VALUE is still scanned with the pattern detectors
(:func:`pii_core.extract.detect`), so ``Ghi chú: gọi 0900 000 001`` does not
pass a phone number through merely because ``Ghi chú`` is not a PII label.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any

from .dates import canonical, shift_days
from .decide import Action, Decision, decisions, table
from .keyring import Keyring
from .labels import category_for_label, declares_not_pii
from .parties import Roster

__all__ = ["Policy", "FieldResult", "TOKEN", "is_token", "is_blank"]


#: A pii-core / pii-lab token, or pii-lab's legacy money mask.
TOKEN = re.compile(r"\[[A-Z_]+-[0-9a-f]+\]|\[[A-Z_]+\]|[\w.+-]+@vidu\.test|\[SỐ TIỀN\]")

_BLANK = re.compile(
    r"^(?:|-+|—+|n/?a|none(?: specified\.?)?|nil|null|nan|"
    r"\[\s*[x ]?\s*\]|\(\s*\)|không|khong|chưa có|chua co|yes|no|có|co)$",
    re.IGNORECASE,
)


def is_token(value: str) -> bool:
    """True when the value is ENTIRELY tokens and punctuation."""
    if not TOKEN.search(value):
        return False
    return not TOKEN.sub("", value).strip(" ,.;:/|-()[]")


def is_blank(value: str) -> bool:
    return bool(_BLANK.fullmatch(value.strip()))


@dataclass(frozen=True, slots=True)
class FieldResult:
    """What the policy did to one field, and why.

    ``tokens`` maps each token minted here to ``{category, value}`` — the
    field's share of the vault. It holds originals, so it goes back to the
    caller only, never to the agent.
    """

    label: str
    category: str | None
    action: str
    reason: str
    after: str
    matched_by: str
    tokens: dict[str, dict[str, str]] = dc_field(default_factory=dict)
    provisional: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "category": self.category,
                "action": self.action, "reason": self.reason,
                "after": self.after, "matched_by": self.matched_by,
                "provisional": self.provisional}


class Policy:
    """One key, one roster, one decision table.

    ``key`` keys the tokens and the date shift. The same key gives the same
    token for the same value — across documents, and across pii-lab and
    pii-core — which is what keeps a case joinable; a different key gives
    unrelated tokens.
    """

    def __init__(self, key: str, roster: Roster | None = None,
                 evidence: dict[str, Any] | None = None) -> None:
        self._keys = Keyring.from_text(key)
        self._dateshift = self._keys.subkey("dateshift").hex()
        self.roster = roster if roster is not None else Roster()
        self.decisions: dict[str, Decision] = (
            decisions() if evidence is None
            else {d.category: d for d in table(evidence)})

    # -- lookups -------------------------------------------------------------

    def action_for(self, category: str | None) -> Action:
        if category is None:
            return Action.KEEP
        decision = self.decisions.get(category)
        return decision.action if decision else Action.REMOVE

    def token(self, category: str, value: str) -> str:
        return f"[{category}-{self._keys.token_digest(category, value)}]"

    def date_shift(self, group: str) -> int:
        """The keyed shift pii-lab applies to this group's dates. pii-core no
        longer shifts; it checks a legacy vault against this."""
        return shift_days(self._dateshift, group)

    # -- the API -------------------------------------------------------------

    def field(self, label: str, value: str, group: str = "") -> FieldResult:
        """Classify and treat one labelled field.

        The label decides the category when it declares one. When it does not,
        the value is scanned, and every sensitive span inside it is treated on
        its own.
        """
        category = category_for_label(label)
        if category is not None or self.roster.lookup(value) is not None:
            return self.apply_as(category, value, group, label=label,
                                 matched_by="label")
        if declares_not_pii(label):
            return FieldResult(label, None, Action.KEEP.name,
                               f"nhãn “{label.strip()}” khai báo sản phẩm / dịch "
                               "vụ / tên miền — thứ luật sư phải đọc được, "
                               "không phải thông tin cá nhân; giữ nguyên.",
                               value, "label:not-pii")
        return self._scan_value(label, value, group)

    def apply_as(self, category: str | None, value: str, group: str = "",
                 label: str = "", matched_by: str = "category") -> FieldResult:
        """The same treatment for a value whose category is already known."""
        party = self.roster.lookup(value)
        roster_head = ""
        if party is not None:
            if self.action_for(party.category) is Action.KEEP:
                return FieldResult(
                    label, party.category, Action.KEEP.name,
                    f"giá trị có trong roster ({party.category}"
                    + (f": {party.why}" if party.why else "")
                    + "); danh tính công khai, nên giữ nguyên dù nhãn nói gì.",
                    value, "roster")
            # The roster's own ``why`` may name the party; a tokenised row's
            # reason must not.
            roster_head = f"giá trị có trong roster ({party.category}); "
            # One party, one token: an alias restores as the roster name.
            category, value, matched_by = party.category, party.name, "roster"

        action = self.action_for(category)
        decision = self.decisions.get(category) if category else None
        tokens: dict[str, dict[str, str]] = {}

        if category is None:
            return FieldResult(label, None, Action.KEEP.name,
                               "nhãn không khai báo hạng mục thông tin cá nhân "
                               "nào; giữ nguyên.", value, "none")
        if decision is None:
            reason = (f"hạng mục {category!r} không có trong bảng quyết định — "
                      "lỗi của dự án, không phải giấy phép công bố; đóng an "
                      "toàn ở REMOVE.")
        else:
            reason = roster_head + self._reason(label, category, decision,
                                                matched_by)

        if action is Action.KEEP or is_blank(value):
            after = value
        elif is_token(value):
            after = value
            reason += " Giá trị đã là token; không token hoá lần nữa."
        elif action is Action.PSEUDONYMISE:
            key = canonical(value) if category == "DATE" else None
            after = self.token(category, key or value)
            tokens[after] = {"category": category, "value": value}
        elif action is Action.ANONYMISE:
            after = f"[{category}]"
        else:
            after = ""

        return FieldResult(label, category, action.name, reason, after,
                           matched_by, tokens,
                           provisional=bool(decision and decision.provisional))

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _reason(label: str, category: str, decision: Decision,
                matched_by: str) -> str:
        if matched_by == "label" and label:
            head = f"nhãn “{label.strip()}” khai báo {category}. "
        elif matched_by.startswith("pattern"):
            head = f"giá trị khớp mẫu {category} ({matched_by}). "
        else:
            head = f"hạng mục {category}. "
        tail = (" L của hạng mục này là ĐỀ XUẤT, văn phòng chưa xác nhận."
                if decision.provisional else "")
        return head + decision.why + tail

    def _scan_value(self, label: str, value: str, group: str) -> FieldResult:
        from .extract import detect   # extract does not import policy

        hits = [h for h in detect(value, roster=self.roster)
                if self.action_for(h.category) is not Action.KEEP]
        if not hits:
            return FieldResult(label, None, Action.KEEP.name,
                               "nhãn không khai báo hạng mục nào và giá trị "
                               "không khớp mẫu nhạy cảm nào; giữ nguyên.",
                               value, "none")
        out, cursor, tokens, worst = [], 0, {}, Action.KEEP
        reasons, provisional = [], False
        for hit in hits:
            result = self.apply_as(hit.category, value[hit.start:hit.end],
                                   group, label=label,
                                   matched_by=f"pattern:{hit.detector}")
            out.append(value[cursor:hit.start])
            out.append(result.after)
            cursor = hit.end
            tokens.update(result.tokens)
            provisional = provisional or result.provisional
            action = Action[result.action]
            if action > worst:
                worst = action
            reasons.append(f"{hit.category} → {result.action}")
        out.append(value[cursor:])
        top = max(hits, key=lambda h: self.action_for(h.category)).category
        return FieldResult(
            label, top, worst.name,
            "nhãn không khai báo hạng mục nào; trong giá trị tìm thấy: "
            + ", ".join(reasons) + ". Hành động của trường là hành động "
            "phá huỷ nhiều nhất trong số đó.",
            "".join(out), "pattern", tokens, provisional)
