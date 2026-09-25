"""Adapt cleaned or synthetic CSVs to the shared KG paper/simulator schema.

Full research cleaned files may include extra columns beyond the KG paper
schema. This script selects and orders columns so Track A and Track B inputs
match. See ``docs/KG_SCHEMA.md``.

Example::

    uv run python scripts/preprocessing/adapt_to_kg_schema.py \\
      --student Data/Cleaned/student_2324.csv \\
      --programs Data/Cleaned/programs_2324.csv \\
      --schools Data/Cleaned/schools_rehauled_2324.csv \\
      --out-dir local-data/kg_ready
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"

# Placeholder columns: if missing, add empty (KG packs often leave these blank).
STUDENT_FILL_IF_MISSING = {
    "msf",
    "r2_ranked_idschool",
    "r2_listed_ranks",
    "r2_programs",
    "r2_randomnumber",
    "r2_cohortstring",
    "r2_designation_randomnumber",
    "r2_idschool",
    "r2_programcode",
    "r2_rank",
    "r2_isdesignation",
    "r2_distance",
}


def load_column_list(path: Path) -> list[str]:
    """Load a one-name-per-line schema file (``#`` comments allowed)."""
    cols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cols.append(line)
    return cols


def adapt_frame(
    df: pd.DataFrame,
    keep: list[str],
    *,
    fill_if_missing: set[str] | None = None,
    label: str = "table",
) -> pd.DataFrame:
    """Return ``df`` restricted to ``keep`` in order.

    Args:
        df: Input frame (may be a column superset).
        keep: Target column order.
        fill_if_missing: Names to create as empty if absent.
        label: Name used in log messages.

    Returns:
        Adapted frame.

    Raises:
        ValueError: A required keep-column is missing and not fillable.
    """
    fill_if_missing = fill_if_missing or set()
    # Drop anonymous index columns from older exports.
    drop_unnamed = [c for c in df.columns if str(c).startswith("Unnamed:")]
    if drop_unnamed:
        df = df.drop(columns=drop_unnamed)
        print(f"[{label}] dropped {drop_unnamed}")

    extras = [c for c in df.columns if c not in keep]
    if extras:
        print(f"[{label}] dropping {len(extras)} extra column(s): {extras}")

    missing = [c for c in keep if c not in df.columns]
    required_missing = [c for c in missing if c not in fill_if_missing]
    if required_missing:
        raise ValueError(
            f"[{label}] missing required columns: {required_missing}"
        )

    out = df.copy()
    for col in missing:
        out[col] = pd.NA
        print(f"[{label}] filled missing placeholder column: {col}")

    return out[keep]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Restrict student/program/school CSVs to the shared KG schema."
        )
    )
    parser.add_argument(
        "--student",
        type=Path,
        help="Input student CSV (cleaned or synthetic).",
    )
    parser.add_argument(
        "--programs",
        type=Path,
        help="Input programs CSV.",
    )
    parser.add_argument(
        "--schools",
        type=Path,
        help="Input schools_rehauled-style CSV.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("local-data/kg_ready"),
        help="Directory for adapted CSVs (default: local-data/kg_ready).",
    )
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=SCHEMA_DIR,
        help="Directory with kg_*_columns.txt files.",
    )
    parser.add_argument(
        "--student-out-name",
        default=None,
        help="Output student filename (default: same as input name).",
    )
    parser.add_argument(
        "--programs-out-name",
        default=None,
        help="Output programs filename (default: same as input name).",
    )
    parser.add_argument(
        "--schools-out-name",
        default=None,
        help="Output schools filename (default: same as input name).",
    )
    args = parser.parse_args(argv)

    if not any([args.student, args.programs, args.schools]):
        parser.error("Provide at least one of --student / --programs / --schools")

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    schema_dir: Path = args.schema_dir

    if args.student:
        keep = load_column_list(schema_dir / "kg_student_columns.txt")
        df = pd.read_csv(args.student, low_memory=False)
        adapted = adapt_frame(
            df,
            keep,
            fill_if_missing=STUDENT_FILL_IF_MISSING,
            label="student",
        )
        name = args.student_out_name or args.student.name
        path = out_dir / name
        adapted.to_csv(path, index=False)
        print(f"[student] wrote {path} ({len(adapted)} rows, {len(adapted.columns)} cols)")

    if args.programs:
        keep = load_column_list(schema_dir / "kg_program_columns.txt")
        df = pd.read_csv(args.programs, low_memory=False)
        adapted = adapt_frame(df, keep, label="programs")
        name = args.programs_out_name or args.programs.name
        path = out_dir / name
        adapted.to_csv(path, index=False)
        print(f"[programs] wrote {path} ({len(adapted)} rows, {len(adapted.columns)} cols)")

    if args.schools:
        keep = load_column_list(schema_dir / "kg_school_columns.txt")
        df = pd.read_csv(args.schools, low_memory=False)
        # schools_rehauled sometimes uses school_id as index column 0
        if "school_id" not in df.columns and df.index.name == "school_id":
            df = df.reset_index()
        elif "school_id" not in df.columns and df.columns[0] in (
            "Unnamed: 0",
            "index",
        ):
            df = df.rename(columns={df.columns[0]: "school_id"})
        adapted = adapt_frame(df, keep, label="schools")
        name = args.schools_out_name or args.schools.name
        path = out_dir / name
        adapted.to_csv(path, index=False)
        print(f"[schools] wrote {path} ({len(adapted)} rows, {len(adapted.columns)} cols)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
