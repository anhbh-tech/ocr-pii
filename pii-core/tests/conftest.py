from __future__ import annotations

import json
from pathlib import Path

import pytest

from pii_core import Policy, Roster

FIXTURES = Path(__file__).parent / "fixtures"
KEY = "synthetic-test-key-not-a-secret"


@pytest.fixture
def policy() -> Policy:
    return Policy(KEY)


@pytest.fixture
def roster() -> Roster:
    return Roster.load(FIXTURES / "roster_synthetic.json")


@pytest.fixture
def case_text() -> str:
    return (FIXTURES / "case_synthetic.txt").read_text(encoding="utf-8")


@pytest.fixture
def register() -> dict:
    return json.loads((FIXTURES / "synthetic_register.json").read_text(encoding="utf-8"))
