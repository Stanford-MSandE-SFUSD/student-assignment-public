"""Extract privacy-protected aggregate priors from the confidential SFUSD data.

Stage 1 of 2 for building the public synthetic dataset. This script is the ONLY
step that touches confidential student records. It emits

  * ``synthetic_priors_<year>.json`` -- every aggregate the generator consumes,
    each one noised (Laplace), small-cell suppressed and/or geographically
    coarsened, and
  * ``block_reference_<year>.csv`` -- a public-geography lookup (census block ->
    block group / tract / ZIP / attendance area / child population / TIGER
    internal point) built from the census block shapefile and the SFUSD block
    database, containing no student-derived counts and no CTIP flag.
  * ``ctip_by_tract_<year>.csv`` -- tract-level CTIP1 (0/1), collapsed from the
    SFUSD block workbook's CTIP assignment (constant within tract). Stage 2
    joins block to tract to CTIP1.

Stage 2 (``generate_synthetic_dataset.py``) reads only these committed
artifacts, so the disclosure surface of the released dataset is exactly what
is committed here and can be audited independently of the synthetic records
themselves.

Usage:
    python scripts/generators/extract_synthetic_priors.py \
        --sfusd-root <SFUSD_DATA_PATH> \
        --seed-file <private seed file> \
        --out-dir data/synthetic_2324

The noise seed is private
-------------------------
Every Laplace draw in this script comes from ``--seed``. Anyone who knows that
seed can regenerate the noise and subtract it from the released counts, so the
seed must be high-entropy (e.g. ``secrets.randbits(128)``), kept by the data
custodians, and never committed. It has no default and is not written to the
priors file. Prefer ``--seed-file`` over ``--seed`` so it stays out of shell
history. Stage 2 uses its own, separate public seed.

Recreating the shipped priors
-----------------------------
The file committed at ``data/synthetic_2324/priors/synthetic_priors_2324.json``
is variant ``joint_v4_blend1`` (profile ``joint_frl_eth``, ``race_frl_aa_blend``
1.0), extracted with the custodians' private seed. Pass ``--variant joint_v4_blend1``. That sets the
stored blend weight to 1.0 (100% attendance-area race, 0% FRL tercile) and
stamps ``meta.variant``, ``meta.parent_variant``, ``meta.privacy_revision``,
and ``meta.race_frl_aa_blend_override``. The weight is not used while the
histograms are built. ``--profile joint_frl_eth`` without ``--variant`` still
writes ``race_frl_aa_blend`` 0.5 and does not stamp those meta fields.

Local inputs, in addition to a checkout of this branch:

  * the confidential Table-1 student file,
    ``r1_filter_student_without_specialprogs_2324.csv`` (KG applicants with a
    nonempty round-1 list; the full ``student_2324.csv`` does not match)
  * the private extraction seed
  * ``schools_rehauled_2324.csv`` (columns ``school_id``, ``school_name``)
  * cleaned ``programs_without_specialprogs_2324.csv`` (columns ``school_id``,
    ``program_type``). Not the synthetic programs file.

``--reuse-block-reference data/synthetic_2324/reference/block_reference_2324.csv``
copies that committed file and the sibling ``ctip_by_tract_2324.csv``. The
census block shapefile and the SFUSD block workbook are not required.

    python scripts/generators/extract_synthetic_priors.py \\
        --sfusd-root <SFUSD root> \\
        --student-csv <path>/r1_filter_student_without_specialprogs_2324.csv \\
        --schools-csv <path>/schools_rehauled_2324.csv \\
        --programs-csv <path>/programs_without_specialprogs_2324.csv \\
        --reuse-block-reference data/synthetic_2324/reference/block_reference_2324.csv \\
        --profile joint_frl_eth \\
        --variant joint_v4_blend1 \\
        --seed-file <private seed file> \\
        --year 2324 \\
        --out-dir <output>

``meta.generated`` is the day of the run. Ignore it when diffing against the
committed file. If the student file has at least 20 non-null ``sped`` or
``speced`` values in a CTIP group, this script estimates a SPED rate and adds
a ``SPED rate`` query. The committed file has the fallback ``0.11`` / ``0.11``
and no SPED query, which is what this script writes when that column is
missing or too thin to release.
"""

import argparse
import ast
import datetime as _dt
import json
import logging
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Privacy parameters. Every count-based prior below is protected by (a) Laplace
# noise at LAPLACE_EPS, (b) suppression of cells whose noisy count is under
# MIN_CELL, and (c) Dirichlet smoothing toward a coarser parent distribution.
# ---------------------------------------------------------------------------
LAPLACE_EPS = 0.5  # per query family; noise scale assumes one student moves one cell by 1
MIN_CELL = 5  # noisy cell counts below this are suppressed to zero
MIN_RATE_DEN = (
    20  # conditional rates below this denominator fall back to the parent
)
PRIOR_FLOOR = 2.0  # minimum parent-prior weight, in applicant-equivalents
TILT_CAP = 8.0  # ceiling on a standardized CTIP1 tilt factor
MIN_BG_BLOCKS = 3  # block group needs this many distinct blocks ...
MIN_BG_STUDENTS = 5  # ... and this many students, else fall back to tract
ATTR_ROUND = 3  # decimals kept for block-group attributes
# Exact cohort scalars are coarsened (not Laplace) before release.
FRL_EDGE_ROUND = 0.05  # frl_bin_edges snapped to this grid


def _round_to_grid(value: float, step: float) -> float:
    """Snap ``value`` to the nearest multiple of ``step`` (stable decimals)."""
    return round(round(float(value) / step) * step, 10)

GRADE = "KG"

# Coarse ethnicity groups. These match ``map_ethnicity`` in
# student_assignment/evaluation/short_match_evaluator.py so that the AALPI
# metrics see the same categories the evaluator builds. "PI/Other" pools the
# Pacific Islander, American Indian and residual labels: citywide they are ~0.5%
# of the cohort, far too few to condition on geographically.
COARSE_ETHNICITY = {
    "Asian": "Asian",
    "Asian Indian": "Asian",
    "Chinese": "Asian",
    "Vietnamese": "Asian",
    "Filipino": "Asian",
    "Japanese": "Asian",
    "Korean": "Asian",
    "Hmong": "Asian",
    "Other Asian": "Asian",
    "Cambodian": "Asian",
    "Laotian": "Asian",
    "Hispanic/Latino": "Hispanic",
    "Hispanic/Latinx": "Hispanic",
    "Hispanic": "Hispanic",
    "White": "White",
    "Middle Eastern/Arabic": "White",
    "Middle Eastern/Arab": "White",
    "Black or African American": "Black",
    "Black/African American": "Black",
    # SFUSD extracts use "Two or More Races"; older files used "Multi-Racial".
    "Two or More Races": "TwoOrMore",
    "Multi-Racial": "TwoOrMore",
    "Multiracial": "TwoOrMore",
    "Two or More": "TwoOrMore",
    "Decline to State": "Decline",
    "Decline To State": "Decline",
}
PI_OTHER = "PI/Other"

# Canonicalize raw ethnicity labels before binning (joint profile only).
ETHNICITY_LABEL_FIXES = {
    "Multi-Racial": "Two or More Races",
    "Multiracial": "Two or More Races",
    "Two or More": "Two or More Races",
    "Middle Eastern/Arab": "Middle Eastern/Arabic",
    "Hispanic": "Hispanic/Latino",
    "Hispanic/Latinx": "Hispanic/Latino",
    "Black/African American": "Black or African American",
}
INVALID_ETHNICITY_LABELS = {"1/0/00", "0", "nan", "none", ""}

# FRL tercile labels for the race|FRL prior family (joint profile).
FRL_BIN_LABELS = ("low", "mid", "high")

# Internal extract/generate profiles (priors meta / CLI). The shipped public
# folder is always data/synthetic_2324/; profile names never appear as "v1"/"v2".
PROFILE_BASELINE = "baseline"
PROFILE_JOINT_FRL_ETH = "joint_frl_eth"
VALID_PROFILES = (PROFILE_BASELINE, PROFILE_JOINT_FRL_ETH)

# Shipped public priors: data/synthetic_2324/priors/synthetic_priors_2324.json.
# race_frl_aa_blend is the weight on the attendance-area race distribution in
# generate_synthetic_dataset.blend_dists. 1.0 stores the FRL tercile table and
# does not mix it into the race draw. The plain joint_frl_eth profile writes 0.5.
VARIANT_JOINT_V4_BLEND1 = "joint_v4_blend1"
VALID_VARIANTS = (VARIANT_JOINT_V4_BLEND1,)
SHIPPED_RACE_FRL_AA_BLEND = 1.0
SHIPPED_PARENT_VARIANT = "joint_v3"
SHIPPED_PRIVACY_REVISION = "2026-09-24-private-noise-seed"

# Home-language groups used to condition the program-type choice. Only languages
# with a matching SFUSD pathway get their own group.
HOMELANG_GROUPS = {
    "EN": "EN",
    "SP": "SP",
    "CC": "ZH",
    "CM": "ZH",
    "JA": "JA",
    "KO": "KO",
    "VN": "VN",
    "RU": "RU",
    "AR": "AR",
    "FT": "FT",
}

# Cleaned extracts sometimes store language names instead of SFUSD codes.
HOMELANG_NAME_TO_CODE = {
    "English": "EN",
    "Spanish": "SP",
    "Cantonese": "CC",
    "Mandarin (Putonghua)": "CM",
    "Mandarin": "CM",
    "Japanese": "JA",
    "Korean": "KO",
    "Vietnamese": "VN",
    "Russian": "RU",
    "Arabic": "AR",
    "Filipino (Pilipino)": "FT",
    "Filipino": "FT",
    "Tagalog": "FT",
    "Toishanese": "CC",
}

# Bins for the ranked-list length. Long lists are pooled so that the per-area
# histograms keep usable cell counts.
LENGTH_BINS = [
    (0, 0),
    (1, 1),
    (2, 2),
    (3, 3),
    (4, 4),
    (5, 5),
    (6, 6),
    (7, 7),
    (8, 9),
    (10, 12),
    (13, 16),
    (17, 22),
    (23, 32),
    (33, 90),
]
POSITION_GROUPS = [
    ("1", 1, 1),
    ("2", 2, 2),
    ("3", 3, 3),
    ("4-6", 4, 6),
    ("7+", 7, 999),
]

BLOCK_ATTRS = [
    "freelunch_prob",
    "reducedlunch_prob",
    "median_hh_income",
]

# `Current ESAA` in the SFUSD block database names attendance areas; a few names
# differ from schools_rehauled_<year>.csv spellings.
ESAA_NAME_FIXUPS = {
    "King": "Starr King",
    "McKinley": "Mckinley",
    "McCoppin": "Mccoppin",
    "Visitacion Valley": "Vis Valley",
}


class Budget:
    """Account for the Laplace queries answered against the confidential data.

    Query labels are of the form ``"<family> | <stratum>"``. Each family is
    charged a single epsilon, treating its strata as disjoint subsets of
    students that compose in parallel; distinct families compose sequentially.
    The reported ``composed_epsilon`` is therefore ``eps_per_family *
    n_families``. It is nominal: some families pair a citywide query with
    per-stratum queries over the same students, and rates spend two draws, so
    it understates the true composition (see ANONYMIZATION.md).
    """

    def __init__(self, eps_per_family: float):
        self.eps_per_family = eps_per_family
        self.queries: list[str] = []

    def spend(self, name: str) -> None:
        """Record one query.

        Args:
            name: Label of the form ``"<family>"`` or ``"<family> | <stratum>"``.
        """
        self.queries.append(name)

    @property
    def families(self) -> list[str]:
        """Distinct query families, in first-use order."""
        seen: dict[str, None] = {}
        for name in self.queries:
            seen.setdefault(name.split(" | ")[0], None)
        return list(seen)

    @property
    def total_eps(self) -> float:
        """Composed epsilon: sequential across families, parallel within each."""
        return self.eps_per_family * len(self.families)


def noisy_counts(
    counts: dict, rng: np.random.Generator, budget: Budget, name: str
) -> tuple[dict, float]:
    """Add Laplace noise to a histogram and suppress small cells.

    Args:
        counts: Raw cell counts.
        rng: Seeded generator.
        budget: Query accountant.
        name: Label recorded in the privacy budget.

    Returns:
        The noisy counts, with every surviving cell at or above ``MIN_CELL``,
        and the noisy total over all cells including suppressed ones. The total
        is what lets :func:`to_dist` hand exactly the suppressed mass to the
        parent prior.
    """
    budget.spend(name)
    scale = 1.0 / LAPLACE_EPS
    out = {}
    total = 0.0
    for key, value in counts.items():
        noisy = float(value) + rng.laplace(0.0, scale)
        total += max(noisy, 0.0)
        if noisy >= MIN_CELL:
            # Keys are stringified here so that a cell and its prior counterpart
            # share one entry when the two are merged in `to_dist`.
            out[str(key)] = noisy
    return out, total


def to_dist(
    counts: dict, total: float | None = None, prior: dict | None = None
) -> dict:
    """Normalise counts into a distribution, smoothed toward ``prior``.

    The prior is given exactly the weight that suppression removed -- ``total``
    minus the surviving counts -- plus a small ``PRIOR_FLOOR`` so that no
    plausible category is left at probability zero. Weighting it this way keeps
    both ends honest: a thin cell whose whole histogram was suppressed falls
    back entirely to the parent, while a relationship the data pins down (a home
    language of English implying English proficiency, say) is left alone instead
    of being blurred in proportion to its sample size.

    Args:
        counts: (Noisy, suppressed) cell counts.
        total: Noisy total across all cells before suppression. Defaults to the
            surviving sum, i.e. no suppressed mass to redistribute.
        prior: Parent distribution to fall back on; used alone when ``counts``
            is empty.

    Returns:
        Probabilities summing to 1, or ``{}`` when nothing is available.
    """
    kept = float(sum(counts.values()))
    if prior:
        weight = max(float(total if total is not None else kept) - kept, 0.0)
        weight += PRIOR_FLOOR
        merged = dict(counts)
        for key, prob in prior.items():
            merged[str(key)] = merged.get(str(key), 0.0) + weight * prob
        counts = merged
    denominator = float(sum(counts.values()))
    if denominator <= 0:
        return dict(prior) if prior else {}
    return {str(k): v / denominator for k, v in counts.items() if v > 0}


def hist(
    series: pd.Series,
    rng: np.random.Generator,
    budget: Budget,
    name: str,
    prior: dict | None = None,
) -> dict:
    """Noisy, suppressed, smoothed histogram of a categorical series."""
    counts, total = noisy_counts(
        Counter(series.dropna().tolist()), rng, budget, name
    )
    return to_dist(counts, total, prior)


def noisy_rate(
    numerator: float,
    denominator: float,
    rng: np.random.Generator,
    budget: Budget,
    name: str,
    fallback: float,
) -> float:
    """Laplace-noised rate, falling back when the cell is too small to report.

    Both tails are suppressed: the cell needs ``MIN_RATE_DEN`` students, and
    both the numerator and its complement need ``MIN_CELL``. That second
    condition matters for accuracy as well as disclosure -- a rate whose
    numerator is a handful of students comes out biased upward, because the
    noised numerator is clipped at zero but not above -- so such a rate falls
    back to its parent instead of being reported.

    Args:
        numerator: Count of students with the property.
        denominator: Count of students in the conditioning cell.
        rng: Seeded generator.
        budget: Query accountant.
        name: Label recorded in the privacy budget.
        fallback: Value to use when the cell is too small to report.

    Returns:
        A rate in [0, 1].
    """
    budget.spend(name)
    if (
        denominator < MIN_RATE_DEN
        or numerator < MIN_CELL
        or denominator - numerator < MIN_CELL
    ):
        return fallback
    num = numerator + rng.laplace(0.0, 1.0 / LAPLACE_EPS)
    den = denominator + rng.laplace(0.0, 1.0 / LAPLACE_EPS)
    if den < MIN_RATE_DEN:
        return fallback
    return float(min(max(num / den, 0.0), 1.0))


def rates_by_area(
    frame: pd.DataFrame,
    flags: pd.Series,
    rng: np.random.Generator,
    budget: Budget,
    name: str,
    citywide: float,
) -> tuple[dict, float]:
    """Per-attendance-area rates, with a residual rate for suppressed areas.

    Reporting only the areas that clear the suppression floors and handing
    everyone else the *overall* citywide rate biases the total: for a rare
    priority, the areas that clear the floor are exactly the high ones, so the
    suppressed areas are below average by construction. The fallback here is
    therefore the pooled rate over the areas that were suppressed, which keeps
    the citywide total intact.

    Args:
        frame: Rows with ``idschoolattendance``.
        flags: Boolean series aligned to ``frame``.
        rng: Seeded generator.
        budget: Query accountant.
        name: Query-family label.
        citywide: Rate to use if even the residual pool is too small.

    Returns:
        The per-area rates and the residual fallback rate.
    """
    usable = frame.dropna(subset=["idschoolattendance"])
    rates, residual = {}, []
    for aa, group in usable.groupby("idschoolattendance"):
        hits = float(flags.loc[group.index].sum())
        rate = noisy_rate(
            hits, float(len(group)), rng, budget, f"{name} | AA {int(aa)}", -1.0
        )
        if rate < 0:
            residual.append((hits, len(group)))
        else:
            rates[str(int(aa))] = round(rate, 4)
    fallback = noisy_rate(
        float(sum(h for h, _ in residual)),
        float(sum(n for _, n in residual)),
        rng,
        budget,
        f"{name} | suppressed areas pooled",
        citywide,
    )
    return rates, round(fallback, 4)


def standardized_ctip_tilts(
    frame: pd.DataFrame,
    value_column: str,
    base_by_aa: dict,
    citywide: dict,
    rng: np.random.Generator,
    budget: Budget,
    name: str,
) -> dict:
    """Estimate the CTIP1 effect *within* attendance areas.

    The generator samples a value from the applicant's attendance-area
    distribution and then tilts it by CTIP1 status. A raw citywide
    ``P(value | CTIP1) / P(value)`` ratio is the wrong tilt for that: the
    area-level distribution already carries the between-area part of the
    association (CTIP1 blocks are concentrated in particular areas), so
    applying the citywide ratio on top counts it twice.

    This computes an indirectly standardized ratio instead -- observed counts
    over counts expected from each area's own distribution -- which isolates
    the within-area effect. Suppressed cells get a tilt of 1.0 rather than 0,
    so suppression never drives a category's probability to zero.

    Args:
        frame: Rows with ``idschoolattendance``, ``ctip1`` and ``value_column``.
        value_column: Column holding the categorical value.
        base_by_aa: The area-level distributions the generator will tilt.
        citywide: Citywide distribution, used for areas with no entry.
        rng: Seeded generator.
        budget: Query accountant.
        name: Query-family label.

    Returns:
        ``{"0": factors, "1": factors}`` keyed like ``citywide``.
    """
    observed = {0: Counter(), 1: Counter()}
    expected = {0: Counter(), 1: Counter()}
    usable = frame.dropna(subset=["idschoolattendance", value_column])
    for aa, group in usable.groupby("idschoolattendance"):
        base = base_by_aa.get(str(int(aa))) or citywide
        for state in (0, 1):
            subset = group[group["ctip1"].fillna(0) == state]
            for value in subset[value_column]:
                observed[state][str(value)] += 1
            for key, prob in base.items():
                expected[state][str(key)] += len(subset) * prob
    tilts = {}
    for state in (0, 1):
        counts, _ = noisy_counts(
            observed[state], rng, budget, f"{name} | ctip{state}"
        )
        factors = {}
        for key in citywide:
            if key not in counts or expected[state].get(key, 0.0) <= 0:
                factors[key] = 1.0
            else:
                factors[key] = round(
                    min(counts[key] / expected[state][key], TILT_CAP), 5
                )
        tilts[str(state)] = factors
    return tilts


def length_bin(length: int) -> int:
    """Index of the ``LENGTH_BINS`` entry containing ``length``."""
    for i, (lo, hi) in enumerate(LENGTH_BINS):
        if lo <= length <= hi:
            return i
    return len(LENGTH_BINS) - 1


def coarse_eth(label) -> str:
    """Map a raw ``resolved_ethnicity`` label to its coarse group."""
    if not isinstance(label, str):
        return PI_OTHER
    return COARSE_ETHNICITY.get(label, PI_OTHER)


def canonicalize_ethnicity(label):
    """Map known aliases to the evaluator's canonical ethnicity strings.

    Returns ``None`` for missing or garbage labels so they count as unobserved
    rather than falling into the residual ``PI/Other`` bucket.
    """
    if not isinstance(label, str):
        return None
    cleaned = label.strip()
    if cleaned.lower() in INVALID_ETHNICITY_LABELS:
        return None
    return ETHNICITY_LABEL_FIXES.get(cleaned, cleaned)


def frl_score(row) -> float:
    """Block free-or-reduced lunch probability used for race|FRL bins."""
    free = row["freelunch_prob"] if "freelunch_prob" in row.index else np.nan
    reduced = (
        row["reducedlunch_prob"] if "reducedlunch_prob" in row.index else np.nan
    )
    if pd.isna(free) and pd.isna(reduced):
        return np.nan
    return float(np.clip(np.nan_to_num(free) + np.nan_to_num(reduced), 0.0, 1.0))


def frl_bin_edges(scores: pd.Series) -> list[float]:
    """Empirical tercile cutpoints of the FRL score, coarsened for release.

    Exact quantiles fingerprint the confidential FRL distribution. Edges are
    snapped to ``FRL_EDGE_ROUND`` before being written into the priors.
    """
    usable = scores.dropna()
    if usable.empty:
        return [1.0 / 3.0, 2.0 / 3.0]
    q33, q66 = np.quantile(usable.to_numpy(dtype=float), [1.0 / 3.0, 2.0 / 3.0])
    return [
        _round_to_grid(float(q33), FRL_EDGE_ROUND),
        _round_to_grid(float(q66), FRL_EDGE_ROUND),
    ]


def assign_frl_bin(score, edges: list[float]) -> str:
    """Map an FRL score to ``low`` / ``mid`` / ``high`` using ``edges``."""
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return "mid"
    lo, hi = edges
    if score <= lo:
        return "low"
    if score <= hi:
        return "mid"
    return "high"


def hl_group(label) -> str:
    """Map a raw ``homelang`` code to its pathway-relevant group."""
    if not isinstance(label, str):
        return "OTH"
    return HOMELANG_GROUPS.get(label, "OTH")


# ---------------------------------------------------------------------------
# Minimal shapefile / dBASE readers. The census block layer is a public DataSF
# export in WGS84; reading its .dbf avoids adding a geospatial dependency.
# ---------------------------------------------------------------------------
def read_dbf(path: Path, keep: set[str]) -> pd.DataFrame:
    """Read the requested columns out of a dBASE (.dbf) table.

    Args:
        path: Path to the .dbf file.
        keep: Field names to return.

    Returns:
        DataFrame with one column per kept field, all as stripped strings.
    """
    with open(path, "rb") as handle:
        header = handle.read(32)
        n_records = struct.unpack("<I", header[4:8])[0]
        header_len = struct.unpack("<H", header[8:10])[0]
        record_len = struct.unpack("<H", header[10:12])[0]
        fields = []
        while True:
            descriptor = handle.read(32)
            if len(descriptor) < 32 or descriptor[0:1] == b"\r":
                break
            fields.append(
                (
                    descriptor[0:11].rstrip(b"\x00").decode("latin1"),
                    descriptor[16],
                )
            )
        handle.seek(header_len)
        data = {name: [] for name, _ in fields if name in keep}
        for _ in range(n_records):
            record = handle.read(record_len)
            if len(record) < record_len:
                break
            offset = 1
            for name, width in fields:
                if name in keep:
                    data[name].append(
                        record[offset : offset + width]
                        .decode("latin1")
                        .strip("\x00 ")
                    )
                offset += width
    return pd.DataFrame(data)


def normalize_homelang(label):
    """Map a home-language code or English name to an SFUSD language code."""
    if not isinstance(label, str):
        return None
    cleaned = label.strip()
    if not cleaned:
        return None
    if cleaned in HOMELANG_GROUPS or len(cleaned) <= 3:
        return cleaned
    return HOMELANG_NAME_TO_CODE.get(cleaned, cleaned)


def _load_students(
    sfusd_root: Path,
    year: str,
    student_csv: Path | None = None,
    *,
    canonicalize_eth: bool = False,
) -> pd.DataFrame:
    """Load the confidential cleaned student file, restricted to the grade.

    Args:
        sfusd_root: Root of the SFUSD data tree.
        year: Two-school-year tag, e.g. ``"2324"``.
        student_csv: Explicit student CSV path; when omitted, tries the stock
            ``Data/Cleaned/student_<year>.csv`` layout and the alternate
            ``data/cleaned/student_without_specialprogs_<year>.csv`` layout.
        canonicalize_eth: When True, rewrite ethnicity aliases (e.g.
            ``Multi-Racial`` → ``Two or More Races``) and drop garbage labels.
    """
    if student_csv is not None:
        path = Path(student_csv)
    else:
        candidates = [
            sfusd_root / "Data" / "Cleaned" / f"student_{year}.csv",
            sfusd_root / "data" / "cleaned" / f"student_{year}.csv",
            sfusd_root
            / "data"
            / "cleaned"
            / f"student_without_specialprogs_{year}.csv",
        ]
        path = next((p for p in candidates if p.is_file()), candidates[0])
    if not path.is_file():
        raise FileNotFoundError(
            f"Student CSV not found at {path}; pass --student-csv."
        )
    df = pd.read_csv(path, low_memory=False)
    df = df.loc[df["grade"] == GRADE].reset_index(drop=True)
    if "englprof" not in df.columns and "englprof_desc" in df.columns:
        df["englprof"] = df["englprof_desc"]
    if "sped" not in df.columns:
        if "speced" in df.columns:
            df["sped"] = df["speced"]
        else:
            df["sped"] = np.nan
    if "homelang" in df.columns:
        df["homelang"] = df["homelang"].apply(normalize_homelang)
    if canonicalize_eth and "resolved_ethnicity" in df.columns:
        df["resolved_ethnicity"] = df["resolved_ethnicity"].apply(
            canonicalize_ethnicity
        )
    for col in (
        "r1_ranked_idschool",
        "r1_programs",
        "sibling",
        "currentlp",
        "aaprek",
        "prek",
        "aa",
        "currentlpsibling",
    ):
        if col not in df.columns:
            df[col] = "[]"
        df[col] = df[col].fillna("[]").apply(ast.literal_eval)
    df["L"] = df["r1_ranked_idschool"].apply(len)
    return df


def _resolve_table(
    sfusd_root: Path,
    year: str,
    kind: str,
    override: Path | None,
) -> Path:
    """Locate a schools or programs CSV under either SFUSD layout."""
    if override is not None:
        return Path(override)
    name = (
        f"schools_rehauled_{year}.csv"
        if kind == "schools"
        else f"programs_without_specialprogs_{year}.csv"
    )
    candidates = [
        sfusd_root / "Data" / "Cleaned" / name,
        sfusd_root / "data" / "cleaned" / name,
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"{kind} CSV not found; pass --{kind}-csv. Tried: {candidates}"
    )


def _haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles between arrays of coordinates."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 3958.8 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _find_census_block_dbf(sfusd_root: Path, override: Path | None) -> Path:
    """Locate the .dbf of the public 2010 census block layer.

    Args:
        sfusd_root: Root of the SFUSD data tree; the census export usually sits
            alongside or one level above ``Data/``.
        override: Explicit directory from ``--census-blocks-dir``.

    Returns:
        Path to the .dbf file.

    Raises:
        FileNotFoundError: If no candidate directory holds a .dbf.
    """
    name = "Census 2010_ Blocks for San Francisco"
    candidates = [override] if override else []
    candidates += [
        sfusd_root / name,
        sfusd_root.parent / name,
        sfusd_root / ".." / name,
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        matches = (
            sorted(Path(candidate).glob("*.dbf"))
            if Path(candidate).is_dir()
            else []
        )
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"No census block .dbf found; pass --census-blocks-dir. Tried: {candidates}"
    )


def _build_block_reference(
    sfusd_root: Path,
    students: pd.DataFrame,
    schools: pd.DataFrame,
    census_blocks_dir: Path | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assemble public census-block geography and a tract-level CTIP1 table.

    Every block-reference column is a published geographic or census fact:
    block / block group / tract identifiers and TIGER internal points from the
    DataSF 2010 block layer, 2010 Census population, and the SFUSD elementary
    attendance-area boundary. CTIP is **not** stored per block: it is collapsed
    to one binary ``ctip1`` flag per census tract (constant within tract in the
    SFUSD block workbook) and returned as a separate frame.

    Args:
        sfusd_root: Root of the SFUSD data tree.
        students: Student frame, used only for the block -> ZIP crosswalk.
        schools: Schools table, used to turn ESAA names into school ids.
        census_blocks_dir: Optional explicit path to the census block export.

    Returns:
        ``(block_reference, ctip_by_tract)`` where ``ctip_by_tract`` has columns
        ``Tract`` and ``ctip1``.
    """
    block_db = pd.read_excel(
        sfusd_root
        / "Data"
        / "SF 2010 blks 022119 with field descriptions (1).xlsx",
        sheet_name="block database",
        usecols=[
            "Block",
            "Block Type",
            "BlockGroup",
            "Tract",
            "Current ESAA",
            "CTIP_2013 assignment",
            "2010 pop less than 18 years old",
            "2010 total population count",
        ],
    ).drop_duplicates(subset="Block")

    name_to_id = {}
    for _, row in schools.iterrows():
        short = re.sub(r"\s*\(.*\)$", "", str(row["school_name"]))
        short = short.replace(" ES", "").strip()
        name_to_id[short] = int(row["school_id"])
    esaa_ids = []
    for name in block_db["Current ESAA"]:
        key = ESAA_NAME_FIXUPS.get(str(name), str(name))
        esaa_ids.append(name_to_id.get(key, -1))
    block_db["aa_school_id"] = esaa_ids
    missing = sorted(
        {n for n, i in zip(block_db["Current ESAA"], esaa_ids) if i == -1}
    )
    if missing:
        raise ValueError(f"Unmapped ESAA names: {missing}")

    geo = read_dbf(
        _find_census_block_dbf(sfusd_root, census_blocks_dir),
        {"geoid10", "intptlat10", "intptlon10", "aland10"},
    )
    geo["Block"] = pd.to_numeric(geo["geoid10"], errors="coerce")
    geo["intptlat"] = pd.to_numeric(geo["intptlat10"], errors="coerce")
    geo["intptlon"] = pd.to_numeric(geo["intptlon10"], errors="coerce")
    geo["aland_m2"] = pd.to_numeric(geo["aland10"], errors="coerce")
    geo = geo.dropna(subset=["Block"]).drop_duplicates(subset="Block")

    ref = block_db.merge(
        geo[["Block", "intptlat", "intptlon", "aland_m2"]],
        on="Block",
        how="left",
    )

    # ZIP is absent from the block database; recover the block -> ZIP crosswalk
    # from the observed data and extend it to every block by nearest internal
    # point. ZIP boundaries are public, but which blocks were observed is
    # applicant-derived; ANONYMIZATION.md discloses this.
    obs_zip = (
        students.dropna(subset=["census_block", "zipcode"])
        .groupby("census_block")["zipcode"]
        .agg(lambda s: int(s.mode().iloc[0]))
    )
    obs_zip.index = obs_zip.index.astype("int64")
    ref["zipcode"] = ref["Block"].map(obs_zip)
    known = ref.dropna(subset=["zipcode", "intptlat"])
    unknown = ref["zipcode"].isna() & ref["intptlat"].notna()
    if unknown.any() and len(known):
        k_lat = known["intptlat"].to_numpy()
        k_lon = known["intptlon"].to_numpy()
        k_zip = known["zipcode"].to_numpy()
        u_lat = ref.loc[unknown, "intptlat"].to_numpy()
        u_lon = ref.loc[unknown, "intptlon"].to_numpy()
        d = _haversine_miles(
            u_lat[:, None], u_lon[:, None], k_lat[None, :], k_lon[None, :]
        )
        ref.loc[unknown, "zipcode"] = k_zip[d.argmin(axis=1)]

    ctip_level = (
        ref["CTIP_2013 assignment"]
        .astype(str)
        .str.extract(r"(\d)")[0]
        .astype(float)
    )
    # CTIP is a tract attribute in the workbook (constant within tract).
    tract_ctip = (
        pd.DataFrame({"Tract": ref["Tract"], "ctip_level": ctip_level})
        .dropna(subset=["ctip_level"])
        .groupby("Tract", as_index=False)["ctip_level"]
        .agg(lambda s: float(s.mode().iloc[0]))
    )
    tract_ctip["ctip1"] = (tract_ctip["ctip_level"] == 1).astype(int)
    tract_ctip = tract_ctip[["Tract", "ctip1"]]

    mixed = (
        pd.DataFrame({"Tract": ref["Tract"], "ctip_level": ctip_level})
        .dropna()
        .groupby("Tract")["ctip_level"]
        .nunique()
    )
    if (mixed > 1).any():
        raise ValueError(
            "CTIP_2013 assignment varies within tract; refuse to collapse"
        )

    ref = ref.rename(
        columns={
            "2010 pop less than 18 years old": "pop_under18",
            "2010 total population count": "pop_total",
            "Block Type": "block_type",
        }
    )
    ref = ref[
        [
            "Block",
            "BlockGroup",
            "Tract",
            "zipcode",
            "aa_school_id",
            "block_type",
            "pop_total",
            "pop_under18",
            "intptlat",
            "intptlon",
            "aland_m2",
        ]
    ]
    return (
        ref.dropna(subset=["intptlat", "intptlon"]).reset_index(drop=True),
        tract_ctip.reset_index(drop=True),
    )


def _ctip_by_tract_from_block_frame(reference: pd.DataFrame) -> pd.DataFrame:
    """Collapse a legacy block reference that still carries ``ctip_2013``."""
    if "ctip_2013" not in reference.columns:
        raise ValueError(
            "block reference has no ctip_2013; provide ctip_by_tract_<year>.csv"
        )
    mixed = reference.groupby("Tract")["ctip_2013"].nunique()
    if (mixed > 1).any():
        raise ValueError(
            "ctip_2013 varies within tract; refuse to collapse to tract table"
        )
    tract_ctip = (
        reference.groupby("Tract", as_index=False)["ctip_2013"]
        .agg(lambda s: float(s.mode().iloc[0]))
        .rename(columns={"ctip_2013": "ctip_level"})
    )
    tract_ctip["ctip1"] = (tract_ctip["ctip_level"] == 1).astype(int)
    return tract_ctip[["Tract", "ctip1"]]


def _blockgroup_attributes(students: pd.DataFrame) -> dict:
    """Coarsen block-level socio-economic attributes to block groups for priors.

    Lunch probabilities arrive per census block in the confidential source; a
    single SF block can hold one household, so publishing them per block would
    re-expose small cells. Each attribute in ``BLOCK_ATTRS`` is replaced by the
    mean over its census block group (tract / citywide fallback). These are the
    socio-economic fields later written to the public student CSV.

    Args:
        students: Confidential student frame.

    Returns:
        Mapping from census block group id to its attribute dict.
    """
    have = students.dropna(subset=["census_block", "census_blockgroup"]).copy()
    blocks = have.groupby("census_block").first()

    city = {a: float(blocks[a].mean()) for a in BLOCK_ATTRS}
    tract_mean = blocks.groupby("census_tract")[BLOCK_ATTRS].mean()
    bg_mean = blocks.groupby("census_blockgroup")[BLOCK_ATTRS].mean()
    bg_blocks = blocks.groupby("census_blockgroup").size()
    bg_students = have.groupby("census_blockgroup").size()
    bg_tract = blocks.groupby("census_blockgroup")["census_tract"].first()

    out = {}
    for bg in bg_mean.index:
        tract = bg_tract.loc[bg]
        ok = (
            bg_blocks.get(bg, 0) >= MIN_BG_BLOCKS
            and bg_students.get(bg, 0) >= MIN_BG_STUDENTS
        )
        attrs = {}
        for attr in BLOCK_ATTRS:
            value = bg_mean.loc[bg, attr] if ok else np.nan
            if pd.isna(value) and tract in tract_mean.index:
                value = tract_mean.loc[tract, attr]
            if pd.isna(value):
                value = city[attr]
            attrs[attr] = value
        out[str(int(bg))] = {
            ("median_hh_income" if a == "median_hh_income" else a): (
                None
                if attrs[a] is None
                else (
                    int(round(attrs[a]))
                    if a == "median_hh_income"
                    else round(float(attrs[a]), ATTR_ROUND)
                )
            )
            for a in BLOCK_ATTRS
        }
    return out


def _blockgroup_residuals(students: pd.DataFrame) -> dict:
    """Describe the block-to-block spread that block-group coarsening removes.

    Coarsening the socio-economic attributes to block groups (see
    :func:`_blockgroup_attributes`) shrinks their variance by roughly a third.
    Releasing the quantiles of the within-block-group residual -- a single
    citywide shape per attribute, pooled over ~2,300 blocks -- lets the
    generator put that spread back as synthetic block-level noise, so the
    marginal distribution matches without any real block's value being tied to
    a real block.

    Args:
        students: Confidential student frame.

    Returns:
        Per attribute: residual quantiles, clipping range, and the rate at
        which the attribute is missing at block level.
    """
    blocks = (
        students.dropna(subset=["census_block", "census_blockgroup"])
        .groupby("census_block")
        .first()
    )
    out = {}
    levels = np.linspace(0.0, 1.0, 41)
    for attr in BLOCK_ATTRS:
        values = blocks[[attr, "census_blockgroup"]].dropna()
        if values.empty:
            continue
        residual = values[attr] - values.groupby("census_blockgroup")[
            attr
        ].transform("mean")
        out[attr] = {
            "quantiles": [
                round(float(q), 4) for q in np.quantile(residual, levels)
            ],
            "min": round(float(values[attr].min()), 4),
            "max": round(float(values[attr].max()), 4),
            "p_missing": round(float(blocks[attr].isna().mean()), 4),
        }
    return out


def _choice_priors(
    students: pd.DataFrame,
    schools: pd.DataFrame,
    programs: pd.DataFrame,
    rng: np.random.Generator,
    budget: Budget,
    *,
    profile: str = PROFILE_BASELINE,
) -> dict:
    """Aggregate everything needed to regenerate ranked lists.

    Args:
        students: Confidential student frame.
        schools: Schools table (for coordinates).
        programs: Programs table (for the offered program types).
        rng: Seeded generator.
        budget: Query accountant.

    Returns:
        Dict of choice-related priors.
    """
    school_ll = schools.set_index("school_id")[["lat", "lon"]]
    listed = students[students["L"] > 0]

    # Rank-1 school, per attendance area, smoothed toward the citywide rank-1
    # popularity so that thin areas degrade to the city pattern.
    city_rank1 = hist(
        listed["r1_ranked_idschool"].apply(lambda x: int(x[0])),
        rng,
        budget,
        "rank-1 school | citywide",
    )
    # Released as (noisy, suppressed) counts rather than a distribution so that
    # the generator can smooth them toward a *distance-localised* citywide
    # prior: an area whose own cells were suppressed then falls back to schools
    # near the synthetic household rather than to the city as a whole. Keeping
    # the smoothing in the public script also makes the policy auditable.
    rank1_counts_by_aa = {}
    rank1_total_by_aa = {}
    for aa, grp in listed.dropna(subset=["idschoolattendance"]).groupby(
        "idschoolattendance"
    ):
        cells, total = noisy_counts(
            Counter(grp["r1_ranked_idschool"].apply(lambda x: int(x[0]))),
            rng,
            budget,
            f"rank-1 school | AA {int(aa)}",
        )
        rank1_counts_by_aa[str(int(aa))] = {
            k: round(v, 2) for k, v in cells.items()
        }
        rank1_total_by_aa[str(int(aa))] = round(total, 2)

    # Tail popularity (positions 2+) is taken citywide only: per-area tails are
    # made up of one- and two-student cells.
    tail = Counter()
    for row in listed.itertuples():
        for school in row.r1_ranked_idschool[1:]:
            tail[int(school)] += 1
    school_pop_tail = to_dist(
        *noisy_counts(tail, rng, budget, "tail school popularity")
    )

    # Mean home->school distance by list position, used by the generator to
    # calibrate a distance-decay parameter rather than copying any real list.
    dist_by_pos = defaultdict(list)
    for row in listed.dropna(subset=["latitude", "longitude"]).itertuples():
        for pos, school in enumerate(row.r1_ranked_idschool, start=1):
            if int(school) not in school_ll.index:
                continue
            lat2, lon2 = school_ll.loc[int(school)]
            d = _haversine_miles(row.latitude, row.longitude, lat2, lon2)
            for name, lo, hi in POSITION_GROUPS:
                if lo <= pos <= hi:
                    dist_by_pos[name].append(float(d))
    budget.spend("mean choice distance by list position")
    target_dist = {
        name: round(
            float(
                np.mean(vals)
                + rng.laplace(0.0, 1.0 / LAPLACE_EPS / max(len(vals), 1))
            ),
            4,
        )
        for name, vals in dist_by_pos.items()
        if len(vals) >= MIN_CELL
    }

    # List length: per-area bin histogram plus a citywide CTIP1 tilt.
    city_len = hist(
        students["L"].apply(length_bin),
        rng,
        budget,
        "list-length bins | citywide",
    )
    len_by_aa = {}
    for aa, grp in students.dropna(subset=["idschoolattendance"]).groupby(
        "idschoolattendance"
    ):
        len_by_aa[str(int(aa))] = hist(
            grp["L"].apply(length_bin),
            rng,
            budget,
            f"list-length bins | AA {int(aa)}",
            prior=city_len,
        )
    length_tilt = standardized_ctip_tilts(
        students.assign(length_bin=students["L"].apply(length_bin)),
        "length_bin",
        len_by_aa,
        city_len,
        rng,
        budget,
        "list-length bins CTIP1 tilt",
    )

    # Program type given the school and the home-language group. Computed
    # citywide over ~24k ranked choices, then restricted at generation time to
    # the program types each school actually offers.
    offered = defaultdict(set)
    for row in programs.itertuples():
        offered[int(row.school_id)].add(str(row.program_type))
    pair_counts = Counter()
    prog_by_hlg = defaultdict(Counter)
    for row in students.itertuples():
        group = hl_group(row.homelang)
        for school, ptype in zip(row.r1_ranked_idschool, row.r1_programs):
            prog_by_hlg[group][str(ptype)] += 1
            pair_counts[(int(school), str(ptype))] += 1
    # Small language groups lose most of their cells to suppression, so each
    # group's surviving cells are smoothed toward the pooled citywide table
    # rather than left as a point mass on the one type that survived.
    prog_city = to_dist(
        *noisy_counts(
            sum(prog_by_hlg.values(), Counter()),
            rng,
            budget,
            "program type | citywide",
        )
    )
    program_by_hlgroup = {
        g: to_dist(
            *noisy_counts(c, rng, budget, f"program type | {g}"),
            prior=prog_city,
        )
        for g, c in prog_by_hlg.items()
    }
    program_rank1_by_hlgroup = None
    if profile == PROFILE_JOINT_FRL_ETH:
        # Rank-1 type shares are lower-GE than the all-rank pool; releasing them
        # lets the generator calibrate first-choice pathway mix without touching
        # the all-rank table the baseline path still uses.
        rank1_by_hlg = defaultdict(Counter)
        for row in listed.itertuples():
            if not row.r1_programs:
                continue
            rank1_by_hlg[hl_group(row.homelang)][str(row.r1_programs[0])] += 1
        rank1_city = to_dist(
            *noisy_counts(
                sum(rank1_by_hlg.values(), Counter()),
                rng,
                budget,
                "rank-1 program type | citywide",
            )
        )
        program_rank1_by_hlgroup = {
            g: to_dist(
                *noisy_counts(c, rng, budget, f"rank-1 program type | {g}"),
                prior=rank1_city,
            )
            for g, c in rank1_by_hlg.items()
        }
    # Program types a school offers: the published programs table, plus types
    # ranked there by at least MIN_CELL students (special programs are absent
    # from the programs table but are ranked, and the simulator's
    # remove-special-lps filter needs them to behave the same way).
    budget.spend("school x program-type existence")
    school_program_types = {}
    for school in sorted(set(list(offered) + [s for s, _ in pair_counts])):
        types = set(offered.get(school, set()))
        for (s, ptype), count in pair_counts.items():
            if (
                s == school
                and count + rng.laplace(0.0, 1.0 / LAPLACE_EPS) >= MIN_CELL
            ):
                types.add(ptype)
        if types:
            school_program_types[str(school)] = sorted(types)

    # Applicants often rank two programs at the same school (typically an
    # immersion pathway and general education). Released as one citywide rate so
    # the generator can reproduce the pattern.
    repeats = total = 0
    for row in listed.itertuples():
        seen = set()
        for school in row.r1_ranked_idschool:
            total += 1
            if school in seen:
                repeats += 1
            seen.add(school)
    p_repeat = noisy_rate(
        float(repeats),
        float(total),
        rng,
        budget,
        "same-school repeat choices",
        0.07,
    )

    # Realised rank of the round-1 assignment, by list-length bin.
    assigned_rank = {}
    for bin_idx, grp in listed.groupby(listed["L"].apply(length_bin)):
        assigned_rank[str(bin_idx)] = hist(
            grp["r1_rank"].dropna().astype(int),
            rng,
            budget,
            f"assigned rank | length bin {bin_idx}",
        )
    p_unassigned = noisy_rate(
        float(listed["r1_rank"].isna().sum()),
        float(len(listed)),
        rng,
        budget,
        "round-1 unassigned rate",
        0.001,
    )
    p_final_eq_r1 = noisy_rate(
        float((students["final_school"] == students["r1_idschool"]).sum()),
        float(len(students)),
        rng,
        budget,
        "final school equals round-1 assignment",
        0.82,
    )
    final_pop = hist(
        students.loc[students["final_school"] > 0, "final_school"].astype(int),
        rng,
        budget,
        "final-school popularity",
    )
    out = {
        "rank1_counts_by_aa": rank1_counts_by_aa,
        "rank1_total_by_aa": rank1_total_by_aa,
        "rank1_school_citywide": city_rank1,
        "school_pop_tail": school_pop_tail,
        "target_mean_dist_by_position": target_dist,
        "length_bins": [list(b) for b in LENGTH_BINS],
        "length_by_aa": len_by_aa,
        "length_citywide": city_len,
        "length_tilt_by_ctip1": length_tilt,
        "program_by_hlgroup": program_by_hlgroup,
        "school_program_types": school_program_types,
        "assigned_rank_by_length_bin": assigned_rank,
        "p_same_school_repeat": round(p_repeat, 4),
        "p_round1_unassigned": round(p_unassigned, 4),
        "p_final_equals_round1": round(p_final_eq_r1, 4),
        "final_school_citywide": final_pop,
    }
    if program_rank1_by_hlgroup is not None:
        out["program_rank1_by_hlgroup"] = program_rank1_by_hlgroup
    return out


def _demographic_priors(
    students: pd.DataFrame,
    rng: np.random.Generator,
    budget: Budget,
    *,
    profile: str = PROFILE_BASELINE,
    race_frl_aa_blend: float = 0.5,
) -> dict:
    """Aggregate the student-attribute priors.

    Race and home language are sampled from area-level distributions over coarse
    groups, then refined citywide -- the joint (area, fine ethnicity, language)
    table is mostly one- and two-student cells and is never used directly.

    Under ``joint_frl_eth``, also release citywide ``P(coarse eth | FRL tercile)``
    so the generator can condition race on the already-drawn block FRL score
    without fabricating a second FRL draw.
    """
    df = students.copy()
    df["coarse_eth"] = df["resolved_ethnicity"].apply(
        lambda x: coarse_eth(x) if isinstance(x, str) else np.nan
    )
    observed = df["resolved_ethnicity"].notna()

    p_observed_city = noisy_rate(
        float(observed.sum()),
        float(len(df)),
        rng,
        budget,
        "demographics observed rate",
        0.82,
    )
    observed_by_aa, p_observed_default = rates_by_area(
        df,
        observed,
        rng,
        budget,
        "demographics observed rate",
        p_observed_city,
    )

    obs = df[observed]
    city_eth = hist(
        obs["coarse_eth"], rng, budget, "coarse ethnicity | citywide"
    )
    eth_by_aa = {}
    for aa, grp in obs.dropna(subset=["idschoolattendance"]).groupby(
        "idschoolattendance"
    ):
        eth_by_aa[str(int(aa))] = hist(
            grp["coarse_eth"],
            rng,
            budget,
            f"coarse ethnicity | AA {int(aa)}",
            prior=city_eth,
        )
    eth_tilt = standardized_ctip_tilts(
        obs,
        "coarse_eth",
        eth_by_aa,
        city_eth,
        rng,
        budget,
        "coarse ethnicity CTIP1 tilt",
    )
    fine_city = hist(
        obs["resolved_ethnicity"], rng, budget, "reported ethnicity | citywide"
    )
    fine_by_coarse = {}
    for group, grp in obs.groupby("coarse_eth"):
        allowed = {
            label
            for label, coarse in COARSE_ETHNICITY.items()
            if coarse == str(group)
        }
        prior = {k: v for k, v in fine_city.items() if k in allowed}
        fine_by_coarse[str(group)] = hist(
            grp["resolved_ethnicity"],
            rng,
            budget,
            f"reported ethnicity | {group}",
            prior=prior or None,
        )
    city_hl = hist(obs["homelang"], rng, budget, "home language | citywide")
    hl_by_eth = {}
    for group, grp in obs.groupby("coarse_eth"):
        hl_by_eth[str(group)] = hist(
            grp["homelang"],
            rng,
            budget,
            f"home language by ethnicity | {group}",
            prior=city_hl,
        )
    hl_by_eth_ctip = {}
    for (group, ctip), grp in obs.dropna(subset=["ctip1"]).groupby(
        ["coarse_eth", "ctip1"]
    ):
        hl_by_eth_ctip[f"{group}|{int(ctip)}"] = hist(
            grp["homelang"],
            rng,
            budget,
            f"home language by ethnicity and CTIP | {group},{int(ctip)}",
            prior=hl_by_eth.get(str(group), city_hl),
        )
    englprof_city = hist(
        obs["englprof"].dropna(),
        rng,
        budget,
        "English proficiency by language | citywide",
    )
    if not englprof_city:
        # Some cleaned extracts drop proficiency codes entirely; keep a stable
        # English-proficient default so generation still has a table.
        englprof_city = {"E": 1.0}
    englprof = {}
    for lang, grp in obs.dropna(subset=["homelang"]).groupby("homelang"):
        values = grp["englprof"].dropna()
        if values.empty:
            englprof[str(lang)] = dict(englprof_city)
            continue
        englprof[str(lang)] = hist(
            values,
            rng,
            budget,
            f"English proficiency | {lang}",
            prior=englprof_city,
        )
    englprof["__default__"] = englprof_city
    sped = {}
    for c, grp in obs.dropna(subset=["ctip1"]).groupby("ctip1"):
        sped_vals = pd.to_numeric(grp["sped"], errors="coerce")
        if sped_vals.notna().sum() < MIN_RATE_DEN:
            sped[str(int(c))] = 0.11
            continue
        sped[str(int(c))] = round(
            noisy_rate(
                float(sped_vals.fillna(0).sum()),
                float(sped_vals.notna().sum()),
                rng,
                budget,
                f"SPED rate | CTIP1={int(c)}",
                0.11,
            ),
            4,
        )
    if not sped:
        sped = {"0": 0.11, "1": 0.11}
    out = {
        "p_demographics_observed": round(p_observed_default, 4),
        "p_demographics_observed_by_aa": observed_by_aa,
        "coarse_eth_citywide": city_eth,
        "coarse_eth_by_aa": eth_by_aa,
        "coarse_eth_tilt_by_ctip1": eth_tilt,
        "fine_eth_by_coarse": fine_by_coarse,
        "homelang_by_coarse_eth": hl_by_eth,
        "homelang_by_coarse_eth_ctip": hl_by_eth_ctip,
        "homelang_citywide": city_hl,
        "englprof_by_homelang": englprof,
        "sped_rate_by_ctip1": sped,
    }
    if profile == PROFILE_JOINT_FRL_ETH:
        scores = obs.apply(frl_score, axis=1)
        edges = frl_bin_edges(scores)
        bins = scores.apply(lambda s: assign_frl_bin(s, edges))
        eth_by_frl = {}
        for label in FRL_BIN_LABELS:
            grp = obs.loc[bins == label, "coarse_eth"]
            eth_by_frl[label] = hist(
                grp,
                rng,
                budget,
                f"coarse ethnicity | FRL {label}",
                prior=city_eth,
            )
        out["frl_bin_edges"] = edges
        out["frl_bin_labels"] = list(FRL_BIN_LABELS)
        out["coarse_eth_by_frl_bin"] = eth_by_frl
        out["race_frl_aa_blend"] = race_frl_aa_blend
    return out


def _priority_priors(
    students: pd.DataFrame, rng: np.random.Generator, budget: Budget
) -> dict:
    """Aggregate the sibling / pre-K / language-pathway priority priors."""
    df = students
    has_sib = df["sibling"].apply(len) > 0
    p_sib_city = noisy_rate(
        float(has_sib.sum()), float(len(df)), rng, budget, "sibling rate", 0.28
    )
    sib_by_aa, p_sib_default = rates_by_area(
        df, has_sib, rng, budget, "sibling rate", p_sib_city
    )
    sib = df[has_sib]
    sib_listed = sib[sib["L"] > 0]
    sibling = {
        "p_two_schools": round(
            noisy_rate(
                float((sib["sibling"].apply(len) > 1).sum()),
                float(len(sib)),
                rng,
                budget,
                "two sibling schools",
                0.005,
            ),
            4,
        ),
        "p_sibling_is_aa_school": round(
            noisy_rate(
                float(
                    sib.apply(
                        lambda r: r.idschoolattendance in r.sibling, axis=1
                    ).sum()
                ),
                float(len(sib)),
                rng,
                budget,
                "sibling school is attendance-area school",
                0.31,
            ),
            4,
        ),
        "p_sibling_in_list": round(
            noisy_rate(
                float(
                    sib_listed.apply(
                        lambda r: any(
                            s in r.r1_ranked_idschool for s in r.sibling
                        ),
                        axis=1,
                    ).sum()
                ),
                float(len(sib_listed)),
                rng,
                budget,
                "sibling school appears in list",
                0.99,
            ),
            4,
        ),
        "p_sibling_first_choice": round(
            noisy_rate(
                float(
                    sib_listed.apply(
                        lambda r: r.r1_ranked_idschool[0] in r.sibling, axis=1
                    ).sum()
                ),
                float(len(sib_listed)),
                rng,
                budget,
                "sibling school is first choice",
                0.92,
            ),
            4,
        ),
        "p_currentlpsibling_given_sibling": round(
            noisy_rate(
                float((sib["currentlpsibling"].apply(len) > 0).sum()),
                float(len(sib)),
                rng,
                budget,
                "sibling is in a language pathway",
                0.03,
            ),
            4,
        ),
    }
    p_aaprek_city = noisy_rate(
        float((df["aaprek"].apply(len) > 0).sum()),
        float(len(df)),
        rng,
        budget,
        "attendance-area pre-K rate",
        0.038,
    )
    aaprek_by_aa, p_aaprek_default = rates_by_area(
        df,
        df["aaprek"].apply(len) > 0,
        rng,
        budget,
        "attendance-area pre-K rate",
        p_aaprek_city,
    )
    prek_counts = Counter(s for row in df.itertuples() for s in row.prek)
    lp_counts = Counter(s for row in df.itertuples() for s in row.currentlp)
    return {
        "p_sibling": round(p_sib_default, 4),
        "p_sibling_by_aa": sib_by_aa,
        "sibling": sibling,
        "p_aaprek": round(p_aaprek_default, 4),
        "p_aaprek_by_aa": aaprek_by_aa,
        "p_prek": round(
            noisy_rate(
                float((df["prek"].apply(len) > 0).sum()),
                float(len(df)),
                rng,
                budget,
                "citywide pre-K rate",
                0.017,
            ),
            4,
        ),
        "prek_schools": to_dist(
            *noisy_counts(prek_counts, rng, budget, "pre-K schools")
        ),
        "p_currentlp": round(
            noisy_rate(
                float((df["currentlp"].apply(len) > 0).sum()),
                float(len(df)),
                rng,
                budget,
                "current language pathway rate",
                0.039,
            ),
            4,
        ),
        "currentlp_schools": to_dist(
            *noisy_counts(
                lp_counts, rng, budget, "current language pathway schools"
            )
        ),
        "designation_rate_by_hlgroup": {
            str(g): round(
                noisy_rate(
                    float(grp["requestprogramdesignation"].sum()),
                    float(grp["requestprogramdesignation"].notna().sum()),
                    rng,
                    budget,
                    f"designation request rate | {g}",
                    0.25,
                ),
                4,
            )
            for g, grp in df.assign(g=df["homelang"].apply(hl_group)).groupby(
                "g"
            )
        },
        "p_isdesignation_ge": round(
            noisy_rate(
                float(
                    (
                        (df["r1_programcode"] == "GE")
                        & (df["r1_isdesignation"] == 1)
                    ).sum()
                ),
                float((df["r1_programcode"] == "GE").sum()),
                rng,
                budget,
                "designation flag | GE assignment",
                0.09,
            ),
            4,
        ),
        "p_isdesignation_lp": round(
            noisy_rate(
                float(
                    (
                        df["r1_programcode"].notna()
                        & (df["r1_programcode"] != "GE")
                        & (df["r1_isdesignation"] == 1)
                    ).sum()
                ),
                float(
                    (
                        df["r1_programcode"].notna()
                        & (df["r1_programcode"] != "GE")
                    ).sum()
                ),
                rng,
                budget,
                "designation flag | language assignment",
                0.02,
            ),
            4,
        ),
        "p_previous_pathway_matches_assignment": round(
            noisy_rate(
                float((df["previous_pathway"] == df["r1_programcode"]).sum()),
                float(len(df)),
                rng,
                budget,
                "previous pathway equals assigned pathway",
                0.92,
            ),
            4,
        ),
        "previous_pathway_citywide": hist(
            df["previous_pathway"], rng, budget, "previous pathway distribution"
        ),
    }


def _missingness_priors(
    students: pd.DataFrame, rng: np.random.Generator, budget: Budget
) -> dict:
    """Rates at which key columns are missing in the source extract."""
    n = float(len(students))
    return {
        "p_no_census_block": round(
            noisy_rate(
                float(students["census_block"].isna().sum()),
                n,
                rng,
                budget,
                "missing census block",
                0.035,
            ),
            4,
        ),
        "p_no_latlon": round(
            noisy_rate(
                float(students["latitude"].isna().sum()),
                n,
                rng,
                budget,
                "missing coordinates",
                0.012,
            ),
            4,
        ),
        "num_ranked_excess": hist(
            (students["num_ranked"] - students["L"]).clip(lower=0),
            rng,
            budget,
            "num_ranked minus list length",
        ),
    }


def extract(
    sfusd_root: Path,
    out_dir: Path,
    year: str,
    seed: int,
    census_blocks_dir: Path | None = None,
    *,
    profile: str = PROFILE_BASELINE,
    variant: str | None = None,
    student_csv: Path | None = None,
    schools_csv: Path | None = None,
    programs_csv: Path | None = None,
    reuse_block_reference: Path | None = None,
) -> None:
    """Run the full extraction and write the two public artifacts.

    Args:
        sfusd_root: Root of the confidential SFUSD data tree (contains ``Data/``
            or ``data/cleaned/``).
        out_dir: Directory to write ``priors/`` and ``reference/`` into.
        year: Two-school-year tag, e.g. ``"2324"``.
        seed: Seed for the Laplace noise draws.
        census_blocks_dir: Optional explicit path to the census block export.
        profile: ``baseline`` or ``joint_frl_eth`` (extra race|FRL / rank-1
            program families).
        variant: ``joint_v4_blend1`` stamps the shipped priors (blend weight
            1.0 and the shipped meta fields). Requires ``joint_frl_eth``.
        student_csv: Optional override for the confidential student file.
        schools_csv: Optional override for the schools table.
        programs_csv: Optional override for the programs table.
        reuse_block_reference: When set, copy this public block reference
            instead of rebuilding it (useful when the census block export /
            block database are unavailable).
    """
    if profile not in VALID_PROFILES:
        raise ValueError(f"Unknown profile {profile!r}; expected one of {VALID_PROFILES}")
    if variant is not None and variant not in VALID_VARIANTS:
        raise ValueError(f"Unknown variant {variant!r}; expected one of {VALID_VARIANTS}")
    if variant == VARIANT_JOINT_V4_BLEND1 and profile != PROFILE_JOINT_FRL_ETH:
        raise ValueError(
            f"--variant {VARIANT_JOINT_V4_BLEND1} requires --profile {PROFILE_JOINT_FRL_ETH}"
        )
    race_frl_aa_blend = (
        SHIPPED_RACE_FRL_AA_BLEND
        if variant == VARIANT_JOINT_V4_BLEND1
        else 0.5
    )
    rng = np.random.default_rng(seed)
    budget = Budget(LAPLACE_EPS)

    students = _load_students(
        sfusd_root,
        year,
        student_csv,
        canonicalize_eth=(profile == PROFILE_JOINT_FRL_ETH),
    )
    schools = pd.read_csv(_resolve_table(sfusd_root, year, "schools", schools_csv))
    programs = pd.read_csv(
        _resolve_table(sfusd_root, year, "programs", programs_csv),
        index_col=0,
    )
    logger.info(
        "loaded %d %s students (profile=%s)", len(students), GRADE, profile
    )

    ref_dir = out_dir / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_path = ref_dir / f"block_reference_{year}.csv"
    ctip_path = ref_dir / f"ctip_by_tract_{year}.csv"
    if reuse_block_reference is not None:
        src = Path(reuse_block_reference)
        if not src.is_file():
            raise FileNotFoundError(f"reuse block reference not found: {src}")
        reference = pd.read_csv(src)
        sibling_ctip = src.with_name(f"ctip_by_tract_{year}.csv")
        if "ctip_2013" in reference.columns:
            tract_ctip = _ctip_by_tract_from_block_frame(reference)
            reference = reference.drop(columns=["ctip_2013"])
        elif sibling_ctip.is_file():
            tract_ctip = pd.read_csv(sibling_ctip)
        else:
            raise FileNotFoundError(
                "reuse block reference has no ctip_2013 and "
                f"{sibling_ctip.name} is missing"
            )
        if src.resolve() != ref_path.resolve():
            reference.to_csv(ref_path, index=False)
        else:
            reference.to_csv(ref_path, index=False)
        tract_ctip.to_csv(ctip_path, index=False)
        logger.info(
            "reused block reference: %d blocks from %s; wrote %d tract CTIP rows",
            len(reference),
            src,
            len(tract_ctip),
        )
    else:
        reference, tract_ctip = _build_block_reference(
            sfusd_root, students, schools, census_blocks_dir
        )
        reference.to_csv(ref_path, index=False)
        tract_ctip.to_csv(ctip_path, index=False)
        logger.info(
            "block reference: %d blocks; tract CTIP: %d tracts",
            len(reference),
            len(tract_ctip),
        )

    budget.spend("cohort size")
    n_noisy = int(round(len(students) + rng.laplace(0.0, 1.0 / LAPLACE_EPS)))
    aa_counts_raw = Counter(
        int(a) for a in students["idschoolattendance"].dropna().astype(int)
    )
    aa_counts, _ = noisy_counts(
        aa_counts_raw, rng, budget, "students per attendance area"
    )
    scale = n_noisy / max(sum(aa_counts.values()), 1)
    aa_counts = {str(k): int(round(v * scale)) for k, v in aa_counts.items()}

    priors = {
        "meta": {
            "source_year": year,
            "grade": GRADE,
            "generated": _dt.date.today().isoformat(),
            "profile": profile,
            "laplace_epsilon_per_family": LAPLACE_EPS,
            "min_cell": MIN_CELL,
            "min_rate_denominator": MIN_RATE_DEN,
            "prior_floor": PRIOR_FLOOR,
            "tilt_cap": TILT_CAP,
            "min_blockgroup_blocks": MIN_BG_BLOCKS,
            "min_blockgroup_students": MIN_BG_STUDENTS,
            "attribute_decimals": ATTR_ROUND,
            "frl_edge_round": FRL_EDGE_ROUND,
            "non_laplace_releases": [
                "blockgroup socio-economic attribute means",
                "within-block-group attribute residual quantiles",
                "frl_bin_edges (snapped to frl_edge_round grid)",
                "ctip_by_tract (binary CTIP1 per census tract)",
            ],
        },
        "n_students": n_noisy,
        "students_per_aa": aa_counts,
        "blockgroup_attributes": _blockgroup_attributes(students),
        "blockgroup_residuals": _blockgroup_residuals(students),
        "choice": _choice_priors(
            students, schools, programs, rng, budget, profile=profile
        ),
        "demographics": _demographic_priors(
            students,
            rng,
            budget,
            profile=profile,
            race_frl_aa_blend=race_frl_aa_blend,
        ),
        "priorities": _priority_priors(students, rng, budget),
        "missingness": _missingness_priors(students, rng, budget),
    }
    priors["meta"]["n_noisy_queries"] = len(budget.queries)
    priors["meta"]["n_query_families"] = len(budget.families)
    priors["meta"]["composed_epsilon"] = round(budget.total_eps, 3)
    priors["meta"]["query_families"] = budget.families
    if variant == VARIANT_JOINT_V4_BLEND1:
        priors["meta"]["variant"] = VARIANT_JOINT_V4_BLEND1
        priors["meta"]["parent_variant"] = SHIPPED_PARENT_VARIANT
        priors["meta"]["privacy_revision"] = SHIPPED_PRIVACY_REVISION
        priors["meta"]["race_frl_aa_blend_override"] = SHIPPED_RACE_FRL_AA_BLEND

    priors_dir = out_dir / "priors"
    priors_dir.mkdir(parents=True, exist_ok=True)
    priors_path = priors_dir / f"synthetic_priors_{year}.json"
    with open(priors_path, "w") as handle:
        json.dump(priors, handle, indent=1, sort_keys=True)
    logger.info(
        "wrote %s (%d queries in %d families, composed eps=%.1f)",
        priors_path,
        len(budget.queries),
        len(budget.families),
        budget.total_eps,
    )
    logger.info("wrote %s", ref_path)
    logger.info("wrote %s", ctip_path)
    logger.info("wrote %s", ctip_path)


def _read_seed_file(path: Path) -> int:
    """Read the private noise seed from ``path``.

    Accepts a bare integer or an ``EXTRACTION_SEED_PRIVATE=<int>`` line, so the
    custodians' combined seed file can be passed directly.
    """
    lines = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for line in lines:
        if line.startswith("EXTRACTION_SEED_PRIVATE="):
            return int(line.split("=", 1)[1])
    if len(lines) == 1 and "=" not in lines[0]:
        return int(lines[0])
    raise ValueError(f"No private seed found in {path}")


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] %(message)s"
    )
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--sfusd-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--year", default="2324")
    seed_group = parser.add_mutually_exclusive_group(required=True)
    seed_group.add_argument(
        "--seed",
        type=int,
        help="Private noise seed. Prefer --seed-file; never commit or publish it.",
    )
    seed_group.add_argument(
        "--seed-file",
        type=Path,
        help="File holding the private noise seed, either as a bare integer or "
        "on an EXTRACTION_SEED_PRIVATE=<int> line.",
    )
    parser.add_argument(
        "--profile",
        choices=VALID_PROFILES,
        default=PROFILE_BASELINE,
        help="baseline keeps today's families; joint_frl_eth adds race|FRL "
        "and rank-1 program-type families.",
    )
    parser.add_argument(
        "--variant",
        choices=VALID_VARIANTS,
        default=None,
        help="joint_v4_blend1 recreates the shipped priors: requires "
        "joint_frl_eth, stores race_frl_aa_blend 1.0, and stamps "
        "meta.variant, meta.parent_variant, meta.privacy_revision, and "
        "meta.race_frl_aa_blend_override. See the module docstring for the "
        "full command and the local files it needs.",
    )
    parser.add_argument(
        "--student-csv",
        type=Path,
        default=None,
        help="Override path to the confidential student CSV.",
    )
    parser.add_argument("--schools-csv", type=Path, default=None)
    parser.add_argument("--programs-csv", type=Path, default=None)
    parser.add_argument(
        "--reuse-block-reference",
        type=Path,
        default=None,
        help="Copy an existing public block_reference_<year>.csv instead of "
        "rebuilding from the census block export.",
    )
    parser.add_argument(
        "--census-blocks-dir",
        type=Path,
        default=None,
        help="Directory holding the public 2010 census block shapefile export.",
    )
    args = parser.parse_args()
    seed = args.seed if args.seed is not None else _read_seed_file(args.seed_file)
    extract(
        args.sfusd_root,
        args.out_dir,
        args.year,
        seed,
        args.census_blocks_dir,
        profile=args.profile,
        variant=args.variant,
        student_csv=args.student_csv,
        schools_csv=args.schools_csv,
        programs_csv=args.programs_csv,
        reuse_block_reference=args.reuse_block_reference,
    )


if __name__ == "__main__":
    main()
