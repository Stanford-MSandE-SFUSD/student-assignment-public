"""Tests for the shared KG schema and adapt_to_kg_schema adapter."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
_PREPROCESS = REPO / "scripts" / "preprocessing"
if str(_PREPROCESS) not in sys.path:
    sys.path.insert(0, str(_PREPROCESS))

from adapt_to_kg_schema import (  # noqa: E402
    STUDENT_FILL_IF_MISSING,
    adapt_frame,
    load_column_list,
)

SCHEMA = REPO / "schemas"


def test_schema_files_exist_and_nonempty():
    for name in (
        "kg_student_columns.txt",
        "kg_program_columns.txt",
        "kg_school_columns.txt",
    ):
        cols = load_column_list(SCHEMA / name)
        assert cols, f"{name} should list at least one column"


def test_adapt_student_drops_extras_and_orders():
    keep = load_column_list(SCHEMA / "kg_student_columns.txt")
    # Minimal row: required cols + extras that must be dropped.
    required = [c for c in keep if c not in STUDENT_FILL_IF_MISSING]
    row = {c: 0 for c in required}
    row.update(
        {
            "extra_research_col": 0.5,
            "another_unused_flag": 1,
            "grade": "KG",
            "resolved_ethnicity": "White",
            "r1_programs": "[]",
            "sibling": "[]",
        }
    )
    df = pd.DataFrame([row])
    out = adapt_frame(
        df, keep, fill_if_missing=STUDENT_FILL_IF_MISSING, label="student"
    )
    assert list(out.columns) == keep
    assert "extra_research_col" not in out.columns
    assert "another_unused_flag" not in out.columns
    assert "msf" in out.columns  # filled placeholder


def test_adapt_student_errors_on_missing_required():
    keep = load_column_list(SCHEMA / "kg_student_columns.txt")
    df = pd.DataFrame([{"studentno": 1, "grade": "KG"}])
    with pytest.raises(ValueError, match="missing required"):
        adapt_frame(
            df, keep, fill_if_missing=STUDENT_FILL_IF_MISSING, label="student"
        )


def test_adapt_programs_drops_unnamed():
    keep = load_column_list(SCHEMA / "kg_program_columns.txt")
    df = pd.DataFrame(
        [
            {
                "Unnamed: 0": 0,
                "program_id": "485-GE-KG",
                "school_id": 485,
                "program_type": "GE",
                "capacity": 10,
                "programno": 1,
                "r1_assigned": 0,
                "r1_noenroll": 0,
                "r1_first_choice": 0,
            }
        ]
    )
    out = adapt_frame(df, keep, label="programs")
    assert list(out.columns) == keep
    assert "Unnamed: 0" not in out.columns
