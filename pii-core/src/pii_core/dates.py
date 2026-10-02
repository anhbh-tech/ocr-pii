"""Dates: found in free text, and (for legacy vaults) shifted.

Since the firm's ruling of 2026-09-28 (P1) a procedural date is tokenised,
not shifted: a shift shared by the whole case falls to one known pair of
real dates, and every other date opens with it. :func:`canonical` is what the
token is computed over, so two writings of one date wear one token. The shift
below stays for the vaults written before the ruling, whose dates
``document.restore`` still moves back.

The shift, as it was:

Ported from pii-lab (`src/pii_lab/dates.py`): every date in one group (a case)
moves by the same keyed number of days, so "filed within three months of the
office action?" still has an answer, and the absolute date does not survive.
The offset is derived exactly as pii-lab derives it, so the same root key and
group shift identically in both projects.

Changes for free text, which pii-lab's table cells never needed:

* **Leftmost match across every shape.** pii-lab tries its shapes in order
  and takes the first shape that matches anywhere, which in a multi-date
  paragraph can skip an earlier date of another shape and leave it verbatim.
* **More shapes**: ``ngày 5 tháng 3 năm 2024``, ``05-03-2024`` /
  ``05.03.2024``, full English month names, ``5 March 2024``.
* **Slash dates fall back to month-first** when day-first is impossible
  (``03/25/2024``), rather than being left unshifted.

What a shift does NOT protect against (pii-lab's caveat, still true): a matter
with a distinctive rhythm of filings can be matched by its intervals alone.
The shift hides *when*, never *which*.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator

__all__ = ["shift_days", "shift_text", "find_dates", "canonical", "FoundDate",
           "MAX_SHIFT_DAYS"]


MAX_SHIFT_DAYS = 365

_MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july",
                "august", "september", "october", "november", "december"]
_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|"
          r"July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
          r"Dec(?:ember)?)")

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A printed timestamp, "Tue Mar 5 09:12:30 ET 2024": the year trails the clock.
    ("ctime", re.compile(
        rf"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+({_MONTH})\s+(\d{{1,2}})\s+"
        r"(\d{1,2}:\d{2}(?::\d{2})?)\s+(?:([A-Z]{2,5})\s+)?(\d{4})\b")),
    ("vn_long", re.compile(
        r"\b(ng[àa]y)\s+(\d{1,2})\s+(th[áa]ng)\s+(\d{1,2})\s+(n[ăa]m)\s+(\d{4})\b",
        re.IGNORECASE)),
    ("mdy_name", re.compile(rf"\b({_MONTH})(\.?)\s+(\d{{1,2}}),\s*(\d{{4}})\b")),
    ("dmy_name", re.compile(rf"\b(\d{{1,2}})\s+({_MONTH})(\.?),?\s+(\d{{4}})\b")),
    # A trailing "." ends a sentence, not the number: only ".<digit>" continues it.
    ("ymd", re.compile(r"(?<![\d./-])(\d{4})-(\d{2})-(\d{2})(?![\d/-]|\.\d)")),
    ("dmy_num", re.compile(
        r"(?<![\d./-])(\d{1,2})([/.-])(\d{1,2})\2(\d{4})(?![\d/-]|\.\d)")),
)


def _month_index(name: str) -> int:
    lower = name.lower()
    for i, full in enumerate(_MONTH_NAMES, start=1):
        if full.startswith(lower[:3]):
            return i
    raise ValueError(name)


def _month_render(original: str, month: int) -> str:
    full = _MONTH_NAMES[month - 1].capitalize()
    if len(original) <= 3:
        return full[:3]
    if original.lower().startswith("sep") and len(original) == 4:
        return "Sept" if month == 9 else full[:3]
    return full


def _pad(padded: bool, value: int) -> str:
    return f"{value:02d}" if padded else str(value)


@dataclass(frozen=True, slots=True)
class FoundDate:
    start: int
    end: int
    value: date
    shape: str
    match: re.Match[str]
    month_first: bool = False

    @property
    def padded(self) -> bool:
        """Zero-padded style, decided for the whole date so a round trip keeps
        it: "5/3/2024" -> "15/3/2024" -> "5/3/2024", and "05/03/2024" stays
        two-wide. A numeric date is padded unless a part is written one digit
        wide; a month-name date only when its day carries a leading zero."""
        m = self.match
        if self.shape in ("vn_long", "dmy_num"):
            parts = (m.group(2), m.group(4)) if self.shape == "vn_long" \
                else (m.group(1), m.group(3))
            return all(len(p) == 2 for p in parts)
        if self.shape in ("mdy_name", "dmy_name", "ctime"):
            day = m.group({"mdy_name": 3, "dmy_name": 1, "ctime": 2}[self.shape])
            return day.startswith("0")
        return True

    def render(self, new: date) -> str:
        m, pad = self.match, self.padded
        if self.shape == "vn_long":
            return (f"{m.group(1)} {_pad(pad, new.day)} {m.group(3)} "
                    f"{_pad(pad, new.month)} {m.group(5)} {new.year}")
        if self.shape == "mdy_name":
            return (f"{_month_render(m.group(1), new.month)}{m.group(2)} "
                    f"{_pad(pad, new.day)}, {new.year}")
        if self.shape == "dmy_name":
            return (f"{_pad(pad, new.day)} "
                    f"{_month_render(m.group(2), new.month)}{m.group(3)} {new.year}")
        if self.shape == "ctime":
            zone = f"{m.group(4)} " if m.group(4) else ""
            return (f"{_WEEKDAYS[new.weekday()]} {_month_render(m.group(1), new.month)} "
                    f"{_pad(pad, new.day)} {m.group(3)} {zone}{new.year}")
        if self.shape == "ymd":
            return new.isoformat()
        sep = m.group(2)
        first, second = ((new.month, new.day) if self.month_first
                         else (new.day, new.month))
        return f"{_pad(pad, first)}{sep}{_pad(pad, second)}{sep}{new.year}"


def _parse(shape: str, m: re.Match[str]) -> tuple[date, bool] | None:
    try:
        if shape == "vn_long":
            return date(int(m.group(6)), int(m.group(4)), int(m.group(2))), False
        if shape == "mdy_name":
            return date(int(m.group(4)), _month_index(m.group(1)),
                        int(m.group(3))), False
        if shape == "dmy_name":
            return date(int(m.group(4)), _month_index(m.group(2)),
                        int(m.group(1))), False
        if shape == "ymd":
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), False
        if shape == "ctime":
            return date(int(m.group(5)), _month_index(m.group(1)),
                        int(m.group(2))), False
        a, b, year = int(m.group(1)), int(m.group(3)), int(m.group(4))
        try:
            return date(year, b, a), False          # day-first (VN, pii-lab)
        except ValueError:
            return date(year, a, b), True           # month-first (US)
    except ValueError:
        return None                                  # 31 February: not a date


def find_dates(text: str) -> Iterator[FoundDate]:
    """Every parseable date in the text, leftmost first, never overlapping."""
    hits: list[FoundDate] = []
    for shape, pattern in _SHAPES:
        for m in pattern.finditer(text):
            parsed = _parse(shape, m)
            if parsed is None:
                continue
            value, month_first = parsed
            hits.append(FoundDate(m.start(), m.end(), value, shape, m, month_first))
    hits.sort(key=lambda h: (h.start, -(h.end - h.start)))
    cursor = -1
    for hit in hits:
        if hit.start >= cursor:
            yield hit
            cursor = hit.end


def canonical(text: str) -> str | None:
    """The ISO form of ``text`` when it is one date and nothing else:
    ``05/03/2024``, ``5.3.2024`` and ``ngày 5 tháng 3 năm 2024`` all give
    ``2024-03-05``. None for anything else, which is then tokenised as
    written."""
    value = text.strip(" \t\r\n,.;:()")
    hits = list(find_dates(value))
    if len(hits) == 1 and hits[0].start == 0 and hits[0].end == len(value):
        return hits[0].value.isoformat()
    return None


def shift_days(key: str, group: str) -> int:
    """How far this group's dates move. Same group, same shift, always.

    ``key`` is the hex of the ``dateshift`` subkey, as in pii-lab.
    """
    digest = hmac.digest(key.encode("utf-8"), f"date-shift|{group}".encode(),
                         hashlib.sha256)
    span = 2 * MAX_SHIFT_DAYS + 1
    return int.from_bytes(digest[:4], "big") % span - MAX_SHIFT_DAYS


def shift_text(text: str, days: int) -> str | None:
    """Every date in the text moved by ``days``. None when nothing parsed —
    the caller then falls back to a class marker rather than emitting text it
    did not understand."""
    offset = timedelta(days=days)
    out, cursor, moved = [], 0, False
    for hit in find_dates(text):
        try:
            new = hit.value + offset
        except OverflowError:
            continue
        out.append(text[cursor:hit.start])
        out.append(hit.render(new))
        cursor = hit.end
        moved = True
    if not moved:
        return None
    out.append(text[cursor:])
    return "".join(out)
