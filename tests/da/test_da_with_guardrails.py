"""
Tests for da/da_with_guardrails.py, covering the soft (`guard-rails: 0`)
versus strict (`guard-rails: 1`) reserve regimes.

Usage: python -m pytest tests/da/test_da_with_guardrails.py -k <test_name> -s
Run all the tests in this file: python -m pytest tests/da/test_da_with_guardrails.py
"""

import numpy as np
import pytest

from student_assignment.da.da_with_guardrails import DAwithGuards

# Program 1 holds 4 seats, reserved half for category 0 and half for
# category 1. Program 2 is a roomy fallback so that no student exhausts
# their list. Four category-0 students outrank the single category-1
# student, who is the only claimant on the category-1 reserve.
CAPACITIES = [4, 10]
RESERVE_FRACTIONS = np.array([[0.5, 0.5], [1.0, 0.0]])
PREFERENCES = [[1, 2]] * 5
PRIORITIES = [[10, 1], [9, 1], [8, 1], [7, 1], [1, 1]]
CATEGORIES = [0, 0, 0, 0, 1]


def run_guardrail_da(strict_guards):
    da = DAwithGuards(
        CAPACITIES,
        PRIORITIES,
        PREFERENCES,
        CATEGORIES,
        strictGuards=strict_guards,
    )
    da.setguards(RESERVE_FRACTIONS, numOfClasses=2)
    match, _ = da.run()
    return match


@pytest.mark.parametrize("strict_guards", [0, 1])
def test_strict_guards_flag_is_kept(strict_guards):
    """The 0/1 flag must survive the trip into the matching engine."""
    da = DAwithGuards(
        CAPACITIES,
        PRIORITIES,
        PREFERENCES,
        CATEGORIES,
        strictGuards=strict_guards,
    )
    assert da.strictGuards == strict_guards


def test_soft_reserves_share_unclaimed_seats():
    """Seats the category-1 reserve does not use fall to the open pool."""
    match = run_guardrail_da(strict_guards=0)
    assert sum(match[:4] == 1) == 3
    assert match[4] == 1


def test_strict_reserves_hold_unclaimed_seats():
    """Category 0 is held to its own 2 seats, even with seats going spare."""
    match = run_guardrail_da(strict_guards=1)
    assert sum(match[:4] == 1) == 2
    assert match[4] == 1


def test_soft_and_strict_reserves_differ():
    """Regression: the two regimes produced identical matches when the
    strict/soft flag was dropped on the way into the engine."""
    assert not np.array_equal(
        run_guardrail_da(strict_guards=0), run_guardrail_da(strict_guards=1)
    )
