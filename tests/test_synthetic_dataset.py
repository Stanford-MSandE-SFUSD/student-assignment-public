"""Checks on the committed public synthetic dataset in data/synthetic_2324/.

Three things are worth guarding for a public release:

1. the files are there and have the schema the loader expects;
2. the dataset is internally consistent (lists, priorities and outcomes agree);
3. the committed CSVs are exactly what the committed priors regenerate, so the
   documented two-stage pipeline in data/synthetic_2324/ANONYMIZATION.md is
   verifiably the provenance of the released records.

Run: python -m pytest tests/test_synthetic_dataset.py -v
"""

import ast
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "synthetic_2324"
YEAR = "2324"
GENERATOR = (
    REPO_ROOT / "scripts" / "generators" / "generate_synthetic_dataset.py"
)

STUDENT_CSV = DATA_DIR / f"student_{YEAR}_synthetic.csv"
PROGRAMS_CSV = DATA_DIR / f"programs_without_specialprogs_{YEAR}.csv"
SCHOOLS_CSV = DATA_DIR / "Cleaned" / f"schools_rehauled_{YEAR}.csv"
PRIORS_JSON = DATA_DIR / "priors" / f"synthetic_priors_{YEAR}.json"
BLOCKS_CSV = DATA_DIR / "reference" / f"block_reference_{YEAR}.csv"
ZONES_CSV = DATA_DIR / "zones" / "concept1zones.csv"

# Columns the simulator reads off the student table; see
# student_assignment/data_interfaces/students.py.
REQUIRED_COLUMNS = [
    "studentno",
    "grade",
    "r1_ranked_idschool",
    "r1_programs",
    "r1_listed_ranks",
    "r1_randomnumber",
    "r1_cohortstring",
    "latitude",
    "longitude",
    "idschoolattendance",
    "ctip1",
    "census_block",
    "census_blockgroup",
    "freelunch_prob",
    "reducedlunch_prob",
    "FRL Score",
    "N'hood SES Score",
    "AALPI Score",
    "HOCidx1",
    "median_hh_income",
    "resolved_ethnicity",
    "homelang",
    "englprof",
    "sped",
    "sibling",
    "currentlpsibling",
    "currentlp",
    "aaprek",
    "prek",
    "aa",
    "previous_pathway",
    "requestprogramdesignation",
    "num_ranked",
    "final_school",
    "enrolled_idschool",
    "msf",
    "zipcode",
    "lowell_ranked",
    "sota_ranked",
]


@pytest.fixture(scope="module")
def students() -> pd.DataFrame:
    """The committed synthetic student table, with lists parsed."""
    df = pd.read_csv(STUDENT_CSV, low_memory=False)
    for column in (
        "r1_ranked_idschool",
        "r1_programs",
        "r1_cohortstring",
        "sibling",
    ):
        df[column] = df[column].fillna("[]").apply(ast.literal_eval)
    return df


def test_files_present():
    """Every file the dataset README advertises must exist."""
    expected = [
        STUDENT_CSV,
        PROGRAMS_CSV,
        SCHOOLS_CSV,
        PRIORS_JSON,
        BLOCKS_CSV,
        ZONES_CSV,
        DATA_DIR / "README.md",
        DATA_DIR / "ANONYMIZATION.md",
        DATA_DIR / "FIDELITY.md",
    ]
    missing = [str(path) for path in expected if not path.is_file()]
    assert not missing, f"Missing dataset files: {missing}"


def test_schema(students):
    """The student table must carry every column the loader touches."""
    missing = [c for c in REQUIRED_COLUMNS if c not in students.columns]
    assert not missing, f"Missing columns: {missing}"
    assert (students["grade"] == "KG").all()
    assert students["studentno"].is_unique
    # Two rounds of columns, so Students.rounds resolves to 2.
    rounds = {int(c[1]) for c in students.columns if "_ranked_idschool" in c}
    assert rounds == {1, 2}


def test_no_source_identifiers(students):
    """Student numbers must be the regenerated sequential ids, not source ones."""
    assert students["studentno"].min() >= 1_000_000
    assert students["studentno"].max() < 1_000_000 + 10 * len(students)


def test_lists_are_internally_consistent(students):
    """Per-choice columns must all have the same length as the ranked list."""
    lengths = students["r1_ranked_idschool"].apply(len)
    assert (students["r1_programs"].apply(len) == lengths).all()
    assert (students["r1_cohortstring"].apply(len) == lengths).all()
    ranks = students["r1_listed_ranks"].apply(lambda s: ast.literal_eval(s))
    assert (ranks.apply(len) == lengths).all()
    randoms = students["r1_randomnumber"].apply(lambda s: ast.literal_eval(s))
    assert (randoms.apply(len) == lengths).all()
    # A school may appear twice (an immersion pathway plus general education),
    # but the same program must never be ranked twice.
    pairs = [
        list(zip(lst, codes))
        for lst, codes in zip(
            students["r1_ranked_idschool"], students["r1_programs"]
        )
    ]
    assert all(len(set(p)) == len(p) for p in pairs)


def test_choices_reference_real_programs(students):
    """Every (school, program type) ranked must exist at that school."""
    programs = pd.read_csv(PROGRAMS_CSV, index_col=0)
    with open(PRIORS_JSON) as handle:
        priors = json.load(handle)
    offered = {
        int(k): set(v)
        for k, v in priors["choice"]["school_program_types"].items()
    }
    schools = set(pd.read_csv(SCHOOLS_CSV)["school_id"])
    assert set(programs["school_id"]) <= schools
    bad = [
        (school, code)
        for lst, codes in zip(
            students["r1_ranked_idschool"], students["r1_programs"]
        )
        for school, code in zip(lst, codes)
        if code not in offered.get(int(school), set())
    ]
    assert not bad, f"Choices at schools that do not offer them: {set(bad)}"


def test_round1_offers_respect_capacity(students):
    """The shipped round-1 outcome must not over-fill any program."""
    programs = pd.read_csv(PROGRAMS_CSV, index_col=0)
    capacity = dict(zip(programs["program_id"], programs["capacity"]))
    offered = students.dropna(subset=["r1_idschool", "r1_programcode"])
    counts = (
        offered["r1_idschool"].astype(int).astype(str)
        + "-"
        + offered["r1_programcode"]
        + "-KG"
    ).value_counts()
    over = {p: int(n) for p, n in counts.items() if n > capacity.get(p, 10**6)}
    assert not over, f"Programs over capacity: {over}"
    # The programs table's outcome columns are derived from this same cohort.
    assert programs["r1_assigned"].sum() == pytest.approx(len(offered))


def test_geography_is_in_the_block_reference(students):
    """Blocks, block groups and coordinates must come from the public reference."""
    blocks = pd.read_csv(BLOCKS_CSV)
    known = set(blocks["Block"].astype("int64"))
    used = set(students["census_block"].dropna().astype("int64"))
    assert used <= known
    located = students.dropna(subset=["latitude", "longitude"])
    assert located["latitude"].between(37.70, 37.84).all()
    assert located["longitude"].between(-122.53, -122.34).all()


def test_regenerates_from_committed_priors(tmp_path):
    """The committed CSVs must be exactly what the committed priors produce."""
    spec = importlib.util.spec_from_file_location(
        "synthetic_generator", GENERATOR
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["synthetic_generator"] = module
    spec.loader.exec_module(module)

    work = tmp_path / "synthetic"
    (work / "priors").mkdir(parents=True)
    (work / "reference").mkdir(parents=True)
    (work / "Cleaned").mkdir(parents=True)
    shutil.copy(PRIORS_JSON, work / "priors" / PRIORS_JSON.name)
    shutil.copy(BLOCKS_CSV, work / "reference" / BLOCKS_CSV.name)
    shutil.copy(SCHOOLS_CSV, work / "Cleaned" / SCHOOLS_CSV.name)
    shutil.copy(PROGRAMS_CSV, work / PROGRAMS_CSV.name)

    module.generate(work, YEAR, seed=20260917)

    for name in (f"student_{YEAR}_synthetic.csv", PROGRAMS_CSV.name):
        assert (work / name).read_text() == (DATA_DIR / name).read_text(), (
            f"{name} differs from the committed copy; regenerate the dataset or "
            "check the generator for non-determinism"
        )
    assert (
        work / "zones" / "concept1zones.csv"
    ).read_text() == ZONES_CSV.read_text()
