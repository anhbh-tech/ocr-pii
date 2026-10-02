"""The document-level entry point: extracted text in, redacted text + vault out.

::

    result = redact_document(text, policy, group="case-042")
    result.text      # safe to hand to the agent
    result.vault     # keep it; NEVER send it to the agent
    result.fields    # the audit: category, action, reason, span — no values
    result.residue   # what a second look still finds; non-empty = stop

    restore(agent_answer, result.vault)   # tokens back

The vault holds exactly the originals that were PSEUDONYMISED (the tokens,
procedural dates among them). Anonymised and removed originals are never
written anywhere: that is what makes them irreversible. A vault written
before the firm's ruling of 2026-09-28 also holds the date strings it shifted;
``restore`` still moves those back.
"""
from __future__ import annotations

import json
import os
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

from .casevars import CaseVar
from .dates import canonical, find_dates
from .decide import Action
from . import names
from .extract import (Hit, extract, labelled_fields, mark_seeds, org_seeds, person_seeds,
                      ref_seeds)
from .keyring import flatten
from .policy import TOKEN, Policy, is_token

__all__ = ["Vault", "VaultError", "FieldRecord", "DocumentResult",
           "redact_document", "redact_case", "restore", "RESIDUE_DIGITS"]


VAULT_VERSION = 1
_TOKEN_REF = re.compile(r"\[[A-Z_]+-[0-9a-f]{10}\]")

#: A second-look shape: nine or more digits in a run that nothing treated.
RESIDUE_DIGITS = re.compile(r"(?<![\w])\d(?:[ .-]?\d){8,}(?![\w])")
#: A word that mixes Cyrillic and Latin letters: a PDF text layer whose
#: Vietnamese font map broke (``4XӕFWӏFK``). Nothing in it can be read for a
#: name, so it stops the document for OCR rather than pass as clean.
RESIDUE_GARBLED = re.compile(
    r"(?<!\w)(?=\w*[\u0400-\u04ff])(?=\w*[A-Za-z])\w+")


class VaultError(ValueError):
    pass


@dataclass(slots=True)
class Vault:
    """Reversal table for one group (one case).

    ``tokens``: token -> {category, value}. ``dates`` and
    ``date_shift_days`` are left from the date shift pii-core applied before
    2026-09-28: a shifted string -> its original, and the case's offset for
    any other date. A vault written since has 0 and ``{}``: dates are tokens.
    """

    group: str = ""
    date_shift_days: int = 0
    tokens: dict[str, dict[str, str]] = field(default_factory=dict)
    dates: dict[str, str] = field(default_factory=dict)

    def add_tokens(self, tokens: dict[str, dict[str, str]]) -> None:
        for token, row in tokens.items():
            have = self.tokens.get(token)
            if have is not None and not _same_value(have, row):
                # Two values, one token: reversal would return the wrong one.
                raise VaultError(f"token collision on {token}")
            self.tokens.setdefault(token, dict(row))

    def merge(self, other: "Vault") -> "Vault":
        if other.group != self.group:
            raise VaultError("vaults of different groups do not merge")
        if other.date_shift_days and self.date_shift_days \
                and other.date_shift_days != self.date_shift_days:
            raise VaultError(
                "vaults do not merge: their dates moved by different offsets")
        self.add_tokens(other.tokens)
        self.date_shift_days = self.date_shift_days or other.date_shift_days
        for shifted, original in other.dates.items():
            self.dates.setdefault(shifted, original)
        return self

    def as_dict(self) -> dict[str, Any]:
        return {"version": VAULT_VERSION, "group": self.group,
                "date_shift_days": self.date_shift_days,
                "tokens": self.tokens, "dates": self.dates}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Vault":
        if data.get("version") != VAULT_VERSION:
            raise VaultError(f"unsupported vault version {data.get('version')!r}")
        vault = cls(group=str(data.get("group", "")),
                    date_shift_days=int(data.get("date_shift_days", 0)),
                    dates=dict(data.get("dates", {})))
        vault.add_tokens(dict(data.get("tokens", {})))
        return vault

    def save(self, path: str | Path) -> None:
        """Written 0600: the vault is the secret, not the redacted text."""
        path = Path(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.as_dict(), fh, ensure_ascii=False, indent=1)
        os.chmod(path, 0o600)

    @classmethod
    def load(cls, path: str | Path) -> "Vault":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _same_value(have: dict[str, str], row: dict[str, str]) -> bool:
    """Do two vault rows under one token hold one value? A date may be
    written two ways (``05/03/2024``, ``ngày 5 tháng 3 năm 2024``)."""
    if flatten(have["value"]) == flatten(row["value"]):
        return True
    if have.get("category") == row.get("category") == "DATE":
        day = canonical(have["value"])
        return day is not None and day == canonical(row["value"])
    return False


@dataclass(frozen=True, slots=True)
class FieldRecord:
    """One treated span. Carries NO original value — only where it was, what
    it was classed as, what was done and why."""

    category: str | None
    action: str
    reason: str
    start: int
    end: int
    replacement: str
    matched_by: str
    label: str
    provisional: bool

    def as_dict(self) -> dict[str, Any]:
        return {"category": self.category, "action": self.action,
                "reason": self.reason, "start": self.start, "end": self.end,
                "replacement": self.replacement, "matched_by": self.matched_by,
                "label": self.label, "provisional": self.provisional}


@dataclass(slots=True)
class DocumentResult:
    text: str
    fields: list[FieldRecord]
    vault: Vault
    residue: list[dict[str, Any]]
    source: str | None = None

    @property
    def summary(self) -> dict[str, Any]:
        by_action: dict[str, int] = {}
        by_category: dict[str, int] = {}
        for f in self.fields:
            by_action[f.action] = by_action.get(f.action, 0) + 1
            if f.category:
                by_category[f.category] = by_category.get(f.category, 0) + 1
        return {"fields": len(self.fields), "by_action": by_action,
                "by_category": by_category, "tokens": len(self.vault.tokens),
                "residue": len(self.residue), "ok": not self.residue}

    def as_dict(self, include_vault: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "text": self.text, "summary": self.summary,
            "fields": [f.as_dict() for f in self.fields],
            "residue": self.residue,
        }
        if self.source is not None:
            out["source"] = self.source
        if include_vault:
            out["vault"] = self.vault.as_dict()
        return out


def _rendered(text: str, s: int, e: int, spans: list[tuple[int, int, str]]) -> str:
    """``text[s:e]`` with every treated span inside it replaced. ``spans`` are
    sorted and never overlap."""
    out, cursor = [], s
    for a, b, after in spans[bisect_right(spans, s, key=lambda t: t[1]):]:
        if a >= e:
            break
        a, b = max(a, s), min(b, e)
        out.append(text[cursor:a])
        out.append(after)
        cursor = b
    out.append(text[cursor:e])
    return "".join(out)


def _overlap_test(spans: list[tuple[int, int]]):
    """``(s, e) -> bool``: does ``[s, e)`` overlap any of ``spans``? They must
    be sorted and never overlap, so their ends are sorted too."""
    ends = [b for _, b in spans]

    def test(s: int, e: int) -> bool:
        i = bisect_right(ends, s)
        return i < len(spans) and spans[i][0] < e
    return test


def _residue(text: str, treated: list[tuple[int, int]], policy: Policy,
             case_vars: Iterable[CaseVar] = ()) -> list[dict[str, Any]]:
    """A second look at the OUTPUT. Everything reported here reached the text
    the agent would read without being treated."""
    in_treated = _overlap_test(treated)
    in_token = _overlap_test([m.span() for m in TOKEN.finditer(text)])
    found: list[dict[str, Any]] = []
    hits = extract(text, keeps=lambda c: policy.action_for(c) is Action.KEEP,
                   roster=policy.roster, case_vars=case_vars)
    kept = []
    for hit in hits:
        if policy.action_for(hit.category) is Action.KEEP:
            kept.append((hit.start, hit.end))
            continue
        value = text[hit.start:hit.end]
        if in_treated(hit.start, hit.end) or is_token(value):
            continue
        found.append({"category": hit.category, "matched_by": hit.detector,
                      "start": hit.start, "end": hit.end})
    # A value a NOT-PII label vouches for (``Tên sản phẩm: KIM LONG``) is
    # shielded, not found, so it is in no hit; the name check must skip it too.
    kept += [(h.start, h.end) for h in labelled_fields(text) if h.category is None]
    in_kept = _overlap_test(sorted(kept))
    in_found = _overlap_test([(r["start"], r["end"]) for r in found])
    for m in RESIDUE_DIGITS.finditer(text):
        s, e = m.span()
        if not (in_treated(s, e) or in_token(s, e) or in_kept(s, e) or in_found(s, e)):
            found.append({"category": None, "matched_by": "residue:digits",
                          "start": s, "end": e})
    for m in RESIDUE_GARBLED.finditer(text):
        s, e = m.span()
        if not (in_treated(s, e) or in_token(s, e)):
            found.append({"category": None, "matched_by": "residue:garbled",
                          "start": s, "end": e})
    if "residue" in names.LAYERS:
        for s, e in names.residue_names(text):
            if not (in_treated(s, e) or in_token(s, e) or in_kept(s, e) or in_found(s, e)):
                found.append({"category": "PERSON", "matched_by": "residue:name",
                              "start": s, "end": e})
    return sorted(found, key=lambda r: r["start"])


def redact_document(text: str, policy: Policy, group: str = "",
                    vault: Vault | None = None,
                    source: str | None = None,
                    names_seen: Iterable[str] = (),
                    marks_seen: Iterable[str] = (),
                    refs_seen: Iterable[str] = (),
                    case_vars: Iterable[CaseVar] = (),
                    orgs_seen: Iterable[str] = ()) -> DocumentResult:
    """Find the fields, treat each one, and return what the agent may read.

    ``group`` is the case: a vault belongs to one case. ``source`` is the
    file name, which is itself a SOURCE_FILE value and is treated like one.

    The case's names are looked for again: the PERSON values already in
    ``vault``, and ``names_seen`` (see :func:`redact_case`). A later
    ``anh hùng`` then wears the token of the ``Nguyễn Văn Hùng`` found under
    a label earlier. The vault's names are guesses, whatever found them, and
    are found again only in a name's shape (:class:`names.CaseNames`);
    ``names_seen`` are sure. Marks the same way: the vault's MARK values and
    ``marks_seen``; matter codes: the vault's MATTER_REF values and
    ``refs_seen``; and organisations by their name without the legal form:
    the vault's ORG values and ``orgs_seen``.
    """
    if vault is None:
        vault = Vault(group=group)
    elif vault.group != group or vault.date_shift_days not in (0, policy.date_shift(group)):
        # A legacy vault's shift is keyed: another shift is another key.
        raise VaultError("the vault passed in belongs to a different group or key")
    else:
        # Work on a copy: a collision halfway through must not leave the
        # caller's vault half-merged.
        vault = Vault.from_dict(vault.as_dict())

    def held(category: str) -> list[str]:
        return [row["value"] for row in vault.tokens.values()
                if row.get("category") == category]

    case_vars = tuple(case_vars)
    hits: list[Hit] = extract(text, keeps=lambda c: policy.action_for(c) is Action.KEEP,
                              roster=policy.roster, names_seen=names_seen,
                              names_guessed=held("PERSON"),
                              marks_seen=[*marks_seen, *held("MARK")],
                              refs_seen=[*refs_seen, *held("MATTER_REF")],
                              orgs_seen=[*orgs_seen, *held("ORG")], case_vars=case_vars)
    treated: list[tuple[int, int, str]] = []
    records: list[tuple[Hit, Any]] = []
    for hit in hits:
        # A name found again takes its first form's token: the vault then
        # restores that form, and the agent sees one person, not several.
        value = hit.canonical or text[hit.start:hit.end]
        matched_by = ("label" if hit.tier == "label" else "roster"
                      if hit.detector == "roster" else f"pattern:{hit.detector}")
        result = policy.apply_as(hit.category, value, group, label=hit.label,
                                 matched_by=matched_by)
        vault.add_tokens(result.tokens)
        treated.append((hit.start, hit.end, result.after))
        records.append((hit, result))

    out, cursor, pos, out_spans = [], 0, 0, []
    for (s, e, after) in treated:
        out.append(text[cursor:s])
        pos += s - cursor
        out.append(after)
        out_spans.append((pos, pos + len(after)))
        pos += len(after)
        cursor = e
    out.append(text[cursor:])
    redacted = "".join(out)

    fields = []
    for hit, result in records:
        label = ""
        if hit.label_start >= 0:
            label = _rendered(text, hit.label_start, hit.label_end, treated).strip()
        fields.append(FieldRecord(
            category=result.category, action=result.action, reason=result.reason,
            start=hit.start, end=hit.end, replacement=result.after,
            matched_by=result.matched_by, label=label,
            provisional=result.provisional))

    source_after = None
    if source is not None:
        src = policy.apply_as("SOURCE_FILE", source, group, label="source",
                              matched_by="category")
        vault.add_tokens(src.tokens)
        source_after = src.after

    residue = _residue(redacted, out_spans, policy, case_vars)
    return DocumentResult(redacted, fields, vault, residue, source_after)


def redact_case(texts: Sequence[str], policy: Policy, group: str = "",
                sources: Sequence[str | None] | None = None,
                vault: Vault | None = None,
                case_vars: Iterable[CaseVar] = ()) -> list[DocumentResult]:
    """Redact a case's documents together, so that a name found with
    confidence, or a mark or matter code under a label, in any one of them is looked for in
    all of them, including the ones before it. Each result carries the case
    vault as it stood after that document; the last one is the whole case's.
    """
    keeps = lambda c: policy.action_for(c) is Action.KEEP  # noqa: E731
    seen: list[str] = []
    marks: list[str] = []
    refs: list[str] = []
    orgs: list[str] = []
    for text in texts:
        hits = extract(text, keeps=keeps, roster=policy.roster,
                       case_vars=case_vars)
        marks += mark_seeds(text, hits)
        refs += ref_seeds(text, hits)
        orgs += org_seeds(text, hits)
        if "propagation" in names.LAYERS:
            seen += person_seeds(text, hits)
    out = []
    for i, text in enumerate(texts):
        result = redact_document(text, policy, group=group, vault=vault,
                                 source=sources[i] if sources else None,
                                 names_seen=seen, marks_seen=marks,
                                 refs_seen=refs, case_vars=case_vars,
                                 orgs_seen=orgs)
        vault = result.vault
        out.append(result)
    return out


def restore(text: str, vault: Vault, unshift_dates: bool = True) -> str:
    """Put the originals back into text that came back from the agent.

    Tokens are replaced by their vault value, a procedural date's included.
    A vault written before 2026-09-28 shifted its dates instead: those come
    back verbatim, and any OTHER date, one the agent computed in shifted time,
    is moved back by the case's offset. Pass ``unshift_dates=False`` when such
    a text carries dates that were never shifted. A vault with no shift
    leaves every literal date alone.

    Anonymised markers (``[NATIONAL_ID]``) stay: nothing can restore them.
    """
    if unshift_dates and (vault.date_shift_days or vault.dates):
        back = timedelta(days=-vault.date_shift_days)
        out, cursor = [], 0
        for hit in find_dates(text):
            original = text[hit.start:hit.end]
            out.append(text[cursor:hit.start])
            if original in vault.dates:
                out.append(vault.dates[original])
            else:
                try:
                    out.append(hit.render(hit.value + back))
                except OverflowError:
                    out.append(original)
            cursor = hit.end
        out.append(text[cursor:])
        text = "".join(out)

    def swap(m: re.Match[str]) -> str:
        row = vault.tokens.get(m.group())
        return row["value"] if row else m.group()
    return _TOKEN_REF.sub(swap, text)
