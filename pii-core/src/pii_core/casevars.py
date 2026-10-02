"""Case variables: the values the matter itself already names.

A case step arrives with the facts of its own matter — the client's name, the
matter code, the mark under dispute. The caller knows them; the extractor
would otherwise have to guess them out of the prose. They are passed in::

    [{"name": "Tên KH", "value": "...", "category": "PERSON"}, ...]

and every mention of one is replaced, whatever shape it arrived in.

Shape is the whole point. The 2026-09-24 dry run released a step whose
client name had been replaced where it stood spaced and accented and left
where an OCR'd chat line wrote it joined and bare after an ``@``, and whose
mark was left because one letter of it had been mistyped. A caller matching
exact strings cannot see either. So the match here is on a *folded* form —
accents stripped, case folded, every separator dropped — over a window of
whole words, and, for a value that is letters only, tolerating one typo.

The two guards that keep this from over-matching:

* a window is only ever whole words of the text, so ``MAI`` inside ``MAIL``
  is not a hit;
* one edit is tolerated only for the whole value, only when it is letters
  only and at least :data:`MIN_FUZZY` letters long. A code is never fuzzed:
  one digit apart, two matter codes are two different matters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Sequence

from . import labels
from .parties import fold_with_index, normalise

__all__ = ["CaseVar", "parse_vars", "find_vars", "CASE_VAR_PRIORITY"]


#: Above every pattern detector, below the roster: a public name stays public
#: even when the caller passes it as a case variable.
CASE_VAR_PRIORITY = 105

#: A value shorter than this, folded, is not worth looking for: it is an
#: initial or a two-letter code and it would match everywhere.
MIN_EXACT = 4
#: One edit is only tolerated from this folded length up.
MIN_FUZZY = 6
#: A part of a name is only looked for on its own from this many words up.
MIN_PART_WORDS = 3
#: ...and this folded length.
MIN_PART = 6
#: How much punctuation may stand between two words of one value. ``, `` or
#: `` - ``; not a line break with an indent.
MAX_GAP = 2

_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True, slots=True)
class CaseVar:
    """One fact of the matter, and the category to redact it as."""

    name: str
    value: str
    category: str | None = None


def _category_for(name: str, value: str) -> str | None:
    """What a variable is, when the caller did not say.

    The label it arrived under comes first — the caller named the field. Then
    the value's own shape, which is how ``extract`` would have read it had it
    found it unlabelled. Then a name, because a case variable that is two
    words of letters is nearly always a person, and PERSON is the careful
    answer when the shape says nothing.
    """
    from .extract import detect  # late: extract imports this module.

    by_label = labels.category_for_label(name)
    if by_label:
        return by_label
    for hit in detect(value.strip()):
        if hit.start == 0 and hit.end == len(value.strip()) and hit.category:
            return hit.category
    words = normalise(value).split()
    if len(words) >= 2 and all(w.isalpha() for w in words):
        return "PERSON"
    return "OTHER_ID"


def parse_vars(raw: Any, resolve_category: bool = True) -> tuple[CaseVar, ...]:
    """Case variables from whatever the caller had to hand.

    ``{"Tên KH": "..."}``, ``[{"name": ..., "value": ..., "category": ...}]``
    or ``["Tên KH=..."]``. An entry with no category gets one from
    :func:`_category_for`.
    """
    rows: list[tuple[str, str, str | None]] = []
    if raw is None:
        return ()
    if isinstance(raw, dict):
        rows = [(str(k), str(v), None) for k, v in raw.items() if v]
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, CaseVar):
                rows.append((item.name, item.value, item.category))
            elif isinstance(item, dict):
                value = item.get("value") or item.get("val") or ""
                if value:
                    rows.append((str(item.get("name", "")), str(value),
                                 item.get("category") or None))
            elif isinstance(item, str) and "=" in item:
                name, _, value = item.partition("=")
                if value:
                    rows.append((name.strip(), value.strip(), None))
            elif item:
                raise ValueError(f"a case variable is NAME=VALUE, not {item!r}")
    else:
        raise ValueError("case variables are a mapping or a list")
    out = []
    for name, value, category in rows:
        if resolve_category and not category:
            category = _category_for(name, value)
        out.append(CaseVar(name=name, value=value, category=category))
    return tuple(out)


def _forms(var: CaseVar) -> tuple[str, list[str]]:
    """``(whole, parts)``, each folded to bare alphanumerics."""
    words = _WORD.findall(normalise(var.value))
    whole = "".join(words)
    parts: list[str] = []
    if len(words) > MIN_PART_WORDS:
        for a in range(len(words)):
            for b in range(a + MIN_PART_WORDS, len(words) + 1):
                if a == 0 and b == len(words):
                    continue            # that is the whole value, not a part
                part = "".join(words[a:b])
                if len(part) >= MIN_PART:
                    parts.append(part)
    return whole, parts


def _within_one(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` are one substitution, insertion or deletion
    apart. Shorter than a full edit distance because one is all we allow."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long[i]:
        i += 1
    return short[i:] == long[i + 1:]


def _index(case_vars: Sequence[CaseVar]):
    exact: dict[str, CaseVar] = {}
    fuzzy: dict[int, list[tuple[str, CaseVar]]] = {}
    for var in case_vars:
        whole, parts = _forms(var)
        if len(whole) < MIN_EXACT:
            continue
        exact.setdefault(whole, var)
        if len(whole) >= MIN_FUZZY and whole.isalpha():
            fuzzy.setdefault(len(whole), []).append((whole, var))
        for part in parts:
            exact.setdefault(part, var)
    return exact, fuzzy


def _fuzzy(window: str, fuzzy) -> CaseVar | None:
    if len(window) < MIN_FUZZY or not window.isalpha():
        return None
    for n in (len(window) - 1, len(window), len(window) + 1):
        for form, var in fuzzy.get(n, ()):
            if _within_one(window, form):
                return var
    return None


def find_vars(text: str, case_vars: Iterable[CaseVar]
              ) -> Iterator[tuple[int, int, CaseVar]]:
    """Every case variable standing in ``text``, as ``(start, end, var)``.

    Longest window wins at a given word, and a window that matched is not
    entered again, so one mention yields one span.
    """
    case_vars = tuple(case_vars)
    if not case_vars:
        return
    exact, fuzzy = _index(case_vars)
    if not exact:
        return
    longest = max(len(form) for form in exact)
    folded, index = fold_with_index(text)
    words = [m.span() for m in _WORD.finditer(folded)]
    i = 0
    while i < len(words):
        best: tuple[int, int, int, CaseVar] | None = None
        window = ""
        j = i
        while j < len(words):
            if j > i and words[j][0] - words[j - 1][1] > MAX_GAP:
                break
            window += folded[words[j][0]:words[j][1]]
            if len(window) > longest + 1:
                break
            found = exact.get(window) or _fuzzy(window, fuzzy)
            if found is not None:
                best = (j, words[i][0], words[j][1], found)
            j += 1
        if best is None:
            i += 1
            continue
        end_word, start, end, var = best
        yield index[start], index[end - 1] + 1, var
        i = end_word + 1
