"""The roster: who a name belongs to, which no label can say.

Three roles. ``FIRM`` (the firm's own staff and name) is kept as written.
``PARTY`` (an opposing party or its counsel) and ``AGENCY`` (Cục SHTT,
USPTO, a court, an official signing for one) are tokenised under their roster
name, on the firm's ruling of 2026-09-28 (P2); until then both were kept.

The lookup is pii-lab's (`src/pii_lab/parties.py`): accent-folded,
punctuation-insensitive, WHOLE-value match, checked on the value before any
label is consulted. A label says ``Name``; whether the name is the client or
opposing counsel is a fact about the value.

What changed: pii-lab ships its roster in source. pii-core ships NONE. The
roster names real counterparties, and this repository holds synthetic data
only, so the firm supplies the roster at run time as a JSON file::

    [{"name": "...", "category": "PARTY" | "AGENCY" | "FIRM", "why": "...",
      "aliases": ["..."]}]

passed as ``--roster FILE`` or ``PII_CORE_ROSTER=FILE``. With no roster every
name is treated as a client's, which is the safe direction to be wrong in --
but an expensive one: the firm's own lawyers are then tokenised out of their
own memos, so the roster carries internal staff (``"category": "FIRM"``) as
well as public counterparties. Keep the file outside the repository, e.g.
``~/.private/pii-core/roster.json``, mode 0600; it is not synthetic data.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

__all__ = ["Party", "Roster", "normalise", "fold_with_index", "ROSTER_ENV"]


ROSTER_ENV = "PII_CORE_ROSTER"
_CATEGORIES = ("PARTY", "AGENCY", "FIRM")


def normalise(value: str) -> str:
    """Comparable form: accents folded, punctuation dropped, case folded."""
    decomposed = unicodedata.normalize("NFD", value or "")
    folded = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    folded = folded.replace("đ", "d").replace("Đ", "D")
    return " ".join(re.sub(r"[^\w\s@.]+", " ", folded).split()).lower()


def fold_with_index(text: str) -> tuple[str, list[int]]:
    """``text`` folded as :func:`normalise` folds it (without collapsing
    spaces or dropping punctuation), plus each folded character's position in
    ``text``."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        base = "".join(c for c in unicodedata.normalize("NFD", ch)
                       if unicodedata.category(c) != "Mn")
        base = base.replace("đ", "d").replace("Đ", "D").lower()
        for c in base:
            out.append(c)
            index.append(i)
    return "".join(out), index


@dataclass(frozen=True, slots=True)
class Party:
    name: str
    category: str
    why: str = ""
    aliases: tuple[str, ...] = ()

    @property
    def spellings(self) -> tuple[str, ...]:
        return (self.name,) + self.aliases


@dataclass(slots=True)
class Roster:
    parties: tuple[Party, ...] = ()
    _index: dict[str, Party] = field(default_factory=dict, repr=False)
    _pattern: re.Pattern[str] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for party in self.parties:
            if party.category not in _CATEGORIES:
                raise ValueError(
                    f"roster entry {party.name!r}: category must be one of "
                    f"{_CATEGORIES}, not {party.category!r}")
            for spelling in party.spellings:
                key = normalise(spelling)
                if key:
                    self._index[key] = party
        if self._index:
            # Longest spelling first, so an alias that is a prefix of a longer
            # name does not win; words may be separated by any punctuation.
            alternatives = sorted(self._index, key=len, reverse=True)
            self._pattern = re.compile(
                r"(?<!\w)(?:" + "|".join(
                    r"[^\w@.]+".join(map(re.escape, key.split(" ")))
                    for key in alternatives) + r")(?!\w)")

    @classmethod
    def from_rows(cls, rows: Iterable[dict[str, Any]]) -> "Roster":
        return cls(tuple(
            Party(name=row["name"], category=row.get("category", "PARTY"),
                  why=row.get("why", ""),
                  aliases=tuple(row.get("aliases", ())))
            for row in rows))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Roster":
        """From ``path``, else ``$PII_CORE_ROSTER``, else empty."""
        source = path or os.environ.get(ROSTER_ENV)
        if not source:
            return cls()
        try:
            raw = Path(source).read_text(encoding="utf-8")
        except OSError as exc:
            # Silence here would be expensive: with no roster the firm's own
            # people are read as clients and tokenised out of their own file.
            raise ValueError(f"roster file {source}: {exc.strerror}") from None
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"roster file {source}: {exc}") from None
        if not isinstance(rows, list):
            raise ValueError(f"roster file {source}: a roster is a JSON list "
                             "of {name, category, aliases?, why?} entries")
        return cls.from_rows(rows)

    def lookup(self, value: str) -> Party | None:
        """The party this WHOLE value names, or None.

        Whole-value on purpose: a roster name inside a longer string (a client
        company whose name contains a public brand) is not the party.
        """
        return self._index.get(normalise(value))

    def find(self, text: str) -> Iterator[tuple[int, int, Party]]:
        """Every roster name standing in running text, as ``(start, end,
        party)`` spans of ``text``.

        A document is not a table of cells: ``Bên bị: <party> và <firm>`` puts
        two public names in one value, and the whole-value :meth:`lookup`
        would miss both. The match is folded the same way as the lookup.
        """
        if self._pattern is None:
            return
        folded, index = fold_with_index(text)
        for m in self._pattern.finditer(folded):
            party = self._index.get(normalise(m.group()))
            if party is not None:
                yield index[m.start()], index[m.end() - 1] + 1, party

    def __len__(self) -> int:
        return len(self.parties)
