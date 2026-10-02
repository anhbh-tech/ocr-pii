"""Floors for the synthetic name benchmark, on a small slice so it stays fast.

The full table: ``uv run python tests/name_bench.py``. A floor that fails is a
regression; lower it only with the reason in the commit.
"""
from __future__ import annotations

import pytest

import name_bench as nb
from pii_core import Policy

N = 20


def rate(result: dict) -> float:
    c = sum(result["by_form"].values(), nb.Counter())
    return c["caught"] / sum(c.values())


def person_fp(result: dict) -> float:
    return result["fp"]["person_fp"] / result["fp"]["negatives"]


@pytest.mark.parametrize("suite, mode, recall, fp", [
    ("dev", "doc", 0.93, 0.0),
    ("dev", "case", 0.99, 0.0),
    ("holdout", "doc", 0.85, 0.15),
    ("holdout", "case", 0.99, 0.15),
    ("holdout", "case-unlabelled", 0.88, 0.15),
])
def test_name_benchmark_floor(suite, mode, recall, fp):
    cases, controls = nb.build(suite, N)
    result = nb.evaluate(mode, cases, controls, Policy(nb.KEY))
    assert rate(result) >= recall
    assert person_fp(result) <= fp
