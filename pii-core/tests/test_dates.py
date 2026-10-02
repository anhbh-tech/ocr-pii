from __future__ import annotations

import pytest

from pii_core.dates import MAX_SHIFT_DAYS, find_dates, shift_days, shift_text


@pytest.mark.parametrize("text, shifted", [
    ("05/03/2024", "15/03/2024"),
    ("5/3/2024", "15/3/2024"),
    ("05.03.2024", "15.03.2024"),
    ("05-03-2024", "15-03-2024"),
    ("2024-03-05", "2024-03-15"),
    ("ngày 5 tháng 3 năm 2024", "ngày 15 tháng 3 năm 2024"),
    ("Ngày 05 tháng 03 năm 2024", "Ngày 15 tháng 03 năm 2024"),
    ("March 5, 2024", "March 15, 2024"),
    ("Mar. 5, 2024", "Mar. 15, 2024"),
    ("5 March 2024", "15 March 2024"),
    ("Tue Mar 5 09:12:30 ET 2024", "Fri Mar 15 09:12:30 ET 2024"),
])
def test_shapes_shift_and_keep_their_form(text, shifted):
    assert shift_text(text, 10) == shifted
    assert shift_text(shifted, -10) == text


def test_month_first_when_day_first_is_impossible():
    # Shifted, it may read day-first; restore() uses the vault's exact
    # shifted -> original map for such dates, not arithmetic.
    assert shift_text("03/25/2024", 10) == "04/04/2024"


def test_every_date_in_a_paragraph_moves():
    text = "nộp 2024-01-02, bổ sung ngày 5 tháng 2 năm 2024 và 01/03/2024."
    out = shift_text(text, 1)
    assert out == "nộp 2024-01-03, bổ sung ngày 6 tháng 2 năm 2024 và 02/03/2024."


def test_non_dates_are_left_alone():
    assert shift_text("mã 4-2024-12345, 31/02/2024, 1.234.567", 5) is None
    assert list(find_dates("version 1.2.2024.5")) == []


def test_shift_is_stable_per_group_and_bounded():
    key = "00" * 32
    assert shift_days(key, "case-a") == shift_days(key, "case-a")
    shifts = {shift_days(key, f"case-{i}") for i in range(200)}
    assert len(shifts) > 100
    assert all(-MAX_SHIFT_DAYS <= s <= MAX_SHIFT_DAYS for s in shifts)
