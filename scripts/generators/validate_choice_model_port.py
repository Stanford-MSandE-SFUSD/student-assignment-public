"""Check the exp8 choice-model port against the model's own published output.

``student_assignment/choice_model/exp8.py`` re-implements the feature
construction of SFUSD-Choice-public so that synthetic preference lists can be
generated from public inputs alone. A re-implementation is only trustworthy if
it reproduces the original, so this script recomputes the model's released
per-student utility matrix for the **real** cohort and diffs it cell by cell.

It therefore needs the confidential data and cannot run from a public clone --
same category as ``extract_synthetic_priors.py``. Run it after any change to
the port.

A handful of choice-set cells legitimately differ, because the released matrix
was produced in May 2024 from an older extract of the student file. The model
widens a student's choice set with the program types they ranked in rounds 1
to 3 only; a few students have a language program in ``r4_programs`` in the
current extract, which the older one evidently carried in an earlier round.
Rather than absorb that into a numeric tolerance, this script *classifies*
each mask difference and only passes if every one is explained that way.

Usage:
    python scripts/generators/validate_choice_model_port.py \
        --sfusd-root /share/data/school_choice \
        --weights /share/data/school_choice/simulation-files/choice-model/ChoiceModel_20240514/weights.csv \
        --estimates /share/data/school_choice/simulation-files/choice-model/ChoiceModel_20240514/estimates_2324.csv
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from student_assignment.choice_model import (  # noqa: E402
    ChoiceSetMode,
    compute_utilities,
    load_weights,
)
from student_assignment.choice_model.exp8 import (  # noqa: E402
    HOME_LANG_2_PROG,
    RANKED_TYPE_COLUMNS,
    _parse_type_list,
)

logger = logging.getLogger(__name__)

GRADE = "KG"
# The released matrices are written at full float precision, so agreement
# should be at round-off level. Anything above this means a feature differs.
TOLERANCE = 1e-6


def main() -> int:
    """CLI entry point.

    Returns:
        Process exit status: 0 when the port matches, 1 otherwise.
    """
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sfusd-root", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--estimates", type=Path, required=True)
    parser.add_argument("--year", default="2324")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    args = parser.parse_args()

    cleaned = args.sfusd_root / "Data" / "Cleaned"
    students = pd.read_csv(
        cleaned / f"student_without_specialprogs_{args.year}.csv",
        low_memory=False,
    )
    students = students.loc[students["grade"] == GRADE].reset_index(drop=True)
    programs = pd.read_csv(
        cleaned / f"programs_without_specialprogs_{args.year}.csv", index_col=0
    )
    schools = pd.read_csv(cleaned / f"schools_rehauled_{args.year}.csv")
    weights = load_weights(args.weights)
    logger.info(
        "%d students, %d programs, %d coefficients",
        len(students),
        len(programs),
        len(weights),
    )

    published = pd.read_csv(args.estimates, index_col=0)
    # The released matrix keys students as "<year>-<studentno>".
    published.index = [int(str(x).split("-")[-1]) for x in published.index]

    ours = compute_utilities(
        students,
        programs,
        schools,
        weights,
        mode=ChoiceSetMode.ESTIMATION,
        grade=GRADE,
    )

    shared_students = ours.index.intersection(published.index)
    shared_programs = [c for c in ours.columns if c in published.columns]
    logger.info(
        "comparing %d students x %d programs (published has %d x %d)",
        len(shared_students),
        len(shared_programs),
        len(published.index),
        len(published.columns),
    )
    missing_programs = set(published.columns) - set(ours.columns)
    if missing_programs:
        logger.warning(
            "programs in the published matrix but not ours: %s",
            sorted(missing_programs),
        )

    a = ours.loc[shared_students, shared_programs].to_numpy(dtype=float)
    b = published.loc[shared_students, shared_programs].to_numpy(dtype=float)

    # -inf cells encode "outside the choice set"; they must agree as a mask,
    # and the finite cells must agree numerically.
    a_inf, b_inf = ~np.isfinite(a), ~np.isfinite(b)
    mask_mismatch = int(np.sum(a_inf != b_inf))
    both_finite = ~a_inf & ~b_inf
    diff = np.abs(a[both_finite] - b[both_finite])
    max_diff = float(diff.max()) if diff.size else 0.0
    median_diff = float(np.median(diff)) if diff.size else 0.0

    # Classify the mask differences: a cell where the published matrix is
    # permissive and ours is not is explained if that student ranked a program
    # type in a round beyond r3 which opens the type in question.
    later_round_columns = [
        c
        for c in students.columns
        if c.endswith("_programs") and c not in RANKED_TYPE_COLUMNS
    ]
    program_type_of = dict(
        zip(
            programs["program_id"].astype(str),
            programs["program_type"].astype(str),
        )
    )
    student_row = {int(row.studentno): row for row in students.itertuples()}
    unexplained = []
    for i, j in np.argwhere(a_inf != b_inf):
        student, program = shared_students[i], shared_programs[j]
        if not (a_inf[i, j] and not b_inf[i, j]):
            unexplained.append((student, program, "we are permissive"))
            continue
        opened: set[str] = set()
        row = student_row.get(int(student))
        for column in later_round_columns:
            for ranked in _parse_type_list(getattr(row, column, None)):
                opened.add(ranked)
                for group in HOME_LANG_2_PROG.values():
                    if ranked in group:
                        opened.update(group)
        if program_type_of.get(program) not in opened:
            unexplained.append((student, program, "no later-round type"))

    logger.info(
        "choice-set mask differences: %d of %d (%d explained by later-round "
        "choices in the current extract, %d unexplained)",
        mask_mismatch,
        a.size,
        mask_mismatch - len(unexplained),
        len(unexplained),
    )
    for student, program, why in unexplained[:5]:
        logger.error(
            "  unexplained: student %s program %s (%s)", student, program, why
        )
    logger.info(
        "finite cells: %d | max abs diff %.3e | median abs diff %.3e",
        int(both_finite.sum()),
        max_diff,
        median_diff,
    )
    over = int(np.sum(diff > args.tolerance))
    if over:
        logger.error("%d cells exceed the tolerance %.1e", over, args.tolerance)
        rows, cols = np.where(both_finite)
        worst = np.argsort(-np.abs(a[both_finite] - b[both_finite]))[:5]
        for k in worst:
            i, j = rows[k], cols[k]
            logger.error(
                "  student %s program %s: ours %.6f published %.6f",
                shared_students[i],
                shared_programs[j],
                a[i, j],
                b[i, j],
            )

    ok = not unexplained and over == 0
    logger.info("PORT %s", "MATCHES the published model" if ok else "DIFFERS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
