"""The repository carries synthetic data only.

Every e-mail, phone number and 12-digit ID in a tracked file must use one of
the reserved invented shapes (tests/fixtures/README.md). A real value pasted
into a fixture, a doc or a docstring fails here before it is committed.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
ALLOWED_DOMAINS = re.compile(r"(?:^|\.)(?:example\.(?:test|com|org)|vidu\.test)$")
PHONE = re.compile(r"(?<![\w+])(?:\+84[ .-]?|0)\d(?:[ .-]?\d){7,9}(?!\d)")
#: Digits only, "+84" read as "0": the invented phone, tax-code, ID and
#: filler shapes, including the "…x" prefixes the fixture README spells out.
ALLOWED_DIGITS = re.compile(
    r"^(?:0900000\d{3}|031234567\d?|00109900000\d?|0+)$")
ID12 = re.compile(r"(?<!\d)\d{12}(?!\d)")
ALLOWED_ID = re.compile(r"^00109900000\d$")


def _files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    # Lockfiles are generated: their digit runs are sizes and hashes.
    return [ROOT / p for p in out.splitlines()
            if (ROOT / p).is_file() and not p.endswith((".png", ".jpg", ".pdf"))
            and Path(p).name not in ("uv.lock",)]


def _offenders() -> list[str]:
    bad = []
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT)
        for m in EMAIL.finditer(text):
            if not ALLOWED_DOMAINS.search(m.group(1).lower()):
                bad.append(f"{rel}: e-mail domain {m.group(1)}")
        for m in PHONE.finditer(text):
            digits = re.sub(r"\D", "", m.group().replace("+84", "0", 1))
            if not ALLOWED_DIGITS.match(digits):
                bad.append(f"{rel}: phone-shaped {m.group()!r}")
        for m in ID12.finditer(text):
            if not ALLOWED_ID.match(m.group()):
                bad.append(f"{rel}: 12-digit id {m.group()}")
    return bad


def test_tracked_files_carry_only_invented_identifiers():
    assert _offenders() == []


def test_no_vault_file_is_tracked():
    assert not [p for p in _files() if p.name.endswith(".vault.json")]
