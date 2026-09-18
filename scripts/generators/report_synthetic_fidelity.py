"""Compare the synthetic dataset against the confidential source cohort.

Produces the fidelity table shipped as ``data/synthetic_2324/FIDELITY.md``.
Like ``extract_synthetic_priors.py`` this needs the confidential data, so it
cannot be re-run from a public clone; the point of committing it is that the
numbers in the released table can be audited by anyone with data access.

Every statistic reported here is an aggregate over hundreds or thousands of
applicants -- the same class of quantity the priors file already releases.

Usage:
    python scripts/generators/report_synthetic_fidelity.py \
        --sfusd-root /share/data/school_choice \
        --data-dir data/synthetic_2324 \
        --out data/synthetic_2324/FIDELITY.md
"""

import argparse
import ast
import datetime as _dt
import logging
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from student_assignment.choice_model import geodesic_miles  # noqa: E402

logger = logging.getLogger(__name__)

GRADE = "KG"
LIST_COLUMNS = ("r1_ranked_idschool", "r1_programs", "sibling")
# `map_ethnicity` in student_assignment/evaluation/short_match_evaluator.py
# folds these labels into the AALPI groups the equity metrics are built on.
AALPI_LABELS = {
    "Black or African American",
    "Black/African American",
    "Hispanic/Latino",
    "Hispanic/Latinx",
    "Hispanic",
    "Samoan",
    "Pacific Islander",
    "Other Pacific Islander",
    "Hawaiian Native",
}


def _load(path: Path) -> pd.DataFrame:
    """Load a student table and parse its list-valued columns."""
    df = pd.read_csv(path, low_memory=False)
    if "grade" in df.columns:
        df = df.loc[df["grade"] == GRADE].reset_index(drop=True)
    for column in LIST_COLUMNS:
        df[column] = df[column].fillna("[]").apply(ast.literal_eval)
    df["n_listed"] = df["r1_ranked_idschool"].apply(len)
    return df


def _choice_distances(df: pd.DataFrame, school_ll: pd.DataFrame) -> dict:
    """Mean home-to-school distance of ranked choices, by list position."""
    buckets: dict[int, list] = {}
    located = df.dropna(subset=["latitude", "longitude"])
    for row in located.itertuples():
        for position, school in enumerate(row.r1_ranked_idschool, start=1):
            if int(school) not in school_ll.index:
                continue
            lat, lon = school_ll.loc[int(school)]
            buckets.setdefault(min(position, 8), []).append(
                geodesic_miles(row.latitude, row.longitude, lat, lon)
            )
    return {k: float(np.mean(v)) for k, v in sorted(buckets.items())}


def _share(counter: Counter) -> pd.Series:
    """Normalise a counter into a share series."""
    total = sum(counter.values())
    return (
        pd.Series({k: v / total for k, v in counter.items()})
        if total
        else pd.Series()
    )


def _rows(
    real: pd.DataFrame, syn: pd.DataFrame, school_ll: pd.DataFrame
) -> list:
    """Build the (section, statistic, real, synthetic) rows of the report."""
    out = []

    def add(section, name, real_value, syn_value, fmt="{:.3f}"):
        out.append(
            (
                section,
                name,
                fmt.format(real_value) if real_value is not None else "-",
                fmt.format(syn_value) if syn_value is not None else "-",
            )
        )

    aa_real = real["idschoolattendance"].value_counts()
    aa_syn = syn["idschoolattendance"].value_counts()
    joined = pd.DataFrame({"real": aa_real, "syn": aa_syn}).dropna()
    add("Cohort", "Applicants", len(real), len(syn), "{:.0f}")
    add(
        "Cohort",
        "Attendance areas",
        real["idschoolattendance"].nunique(),
        syn["idschoolattendance"].nunique(),
        "{:.0f}",
    )
    add(
        "Cohort",
        "Correlation of applicants per attendance area",
        None,
        joined["real"].corr(joined["syn"]),
    )
    add(
        "Cohort",
        "Largest absolute difference in applicants per area",
        None,
        (joined["real"] - joined["syn"]).abs().max(),
        "{:.0f}",
    )

    add(
        "Ranked lists",
        "Mean list length",
        real["n_listed"].mean(),
        syn["n_listed"].mean(),
    )
    add(
        "Ranked lists",
        "Median list length",
        real["n_listed"].median(),
        syn["n_listed"].median(),
        "{:.0f}",
    )
    add(
        "Ranked lists",
        "Share filing no list",
        (real["n_listed"] == 0).mean(),
        (syn["n_listed"] == 0).mean(),
    )
    add(
        "Ranked lists",
        "Share filing 10 or more choices",
        (real["n_listed"] >= 10).mean(),
        (syn["n_listed"] >= 10).mean(),
    )
    for name, df in (("real", real), ("syn", syn)):
        df["_aa_first"] = [
            (bool(lst) and not pd.isna(aa) and int(lst[0]) == int(aa))
            for lst, aa in zip(
                df["r1_ranked_idschool"], df["idschoolattendance"]
            )
        ]
        df["_aa_in"] = [
            (bool(lst) and not pd.isna(aa) and int(aa) in lst)
            for lst, aa in zip(
                df["r1_ranked_idschool"], df["idschoolattendance"]
            )
        ]
    listed_real = real[real["n_listed"] > 0]
    listed_syn = syn[syn["n_listed"] > 0]
    add(
        "Ranked lists",
        "First choice is own attendance-area school",
        listed_real["_aa_first"].mean(),
        listed_syn["_aa_first"].mean(),
    )
    add(
        "Ranked lists",
        "Own attendance-area school appears in list",
        listed_real["_aa_in"].mean(),
        listed_syn["_aa_in"].mean(),
    )

    first_real = _share(
        Counter(int(x[0]) for x in real["r1_ranked_idschool"] if x)
    )
    first_syn = _share(
        Counter(int(x[0]) for x in syn["r1_ranked_idschool"] if x)
    )
    any_real = _share(
        Counter(int(s) for x in real["r1_ranked_idschool"] for s in x)
    )
    any_syn = _share(
        Counter(int(s) for x in syn["r1_ranked_idschool"] for s in x)
    )
    first = pd.DataFrame({"real": first_real, "syn": first_syn}).fillna(0)
    anywhere = pd.DataFrame({"real": any_real, "syn": any_syn}).fillna(0)
    add(
        "School demand",
        "Correlation of first-choice share across schools",
        None,
        first["real"].corr(first["syn"]),
    )
    add(
        "School demand",
        "Correlation of any-rank share across schools",
        None,
        anywhere["real"].corr(anywhere["syn"]),
    )
    add(
        "School demand",
        "Total absolute deviation in first-choice share",
        None,
        (first["real"] - first["syn"]).abs().sum(),
    )

    type_real = _share(Counter(p for x in real["r1_programs"] for p in x))
    type_syn = _share(Counter(p for x in syn["r1_programs"] for p in x))
    add(
        "Program type",
        "General education share of choices",
        type_real.get("GE", 0),
        type_syn.get("GE", 0),
    )
    add(
        "Program type",
        "Language pathway share of choices",
        1 - type_real.get("GE", 0),
        1 - type_syn.get("GE", 0),
    )

    def _repeat_share(df: pd.DataFrame) -> float:
        repeats = total = 0
        for lst in df["r1_ranked_idschool"]:
            seen = set()
            for school in lst:
                total += 1
                repeats += school in seen
                seen.add(school)
        return repeats / total if total else 0.0

    def _repeat_applicants(df: pd.DataFrame) -> float:
        return float(
            np.mean(
                [len(set(lst)) != len(lst) for lst in df["r1_ranked_idschool"]]
            )
        )

    add(
        "Program type",
        "Share of choices repeating a school already ranked",
        _repeat_share(real),
        _repeat_share(syn),
    )
    add(
        "Program type",
        "Share of applicants ranking one school twice",
        _repeat_applicants(listed_real),
        _repeat_applicants(listed_syn),
    )
    add(
        "Program type",
        "Total absolute deviation across program types",
        None,
        pd.DataFrame({"real": type_real, "syn": type_syn})
        .fillna(0)
        .diff(axis=1)
        .iloc[:, 1]
        .abs()
        .sum(),
    )

    real_dist = _choice_distances(real, school_ll)
    syn_dist = _choice_distances(syn, school_ll)
    for position in sorted(real_dist):
        label = "8+" if position == 8 else str(position)
        add(
            "Choice distance (mi)",
            f"Mean distance of choice at position {label}",
            real_dist[position],
            syn_dist.get(position),
            "{:.2f}",
        )

    for column, label in (
        ("freelunch_prob", "Free-lunch probability of home block"),
        ("AALPI Score", "AALPI score of home block"),
        ("N'hood SES Score", "Neighbourhood SES score of home block"),
        ("HOCidx1", "Home opportunity index of home block"),
    ):
        add(
            "Block attributes",
            f"{label}: mean",
            real[column].mean(),
            syn[column].mean(),
        )
        add(
            "Block attributes",
            f"{label}: std. dev.",
            real[column].std(),
            syn[column].std(),
        )
    add(
        "Block attributes",
        "CTIP1 share",
        real["ctip1"].mean(),
        syn["ctip1"].mean(),
    )
    add(
        "Block attributes",
        "Median household income: mean",
        real["median_hh_income"].mean(),
        syn["median_hh_income"].mean(),
        "{:,.0f}",
    )

    for column, label in (
        ("resolved_ethnicity", "ethnicity"),
        ("homelang", "home language"),
        ("englprof", "English proficiency"),
    ):
        shares = pd.DataFrame(
            {
                "real": real[column].value_counts(normalize=True),
                "syn": syn[column].value_counts(normalize=True),
            }
        ).fillna(0)
        add(
            "Demographics",
            f"Total absolute deviation across {label} categories",
            None,
            (shares["real"] - shares["syn"]).abs().sum(),
        )
    for name, df in (("real", real), ("syn", syn)):
        df["_aalpi"] = df["resolved_ethnicity"].isin(AALPI_LABELS)
    add(
        "Demographics",
        "AALPI share",
        real["_aalpi"].mean(),
        syn["_aalpi"].mean(),
    )
    add(
        "Segregation signal",
        "Mean block free-lunch probability, AALPI applicants",
        real.loc[real["_aalpi"], "freelunch_prob"].mean(),
        syn.loc[syn["_aalpi"], "freelunch_prob"].mean(),
    )
    add(
        "Segregation signal",
        "Mean block free-lunch probability, other applicants",
        real.loc[~real["_aalpi"], "freelunch_prob"].mean(),
        syn.loc[~syn["_aalpi"], "freelunch_prob"].mean(),
    )
    add(
        "Segregation signal",
        "CTIP1 share, AALPI applicants",
        real.loc[real["_aalpi"], "ctip1"].mean(),
        syn.loc[syn["_aalpi"], "ctip1"].mean(),
    )
    add(
        "Segregation signal",
        "CTIP1 share, other applicants",
        real.loc[~real["_aalpi"], "ctip1"].mean(),
        syn.loc[~syn["_aalpi"], "ctip1"].mean(),
    )

    def _sibling_first(df: pd.DataFrame) -> float:
        rows = [
            (lst, sib)
            for lst, sib in zip(df["r1_ranked_idschool"], df["sibling"])
            if sib and lst
        ]
        return (
            float(np.mean([lst[0] in sib for lst, sib in rows]))
            if rows
            else 0.0
        )

    def _sibling_in_list(df: pd.DataFrame) -> float:
        rows = [
            (lst, sib)
            for lst, sib in zip(df["r1_ranked_idschool"], df["sibling"])
            if sib and lst
        ]
        return (
            float(np.mean([any(s in lst for s in sib) for lst, sib in rows]))
            if rows
            else 0.0
        )

    add(
        "Choice model",
        "Sibling's school is the first choice",
        _sibling_first(listed_real),
        _sibling_first(listed_syn),
    )
    add(
        "Choice model",
        "Sibling's school appears in the list",
        _sibling_in_list(listed_real),
        _sibling_in_list(listed_syn),
    )

    for column, label in (
        ("sibling", "sibling priority"),
        ("aaprek", "attendance-area pre-K priority"),
        ("prek", "citywide pre-K priority"),
        ("currentlp", "current language pathway"),
        ("aa", "attendance-area priority applied"),
    ):
        if column == "sibling":
            real_rate = (real[column].apply(len) > 0).mean()
            syn_rate = (syn[column].apply(len) > 0).mean()
        else:
            real_rate = (real[column].fillna("[]") != "[]").mean()
            syn_rate = (syn[column].fillna("[]") != "[]").mean()
        add("Priorities", f"Share with {label}", real_rate, syn_rate)

    add(
        "Round 1 outcome",
        "Share of applicants with a list left with no offer",
        listed_real["r1_idschool"].isna().mean(),
        listed_syn["r1_idschool"].isna().mean(),
    )
    add(
        "Round 1 outcome",
        "Share of applicants with a list offered their first choice",
        (listed_real["r1_rank"] == 1).mean(),
        (listed_syn["r1_rank"] == 1).mean(),
    )

    def _offer_on_list(df: pd.DataFrame) -> float:
        offered = df.dropna(subset=["r1_idschool"])
        return float(
            np.mean(
                [
                    int(school) in lst
                    for school, lst in zip(
                        offered["r1_idschool"], offered["r1_ranked_idschool"]
                    )
                ]
            )
        )

    add(
        "Round 1 outcome",
        "Share of offers that are on the applicant's own list",
        _offer_on_list(listed_real),
        _offer_on_list(listed_syn),
    )
    add(
        "Round 1 outcome",
        "Mean distance to the round-1 offer (mi)",
        real["r1_distance"].mean(),
        syn["r1_distance"].mean(),
        "{:.2f}",
    )
    return out


def write_report(rows: list, out_path: Path, year: str) -> None:
    """Write the fidelity table as markdown.

    Args:
        rows: ``(section, statistic, real, synthetic)`` tuples.
        out_path: File to write.
        year: Two-school-year tag of the source cohort.
    """
    lines = [
        f"# Fidelity of the synthetic {year} kindergarten cohort",
        "",
        "Generated by `scripts/generators/report_synthetic_fidelity.py`"
        f" on {_dt.date.today().isoformat()}.",
        "",
        "Each row compares one aggregate statistic of the confidential source",
        "cohort with the same statistic in the released synthetic dataset. A",
        "dash in the source column means the statistic is only defined across",
        "the two datasets (a correlation or a total deviation).",
        "",
        "See `ANONYMIZATION.md` for which differences are deliberate.",
        "",
    ]
    current = None
    for section, name, real_value, syn_value in rows:
        if section != current:
            lines += [
                "",
                f"## {section}",
                "",
                "| Statistic | Source | Synthetic |",
                "| --- | --- | --- |",
            ]
            current = section
        lines.append(f"| {name} | {real_value} | {syn_value} |")
    lines.append("")
    out_path.write_text("\n".join(lines))
    logger.info("wrote %s (%d statistics)", out_path, len(rows))


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sfusd-root", type=Path, required=True)
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data/synthetic_2324")
    )
    parser.add_argument("--year", default="2324")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    real = _load(
        args.sfusd_root / "Data" / "Cleaned" / f"student_{args.year}.csv"
    )
    syn = _load(args.data_dir / f"student_{args.year}_synthetic.csv")
    schools = pd.read_csv(
        args.data_dir / "Cleaned" / f"schools_rehauled_{args.year}.csv"
    ).dropna(subset=["lat", "lon"])
    school_ll = schools.set_index("school_id")[["lat", "lon"]]
    rows = _rows(real, syn, school_ll)
    write_report(rows, args.out or args.data_dir / "FIDELITY.md", args.year)


if __name__ == "__main__":
    main()
