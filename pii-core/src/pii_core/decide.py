"""The decision table: ``risk = R x L``, then N picks the treatment.

Ported from pii-lab (`src/pii_lab/decide.py` and the `Need` /
`Reidentification` records of `measure.py`). pii-lab is the source of truth:
the rule, the thresholds and the Vietnamese reasons are carried over unchanged,
and ``tests/test_decide.py`` asserts that running this rule over the ported
evidence reproduces pii-lab's frozen table row for row.

No category carries a hand-written verdict. R and N come from counts measured
on pii-lab's corpus (``data/evidence.json``), plus the searches the firm
declares (:data:`DECLARED_SEARCHABLE`); L comes from the register. Change an
input and the action changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import IntEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from .categories import BY_CODE, Category, Harm

__all__ = ["Action", "Risk", "Decision", "Need", "Reidentification",
           "need_score", "risk_of", "decide", "table", "decisions",
           "load_evidence", "EVIDENCE_PATH", "FACTS_MANY", "LINKS_MANY",
           "REVERSIBLE_NEEDS_N", "R_MIN_DISTINCT", "DECLARED_SEARCHABLE"]


EVIDENCE_PATH = Path(__file__).parent / "data" / "evidence.json"

# `facts_lost` at or above this means the system's own extraction leans on the
# category. pii-lab: every category in its corpus sits clearly on one side.
FACTS_MANY = 100

# 50 distinct values reaching more than one document: a corpus genuinely
# joined on this category.
LINKS_MANY = 50

# N at or above this buys a REVERSIBLE treatment. ocr-lab's threshold, adopted
# by pii-lab: reversibility is itself a re-identification path, so the need
# has to show on two measures, not one. Moving it to 1 pseudonymises CCCD.
REVERSIBLE_NEEDS_N = 2

# Below this many distinct values R is a ratio of small integers wearing a
# percent sign; the row then uses the worst case R = 1 and says so.
R_MIN_DISTINCT = 20

# pii-core's additions to pii-lab's KEEP_SEARCHABLE: a declaration by the firm,
# not a count, so it stays out of the measured evidence file.
DECLARED_SEARCHABLE: dict[str, str] = {
    "MARK": "2026-09-23: một nhãn hiệu phải là một giá trị trong cả hồ sơ "
            "(đơn, thông báo, phản đối, gia hạn).",
    # 2026-09-28, P2: tokenise agencies and opposing parties rather than keep
    # them. The roster names them, so no count was ever taken.
    "PARTY": "2026-09-28: tìm mọi văn bản về một đối phương (truy hồi) và "
             "khôi phục tên khi soạn thư; một đối phương là một giá trị trong "
             "cả hồ sơ.",
    "AGENCY": "2026-09-28: nối thông báo với đơn theo cơ quan đã ra nó (suy "
              "giai đoạn, truy hồi); một cơ quan là một giá trị trong cả hồ sơ.",
}


class Action(IntEnum):
    """What to do with a category. Ordered by how much is destroyed."""

    KEEP = 0
    """Leave it. Hiding it protects nobody and costs the lawyer the check."""
    PSEUDONYMISE = 1
    """Stable, REVERSIBLE token. Dates too, since 2026-09-28 (no shift)."""
    ANONYMISE = 2
    """Class marker, irreversibly."""
    REMOVE = 3
    """Take it out. High harm, no need at all."""


class Risk(IntEnum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass(frozen=True, slots=True)
class Reidentification:
    """R for one category: the share of distinct values seen in one matter."""

    category: str
    source: str = "none"
    distinct: int = 0
    singletons: int = 0
    matters: int = 0

    @property
    def r(self) -> float | None:
        return self.singletons / self.distinct if self.distinct else None

    @property
    def reliable(self) -> bool:
        return self.distinct >= R_MIN_DISTINCT


@dataclass(frozen=True, slots=True)
class Need:
    """N for one category, measured as what stops working without it."""

    category: str
    facts_lost: int = 0
    sole_anchor_for: int = 0
    declared_searchable: bool = False
    links: int = 0
    links_source: str = "none"


def need_score(need: Need) -> int:
    """N, 0-3, derived from what was measured.

    3 — some document's only way home; 2 — the corpus leans on it (many facts,
    many cross-document links, or declared searchable); 1 — something uses it;
    0 — no measured use was FOUND (not: there is no need).
    """
    if need.sole_anchor_for > 0:
        return 3
    if (need.facts_lost >= FACTS_MANY or need.links >= LINKS_MANY
            or need.declared_searchable):
        return 2
    if need.facts_lost > 0 or need.links > 0:
        return 1
    return 0


def risk_of(r: float, harm: Harm) -> Risk:
    """Bucket `R x L` (0..3). At L = 0 the product is 0 whatever R does."""
    product = r * int(harm)
    if product <= 0:
        return Risk.NONE
    if product <= 1.0:
        return Risk.LOW
    if product <= 2.0:
        return Risk.MEDIUM
    return Risk.HIGH


@dataclass(frozen=True, slots=True)
class Decision:
    """One row of the table, carrying every input that produced it."""

    category: str
    r: float | None
    r_measured: bool
    harm: Harm
    harm_basis: str
    settled: bool
    n: int
    n_basis: str
    risk: Risk
    action: Action
    why: str
    image: bool = False

    @property
    def provisional(self) -> bool:
        return not self.settled

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category, "r": self.r,
            "r_measured": self.r_measured, "harm": int(self.harm),
            "harm_basis": self.harm_basis, "settled": self.settled,
            "n": self.n, "n_basis": self.n_basis, "risk": self.risk.name,
            "action": self.action.name, "why": self.why, "image": self.image,
        }


def _n_basis(need: Need) -> str:
    parts = [f"mất {need.facts_lost} dòng fact"]
    if need.links_source == "none":
        parts.append("không đo được liên kết")
    else:
        parts.append(f"{need.links} liên kết giữa các tài liệu "
                     f"({need.links_source})")
    if need.sole_anchor_for:
        parts.append(f"là neo duy nhất của {need.sole_anchor_for} tài liệu")
    if need.declared_searchable:
        parts.append("được khai trong KEEP_SEARCHABLE")
    return "; ".join(parts)


def decide(category: Category, reid: Reidentification | None,
           need: Need) -> Decision:
    """One category in, one decided row out.

    * risk NONE          -> KEEP
    * N >= 2             -> PSEUDONYMISE
    * risk HIGH, N > 0   -> ANONYMISE (a weak need does not pay for a vault)
    * risk HIGH, N = 0   -> REMOVE
    * otherwise          -> ANONYMISE
    """
    measured = reid is not None and reid.r is not None and reid.reliable
    r = reid.r if (measured and reid is not None and reid.r is not None) else 1.0

    risk = risk_of(r, category.leak_harm)
    n = need_score(need)

    if risk is Risk.NONE:
        action = Action.KEEP
        why = (f"L = 0 ({category.leak_harm_basis}), nên rủi ro bằng 0 dù R "
               f"bằng bao nhiêu. Ở đây R = {r:.0%} và điều đó không đổi được "
               f"gì — R đo khả năng TÁCH BIỆT, không đo thiệt hại.")
    elif n >= REVERSIBLE_NEEDS_N:
        action = Action.PSEUDONYMISE
        why = (f"rủi ro {risk.name} (R {r:.0%} × L {int(category.leak_harm)}), "
               f"và N = {n}: {_n_basis(need)}. Nhu cầu được chứng minh trên "
               f"nhiều hơn một phép đo, nên giá trị đáng được giữ ở dạng lấy "
               f"lại được và phần thay thế phải hoàn nguyên được.")
    elif risk is Risk.HIGH and n > 0:
        action = Action.ANONYMISE
        why = (f"rủi ro {risk.name} (R {r:.0%} × L {int(category.leak_harm)}) "
               f"đối lại N = {n} — {_n_basis(need)}. Nhu cầu đo được bằng {n} "
               f"thì chưa đủ trả giá cho một hàng vault: khả năng hoàn nguyên "
               f"tự nó đã là một đường tái định danh, và ở mức thiệt hại này "
               f"nó phải được đánh đổi bằng nhiều hơn một tín hiệu. Khái quát "
               f"hoá thay vì giữ lại.")
    elif risk is Risk.HIGH:
        action = Action.REMOVE
        why = (f"rủi ro {risk.name} (R {r:.0%} × L {int(category.leak_harm)}) "
               f"với N = 0 — {_n_basis(need)}. Giữ một bản hoàn nguyên được là "
               f"giữ nguyên rủi ro mà không đổi lại được gì đo đếm được.")
    else:
        action = Action.ANONYMISE
        why = (f"rủi ro {risk.name} (R {r:.0%} × L {int(category.leak_harm)}) "
               f"với N = 0 — {_n_basis(need)}. Không phép đo nào cần lấy lại nó.")

    if not measured:
        why += (" R ở đây không đo được"
                + (f" (chỉ có {reid.distinct} giá trị phân biệt)" if reid else "")
                + ", nên lấy trường hợp xấu nhất R = 100%.")

    return Decision(
        category=category.code, r=reid.r if reid else None, r_measured=measured,
        harm=category.leak_harm, harm_basis=category.leak_harm_basis,
        settled=category.settled, n=n, n_basis=_n_basis(need),
        risk=risk, action=action, why=why, image=category.image,
    )


def load_evidence(path: Path | None = None) -> dict[str, Any]:
    """The measured counts ported from pii-lab. Counts only."""
    return json.loads((path or EVIDENCE_PATH).read_text(encoding="utf-8"))


def table(evidence: dict[str, Any] | None = None) -> list[Decision]:
    """Every category, decided from the evidence. Most destructive first."""
    data = evidence if evidence is not None else load_evidence()
    reid = {code: Reidentification(**row)
            for code, row in data.get("reidentification", {}).items()}
    need = {code: Need(**row) for code, row in data.get("need", {}).items()}
    for code in DECLARED_SEARCHABLE:
        need[code] = replace(need.get(code, Need(code)), declared_searchable=True)
    rows = [decide(cat, reid.get(code), need.get(code, Need(code)))
            for code, cat in BY_CODE.items()]
    return sorted(rows, key=lambda d: (-d.action, -d.risk, d.category))


@lru_cache(maxsize=1)
def decisions() -> dict[str, Decision]:
    """The default table, keyed by category code. Computed once per process."""
    return {d.category: d for d in table()}
