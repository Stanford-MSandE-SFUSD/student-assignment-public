"""Build the public synthetic SFUSD student dataset from aggregate priors.

Stage 2 of 2. This script reads only committed artifacts --

  * ``priors/synthetic_priors_<year>.json``  (noised / suppressed aggregates)
  * ``reference/block_reference_<year>.csv`` (public census + boundary geography)
  * the school and program tables

-- and emits a synthetic cohort with the schema the simulator expects. It never
reads a student record, so anyone who clones the repo can re-run it.

For every attendance area the generator draws ``n_a`` households from the public
census blocks of that area, then samples each household's features and ranked
list independently from the area-level and citywide distributions in the priors
file. No real student's location, attribute vector or ranked list is reproduced.

Usage:
    python scripts/generators/generate_synthetic_dataset.py \
        --data-dir data/synthetic_2324
"""

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from student_assignment.choice_model import (  # noqa: E402
    ChoiceSetMode,
    compute_utilities,
    load_weights,
)

logger = logging.getLogger(__name__)

GRADE = "KG"

# Fraction of a block's equivalent radius used as the jitter radius when placing
# a synthetic household. A median San Francisco block is ~70 m across, so this
# spreads the point through the block without moving it to a different one.
JITTER_FRACTION = 0.7
METERS_PER_DEGREE_LAT = 111_320.0

# Blocks with no children still get a small weight so that every block of an
# attendance area is reachable; this deliberately blurs where families live.
BLOCK_WEIGHT_FLOOR = 0.25

# Temperature of the softmax used to place a sibling's school. Siblings
# attend schools their family would plausibly have chosen, so the draw reuses
# the choice model's own utilities (with the sibling term itself switched off)
# rather than introducing a separate distance kernel.
SIBLING_PLACEMENT_TEMPERATURE = 1.0

# Round-1 priority tiers, highest first. The district's kindergarten
# tie-breakers apply in this order, with a single lottery number breaking ties
# inside a tier.
PRIORITY_TIERS = {"sibling": 8, "prek": 4, "attendance_area": 2, "ctip1": 1}

STUDENT_COLUMNS = [
    "studentno",
    "r1_ranked_idschool",
    "r1_listed_ranks",
    "r1_programs",
    "grade",
    "r1_randomnumber",
    "r1_cohortstring",
    "bayview_to_all_ms",
    "brown_ms_to_hs",
    "bayview_to_brown_ms",
    "r1_designation_randomnumber",
    "requestprogramdesignation",
    "latitude",
    "longitude",
    "previous_pathway",
    "msf",
    "r2_ranked_idschool",
    "r2_listed_ranks",
    "r2_programs",
    "r2_randomnumber",
    "r2_cohortstring",
    "r2_designation_randomnumber",
    "r1_idschool",
    "r1_programcode",
    "r1_rank",
    "r1_isdesignation",
    "r1_distance",
    "idschoolattendance",
    "ctip1",
    "r2_idschool",
    "r2_programcode",
    "r2_rank",
    "r2_isdesignation",
    "r2_distance",
    "enrolled_idschool",
    "homelang",
    "englprof",
    "sped",
    "resolved_ethnicity",
    "final_school",
    "num_ranked",
    "census_block",
    "freelunch_prob",
    "reducedlunch_prob",
    "census_blockgroup",
    "census_tract",
    "FRL Score",
    "N'hood SES Score",
    "Academic Score",
    "AALPI Score",
    "HOCidx1",
    "sibling",
    "currentlpsibling",
    "currentlp",
    "aaprek",
    "prek",
    "aa",
    "zipcode",
    "median_hh_income",
    "lowell_ranked",
    "sota_ranked",
]

BLOCK_ATTR_COLUMNS = [
    "freelunch_prob",
    "reducedlunch_prob",
    "FRL Score",
    "N'hood SES Score",
    "Academic Score",
    "AALPI Score",
    "HOCidx1",
    "median_hh_income",
]

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


def hl_group(label) -> str:
    """Map a home-language code to its pathway-relevant group."""
    if not isinstance(label, str):
        return "OTH"
    return HOMELANG_GROUPS.get(label, "OTH")


def draw(dist: dict, rng: np.random.Generator, default=None):
    """Draw one key from a ``{key: weight}`` mapping.

    Args:
        dist: Weight mapping; may be empty.
        rng: Seeded generator.
        default: Value returned when ``dist`` carries no mass.

    Returns:
        A key of ``dist``, or ``default``.
    """
    if not dist:
        return default
    keys = list(dist)
    weights = np.array([dist[k] for k in keys], dtype=float)
    total = weights.sum()
    if total <= 0:
        return default
    return keys[int(rng.choice(len(keys), p=weights / total))]


def tilt(dist: dict, factors: dict) -> dict:
    """Multiply a distribution by per-key factors and renormalise.

    Used to fold a citywide CTIP1 effect into an area-level distribution
    without needing the (very sparse) area-by-CTIP1 cross-tabulation.

    Args:
        dist: Base distribution.
        factors: Multiplicative factors keyed like ``dist``.

    Returns:
        The tilted, renormalised distribution.
    """
    out = {k: v * float(factors.get(k, 1.0)) for k, v in dist.items()}
    total = sum(out.values())
    if total <= 0:
        return dict(dist)
    return {k: v / total for k, v in out.items()}


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles between (arrays of) coordinates."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 3958.8 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def sample_locations(
    aa_counts: dict, blocks: pd.DataFrame, rng: np.random.Generator
) -> pd.DataFrame:
    """Draw one synthetic household location per synthetic student.

    Blocks are drawn within each attendance area with probability proportional
    to the block's 2010 Census under-18 count (plus a floor), and the point is
    then jittered inside the block around its published TIGER internal point.
    Both inputs are public, so the coordinates carry no information about where
    any applicant actually lived -- only the shape of the city.

    Args:
        aa_counts: Attendance-area school id (as str) -> number of students.
        blocks: The block reference table.
        rng: Seeded generator.

    Returns:
        One row per student with its block, block group, tract, ZIP, CTIP
        designation and jittered coordinates.
    """
    usable = blocks.dropna(subset=["intptlat", "intptlon", "BlockGroup"])
    by_aa = {aa: grp for aa, grp in usable.groupby("aa_school_id")}
    frames = []
    for aa_str, count in sorted(aa_counts.items(), key=lambda kv: int(kv[0])):
        aa = int(aa_str)
        pool = by_aa.get(aa)
        if pool is None or pool.empty:
            raise ValueError(f"No reference blocks for attendance area {aa}")
        weights = pool["pop_under18"].to_numpy(dtype=float) + BLOCK_WEIGHT_FLOOR
        chosen = pool.iloc[
            rng.choice(len(pool), size=int(count), p=weights / weights.sum())
        ]
        radius_m = JITTER_FRACTION * np.sqrt(
            np.maximum(chosen["aland_m2"].to_numpy(dtype=float), 100.0) / np.pi
        )
        angle = rng.uniform(0, 2 * np.pi, len(chosen))
        # The sqrt keeps the draw uniform over the disc instead of clumping in.
        radius = radius_m * np.sqrt(rng.uniform(0, 1, len(chosen)))
        lat = chosen["intptlat"].to_numpy(dtype=float)
        lon = chosen["intptlon"].to_numpy(dtype=float)
        frames.append(
            pd.DataFrame(
                {
                    "idschoolattendance": float(aa),
                    "census_block": chosen["Block"].to_numpy(),
                    "census_blockgroup": chosen["BlockGroup"].to_numpy(),
                    "census_tract": chosen["Tract"].to_numpy(),
                    "zipcode": chosen["zipcode"].to_numpy(),
                    "ctip_2013": chosen["ctip_2013"].to_numpy(),
                    "latitude": (
                        lat + (radius * np.sin(angle)) / METERS_PER_DEGREE_LAT
                    ).round(6),
                    "longitude": (
                        lon
                        + (radius * np.cos(angle))
                        / (METERS_PER_DEGREE_LAT * np.cos(np.radians(lat)))
                    ).round(6),
                }
            )
        )
    out = pd.concat(frames, ignore_index=True)
    shuffled = rng.permutation(len(out))
    return out.iloc[shuffled].reset_index(drop=True)


def sample_block_attributes(
    students: pd.DataFrame, priors: dict, rng: np.random.Generator
) -> pd.DataFrame:
    """Attach the socio-economic attributes of each synthetic household's block.

    The priors carry one value per census *block group* (the coarsening that
    protects the one-household blocks of the source data) plus the quantiles of
    the within-block-group spread that coarsening removed. Each synthetic block
    draws its own residual from those quantiles, once, so the attribute stays a
    property of the block, varies between neighbouring blocks the way the real
    data does, and matches the real marginal distribution.

    Args:
        students: Frame with ``census_block`` and ``census_blockgroup``.
        priors: The priors dict.
        rng: Seeded generator.

    Returns:
        Frame of attribute columns aligned to ``students``.
    """
    means = priors["blockgroup_attributes"]
    spread = priors["blockgroup_residuals"]
    levels = None
    per_block: dict[tuple[int, str], float] = {}
    out = {column: [] for column in BLOCK_ATTR_COLUMNS}
    missing_block: dict[tuple[int, str], bool] = {}
    for block, bg in zip(
        students["census_block"], students["census_blockgroup"]
    ):
        bg_values = means.get(str(int(bg)), {})
        for column in BLOCK_ATTR_COLUMNS:
            base = bg_values.get(column)
            config = spread.get(column)
            key = (int(block), column)
            if base is None or config is None:
                out[column].append(np.nan)
                continue
            if key not in missing_block:
                missing_block[key] = rng.random() < float(config["p_missing"])
            if missing_block[key]:
                out[column].append(np.nan)
                continue
            if key not in per_block:
                quantiles = np.asarray(config["quantiles"], dtype=float)
                if levels is None or len(levels) != len(quantiles):
                    levels = np.linspace(0.0, 1.0, len(quantiles))
                residual = float(np.interp(rng.random(), levels, quantiles))
                value = float(base) + residual
                value = min(
                    max(value, float(config["min"])), float(config["max"])
                )
                per_block[key] = (
                    int(round(value))
                    if column == "median_hh_income"
                    else round(value, 4)
                )
            out[column].append(per_block[key])
    return pd.DataFrame(out, index=students.index)


def sample_lengths(
    students: pd.DataFrame, priors: dict, rng: np.random.Generator
) -> np.ndarray:
    """Draw a ranked-list length for every student.

    The bin comes from the student's attendance-area length histogram, tilted
    by the citywide CTIP1 length effect -- CTIP1 applicants file markedly
    shorter lists -- and a length is then drawn uniformly inside the bin.

    Args:
        students: Frame with ``idschoolattendance`` and ``ctip1``.
        priors: The priors dict.
        rng: Seeded generator.

    Returns:
        Integer list length per student.
    """
    choice = priors["choice"]
    bins = [tuple(b) for b in choice["length_bins"]]
    tilts = choice["length_tilt_by_ctip1"]
    out = np.zeros(len(students), dtype=int)
    aa_values = students["idschoolattendance"].to_numpy()
    ctip_values = students["ctip1"].fillna(0).to_numpy()
    cache: dict[tuple[int, int], dict] = {}
    for i in range(len(students)):
        key = (int(aa_values[i]), int(ctip_values[i]))
        dist = cache.get(key)
        if dist is None:
            dist = tilt(
                choice["length_by_aa"].get(
                    str(key[0]), choice["length_citywide"]
                ),
                tilts[str(key[1])],
            )
            cache[key] = dist
        lo, hi = bins[int(draw(dist, rng, default="5"))]
        out[i] = int(rng.integers(lo, hi + 1))
    return out


def sample_demographics(
    students: pd.DataFrame, priors: dict, rng: np.random.Generator
) -> pd.DataFrame:
    """Draw ethnicity, home language, English proficiency and SPED status.

    Race is drawn from the attendance area's coarse-group distribution tilted
    by the citywide CTIP1 effect, then refined to a reported label citywide;
    home language is drawn conditional on the coarse group and CTIP1 status,
    and English proficiency conditional on the language. Because each layer is
    a separate draw, the joint (area, reported race, language) cell of any real
    student is never reproduced as a unit.

    Args:
        students: Frame with ``idschoolattendance`` and ``ctip1``.
        priors: The priors dict.
        rng: Seeded generator.

    Returns:
        Frame with the demographic columns plus an ``observed`` flag.
    """
    dem = priors["demographics"]
    observed_by_aa = dem["p_demographics_observed_by_aa"]
    p_observed = dem["p_demographics_observed"]
    eth_tilts = dem["coarse_eth_tilt_by_ctip1"]
    aa_values = students["idschoolattendance"].to_numpy()
    ctip_values = students["ctip1"].fillna(0).to_numpy()

    rows = []
    for i in range(len(students)):
        aa = str(int(aa_values[i]))
        ctip = int(ctip_values[i])
        if rng.random() > float(observed_by_aa.get(aa, p_observed)):
            # The whole demographic block is missing together in the source
            # extract, for applicants who never enrolled in the district.
            rows.append(
                {
                    "resolved_ethnicity": np.nan,
                    "homelang": np.nan,
                    "englprof": np.nan,
                    "sped": np.nan,
                    "observed": False,
                }
            )
            continue
        coarse = draw(
            tilt(
                dem["coarse_eth_by_aa"].get(aa, dem["coarse_eth_citywide"]),
                eth_tilts[str(ctip)],
            ),
            rng,
            default="Hispanic",
        )
        lang = draw(
            dem["homelang_by_coarse_eth_ctip"].get(
                f"{coarse}|{ctip}",
                dem["homelang_by_coarse_eth"].get(
                    coarse, dem["homelang_citywide"]
                ),
            ),
            rng,
            default="EN",
        )
        rows.append(
            {
                "resolved_ethnicity": draw(
                    dem["fine_eth_by_coarse"].get(coarse, {}),
                    rng,
                    default=coarse,
                ),
                "homelang": lang,
                "englprof": draw(
                    dem["englprof_by_homelang"].get(
                        lang, dem["englprof_by_homelang"]["__default__"]
                    ),
                    rng,
                    default="E",
                ),
                "sped": float(
                    rng.random()
                    < float(dem["sped_rate_by_ctip1"].get(str(ctip), 0.11))
                ),
                "observed": True,
            }
        )
    return pd.DataFrame(rows, index=students.index)


def sample_priorities(
    students: pd.DataFrame,
    priors: dict,
    school_ids: list[int],
    placement_weights: np.ndarray,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Draw sibling, pre-K and language-pathway priorities.

    A sibling school is either the applicant's own attendance-area school (at
    the citywide rate) or a school drawn from ``placement_weights`` -- the
    choice model's own utilities with the sibling term switched off. Siblings
    attend schools their family would plausibly have chosen, so reusing the
    model here keeps sibling placement consistent with everything else and
    avoids inventing a second notion of "nearby and desirable".

    Args:
        students: Frame with ``idschoolattendance``.
        priors: The priors dict.
        school_ids: Column order of ``placement_weights``.
        placement_weights: Row-normalised ``(n_students, n_schools)``
            probabilities over schools.
        rng: Seeded generator.

    Returns:
        Frame of priority columns aligned to ``students``.
    """
    pri = priors["priorities"]
    sib_cfg = pri["sibling"]
    aa_values = students["idschoolattendance"].to_numpy()
    rows = []
    for i in range(len(students)):
        aa = int(aa_values[i]) if not pd.isna(aa_values[i]) else -1
        sibling: list[int] = []
        if rng.random() < float(
            pri["p_sibling_by_aa"].get(str(aa), pri["p_sibling"])
        ):
            if aa > 0 and rng.random() < float(
                sib_cfg["p_sibling_is_aa_school"]
            ):
                sibling = [aa]
            else:
                sibling = [
                    school_ids[
                        int(rng.choice(len(school_ids), p=placement_weights[i]))
                    ]
                ]
            if rng.random() < float(sib_cfg["p_two_schools"]):
                extra = school_ids[
                    int(rng.choice(len(school_ids), p=placement_weights[i]))
                ]
                if extra not in sibling:
                    sibling.append(extra)
        aaprek = (
            [aa]
            if aa > 0
            and rng.random()
            < float(pri["p_aaprek_by_aa"].get(str(aa), pri["p_aaprek"]))
            else []
        )
        prek: list[int] = []
        if not aaprek and rng.random() < float(pri["p_prek"]):
            school = draw(pri["prek_schools"], rng)
            if school is not None:
                prek = [int(school)]
        currentlp: list[int] = []
        if rng.random() < float(pri["p_currentlp"]):
            school = draw(pri["currentlp_schools"], rng)
            if school is not None:
                currentlp = [int(school)]
        rows.append(
            {
                "sibling": sibling,
                "aaprek": aaprek,
                "prek": prek,
                "currentlp": currentlp,
                "lp_sibling": bool(
                    sibling
                    and rng.random()
                    < float(sib_cfg["p_currentlpsibling_given_sibling"])
                ),
            }
        )
    return pd.DataFrame(rows, index=students.index)


def school_placement_weights(
    utilities: pd.DataFrame, school_ids: list[int], program_ids: list[str]
) -> np.ndarray:
    """Collapse program utilities into a probability distribution over schools.

    Each school is scored by its best program for that student, then the
    scores are turned into probabilities with a softmax. Used only to place
    the schools a student's sibling or pre-K attends.

    Args:
        utilities: ``(n_students, n_programs)`` utilities.
        school_ids: Schools to score, in output column order.
        program_ids: Column order of ``utilities``.

    Returns:
        Row-normalised ``(n_students, n_schools)`` probabilities.
    """
    values = utilities.to_numpy(dtype=float)
    columns_by_school = defaultdict(list)
    for j, program_id in enumerate(program_ids):
        columns_by_school[int(str(program_id).split("-")[0])].append(j)
    best = np.full((values.shape[0], len(school_ids)), -np.inf)
    for k, school in enumerate(school_ids):
        columns = columns_by_school.get(school)
        if columns:
            best[:, k] = values[:, columns].max(axis=1)
    # Softmax over a row that may be entirely -inf (no eligible program
    # anywhere) falls back to uniform.
    shifted = best / SIBLING_PLACEMENT_TEMPERATURE
    shifted -= np.where(
        np.isfinite(shifted).any(axis=1, keepdims=True),
        np.nanmax(
            np.where(np.isfinite(shifted), shifted, np.nan),
            axis=1,
            keepdims=True,
        ),
        0.0,
    )
    weights = np.exp(np.where(np.isfinite(shifted), shifted, -np.inf))
    totals = weights.sum(axis=1, keepdims=True)
    uniform = np.full(len(school_ids), 1.0 / len(school_ids))
    return np.where(
        totals > 0, weights / np.where(totals > 0, totals, 1.0), uniform
    )


def draw_lists_from_model(
    utilities: pd.DataFrame,
    lengths: np.ndarray,
    rng: np.random.Generator,
) -> tuple[list[list[int]], list[list[str]]]:
    """Draw each applicant's ranked list from the choice model.

    This is the model's own preference draw, as implemented by
    ``Metrics.get_preferences`` in SFUSD-Choice-public: add a standard Gumbel
    shock to every utility and sort descending. Truncating that ranking at the
    applicant's list length gives a Plackett-Luce draw from the fitted model,
    so the ordering, the mix of program types and the geography of the list
    are all consequences of the model rather than of separately calibrated
    priors.

    Args:
        utilities: ``(n_students, n_programs)`` utilities, ``-inf`` outside
            the choice set.
        lengths: Number of programs each applicant ranks.
        rng: Seeded generator.

    Returns:
        Ranked school ids and the parallel program types.
    """
    program_ids = np.asarray(utilities.columns)
    keys = utilities.to_numpy(dtype=float) + rng.gumbel(
        0.0, 1.0, utilities.shape
    )
    order = np.argsort(-keys, axis=1)
    schools: list[list[int]] = []
    types: list[list[str]] = []
    for i, length in enumerate(lengths):
        # Skipping non-finite keys keeps an applicant from ever ranking a
        # program outside their choice set, even when their drawn length
        # exceeds the size of that set.
        picked = [
            program_ids[j]
            for j in order[i, : int(length)]
            if np.isfinite(keys[i, j])
        ]
        schools.append([int(str(p).split("-")[0]) for p in picked])
        types.append([str(p).split("-")[1] for p in picked])
    return schools, types


def run_round1_da(
    lists: list[list[int]],
    codes: list[list[str]],
    students: pd.DataFrame,
    priorities: pd.DataFrame,
    programs: pd.DataFrame,
    distances: np.ndarray,
    school_index: dict[int, int],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Run student-proposing deferred acceptance for the round-1 outcome.

    Programs rank applicants by priority tier -- sibling, pre-K,
    attendance area, CTIP1 -- and break ties on a single lottery number, which
    is the structure of the district's kindergarten round 1. Running the
    mechanism (rather than sampling an offer rank) keeps the outcome columns
    capacity-feasible and internally consistent with the synthetic lists and
    priorities.

    Args:
        lists: Ranked school ids per student.
        codes: Program types parallel to ``lists``.
        students: Frame with ``idschoolattendance`` and ``ctip1``.
        priorities: Frame from :func:`sample_priorities`.
        programs: Programs table with ``program_id`` and ``capacity``.
        distances: ``(n_students, n_schools)`` miles matrix.
        school_index: School id -> column of ``distances``.
        rng: Seeded generator.

    Returns:
        Frame with ``r1_idschool``, ``r1_programcode`` and ``r1_rank``;
        ``r1_rank`` is missing for applicants placed off their own list.
    """
    capacity = {
        str(row.program_id): int(row.capacity) for row in programs.itertuples()
    }
    n = len(lists)
    lottery = rng.uniform(0, 1, n)
    aa_values = students["idschoolattendance"].to_numpy()
    ctip_values = students["ctip1"].fillna(0).to_numpy()

    def tier(i: int, school: int) -> int:
        row = priorities.iloc[i]
        score = 0
        if school in row["sibling"]:
            score += PRIORITY_TIERS["sibling"]
        if school in row["aaprek"] or school in row["prek"]:
            score += PRIORITY_TIERS["prek"]
        if not pd.isna(aa_values[i]) and school == int(aa_values[i]):
            score += PRIORITY_TIERS["attendance_area"]
        if ctip_values[i] == 1:
            score += PRIORITY_TIERS["ctip1"]
        return score

    next_choice = np.zeros(n, dtype=int)
    held: dict[str, list[tuple[int, float, int]]] = defaultdict(list)
    free = [i for i in range(n) if lists[i]]
    while free:
        proposals: dict[str, list[tuple[int, float, int]]] = defaultdict(list)
        still_free = []
        for i in free:
            pos = next_choice[i]
            if pos >= len(lists[i]):
                continue
            school = lists[i][pos]
            program = f"{school}-{codes[i][pos]}-{GRADE}"
            if program not in capacity:
                # Special-programme choices have no capacity row; the simulator
                # drops these applicants via remove-special-lps.
                next_choice[i] += 1
                still_free.append(i)
                continue
            proposals[program].append((-tier(i, school), lottery[i], i))
        for program, incoming in proposals.items():
            pool = held[program] + incoming
            pool.sort()
            keep = pool[: capacity[program]]
            for _, _, i in pool[capacity[program] :]:
                next_choice[i] += 1
                if next_choice[i] < len(lists[i]):
                    still_free.append(i)
            held[program] = keep
        free = still_free

    assigned_program = {}
    for program, pool in held.items():
        for _, _, i in pool:
            assigned_program[i] = program

    # District practice: an applicant who filed a list but cleared none of it is
    # placed administratively at a school that still has space. In the source
    # year only 3 of 3,955 listed applicants ended round 1 with no offer, and
    # ~7% of offers were outside the applicant's own list.
    remaining = {
        program: capacity[program] - len(held.get(program, []))
        for program in capacity
    }
    leftover = [i for i in range(n) if lists[i] and i not in assigned_program]
    for i in rng.permutation(leftover):
        i = int(i)
        options = [
            (distances[i, school_index[int(p.split("-")[0])]], p)
            for p, seats in remaining.items()
            if seats > 0 and int(p.split("-")[0]) in school_index
        ]
        if not options:
            break
        _, program = min(options)
        assigned_program[i] = program
        remaining[program] -= 1
        next_choice[i] = -1  # placed off-list: no meaningful choice rank

    school_out, code_out, rank_out = [], [], []
    for i in range(n):
        program = assigned_program.get(i)
        if program is None:
            school_out.append(np.nan)
            code_out.append(np.nan)
            rank_out.append(np.nan)
            continue
        school, code = program.split("-")[0], program.split("-")[1]
        school_out.append(float(school))
        code_out.append(code)
        rank_out.append(
            float(next_choice[i] + 1) if next_choice[i] >= 0 else np.nan
        )
    return pd.DataFrame(
        {
            "r1_idschool": school_out,
            "r1_programcode": code_out,
            "r1_rank": rank_out,
        }
    )


def cohort_string(
    school: int,
    code: str,
    ctip1: float,
    sibling: list,
    aa: list,
    aaprek: list,
    prek: list,
    currentlp: list,
    lp_sibling: list,
) -> str:
    """Rebuild the per-choice priority marker string.

    In the source data ``r1_cohortstring`` is fully determined by the priority
    flags -- one entry per ranked choice, markers in the order CTIP1, sibling,
    attendance area, attendance-area pre-K, pre-K, current language pathway,
    language pathway sibling.

    Args:
        school: The ranked school id.
        code: The ranked program type.
        ctip1: CTIP1 flag for the student.
        sibling: Sibling schools.
        aa: Attendance-area priority schools.
        aaprek: Attendance-area pre-K schools.
        prek: Citywide pre-K schools.
        currentlp: Current language pathway schools.
        lp_sibling: Language pathway sibling program ids.

    Returns:
        The marker string for this choice, possibly empty.
    """
    parts = []
    if ctip1 == 1:
        parts.append("CT1;")
    if school in sibling:
        parts.append("S;")
    if school in aa:
        parts.append("AA;")
    if school in aaprek:
        parts.append("AAP;")
    if school in prek:
        parts.append("PK;")
    if school in currentlp:
        parts.append("CL;")
    if f"{school}-{code}-{GRADE}" in lp_sibling:
        parts.append("CLS;")
    return "".join(parts)


def generate(
    data_dir: Path,
    year: str,
    seed: int,
    schools_csv: Path | None = None,
    programs_csv: Path | None = None,
    weights_csv: Path | None = None,
) -> pd.DataFrame:
    """Build and write the synthetic dataset.

    Args:
        data_dir: Dataset root; holds ``priors/`` and ``reference/`` and
            receives the generated CSVs.
        year: Two-school-year tag, e.g. ``"2324"``.
        seed: Master seed; the output is a deterministic function of it.
        schools_csv: Schools table; defaults to ``<data_dir>/Cleaned/``.
        programs_csv: Programs table; defaults to ``<data_dir>/``.
        weights_csv: Choice-model coefficients; defaults to
            ``<data_dir>/choice_model/weights_exp8.csv``.

    Returns:
        The generated student frame.
    """
    rng = np.random.default_rng(seed)
    with open(data_dir / "priors" / f"synthetic_priors_{year}.json") as handle:
        priors = json.load(handle)
    blocks = pd.read_csv(data_dir / "reference" / f"block_reference_{year}.csv")
    schools = pd.read_csv(
        schools_csv or data_dir / "Cleaned" / f"schools_rehauled_{year}.csv"
    )
    programs = pd.read_csv(
        programs_csv or data_dir / f"programs_without_specialprogs_{year}.csv",
        index_col=0,
    )
    weights_csv = weights_csv or data_dir / "choice_model" / "weights_exp8.csv"

    students = sample_locations(priors["students_per_aa"], blocks, rng)
    n = len(students)
    students["ctip1"] = (students["ctip_2013"] == 1).astype(float)
    logger.info(
        "sampled %d synthetic households across %d attendance areas",
        n,
        students["idschoolattendance"].nunique(),
    )

    # Assigned up front because the choice model keys its utility matrix on it.
    students["studentno"] = np.arange(1_000_000, 1_000_000 + n)

    attributes = sample_block_attributes(students, priors, rng)
    for column in BLOCK_ATTR_COLUMNS:
        students[column] = attributes[column]

    schools_ok = schools.dropna(subset=["lat", "lon"])
    school_ids = [int(x) for x in schools_ok["school_id"]]
    index_of = {sid: j for j, sid in enumerate(school_ids)}
    distances = haversine_miles(
        students["latitude"].to_numpy()[:, None],
        students["longitude"].to_numpy()[:, None],
        schools_ok["lat"].to_numpy(dtype=float)[None, :],
        schools_ok["lon"].to_numpy(dtype=float)[None, :],
    )

    demographics = sample_demographics(students, priors, rng)
    for column in ("resolved_ethnicity", "homelang", "englprof", "sped"):
        students[column] = demographics[column]
    lengths = sample_lengths(students, priors, rng)

    # --- preferences, straight from the choice model ----------------------
    # Sibling priority is itself a model feature with a large coefficient, so
    # the utilities are built twice: once with no sibling anywhere, which is
    # what places each sibling's school, and then again once those schools are
    # known.
    weights = load_weights(weights_csv)
    baseline = compute_utilities(
        students.assign(sibling="[]"),
        programs,
        schools,
        weights,
        mode=ChoiceSetMode.FORWARD,
    )
    placement = school_placement_weights(
        baseline, school_ids, list(baseline.columns)
    )
    priorities = sample_priorities(students, priors, school_ids, placement, rng)
    students["sibling"] = [
        [s for s in row if s in index_of] for row in priorities["sibling"]
    ]

    utilities = compute_utilities(
        students, programs, schools, weights, mode=ChoiceSetMode.FORWARD
    )
    eligible = int(np.isfinite(utilities.to_numpy()).sum(axis=1).mean())
    logger.info(
        "choice model: %d coefficients, %d programs, %d eligible per applicant",
        len(weights),
        utilities.shape[1],
        eligible,
    )
    lists, codes = draw_lists_from_model(utilities, lengths, rng)
    lengths = np.array([len(x) for x in lists])

    # --- priority bookkeeping --------------------------------------------
    students["aaprek"] = list(priorities["aaprek"])
    students["prek"] = list(priorities["prek"])
    students["currentlp"] = list(priorities["currentlp"])
    students["aa"] = [
        [int(aa)] if (not pd.isna(aa) and int(aa) in lst) else []
        for aa, lst in zip(students["idschoolattendance"], lists)
    ]
    lp_sibling = []
    for i in range(n):
        options = (
            [
                f"{s}-{c}-{GRADE}"
                for s, c in zip(lists[i], codes[i])
                if c != "GE"
            ]
            if priorities["lp_sibling"].iloc[i]
            else []
        )
        lp_sibling.append(options[:1])
    students["currentlpsibling"] = lp_sibling

    # --- round-1 outcome --------------------------------------------------
    outcomes = run_round1_da(
        lists, codes, students, priorities, programs, distances, index_of, rng
    )
    for column in outcomes.columns:
        students[column] = outcomes[column].to_numpy()
    students["r1_distance"] = [
        round(float(distances[i, index_of[int(s)]]), 2)
        if not pd.isna(s) and int(s) in index_of
        else np.nan
        for i, s in enumerate(students["r1_idschool"])
    ]
    p_final = float(priors["choice"]["p_final_equals_round1"])
    final_pop = priors["choice"]["final_school_citywide"]
    final_school = []
    for assigned in students["r1_idschool"]:
        if not pd.isna(assigned) and rng.random() < p_final:
            final_school.append(int(assigned))
        else:
            pick = draw(final_pop, rng)
            final_school.append(int(pick) if pick is not None else 0)
    students["final_school"] = final_school
    students["enrolled_idschool"] = [
        float(school) if observed else np.nan
        for school, observed in zip(final_school, demographics["observed"])
    ]

    # --- pathway and designation flags -----------------------------------
    pri = priors["priorities"]
    p_prev = float(pri["p_previous_pathway_matches_assignment"])
    previous_pathway = []
    for i in range(n):
        code = students["r1_programcode"].iloc[i]
        if pd.isna(code):
            code = codes[i][0] if codes[i] else "GE"
        if rng.random() >= p_prev:
            code = draw(pri["previous_pathway_citywide"], rng, default=code)
        previous_pathway.append(code)
    students["previous_pathway"] = previous_pathway
    designation_rates = pri["designation_rate_by_hlgroup"]
    groups = [hl_group(x) for x in students["homelang"]]
    students["requestprogramdesignation"] = [
        float(
            rng.random()
            < float(
                designation_rates.get(group, designation_rates.get("EN", 0.25))
            )
        )
        for group in groups
    ]
    students["r1_isdesignation"] = [
        np.nan
        if pd.isna(code)
        else float(
            rng.random()
            < float(
                pri["p_isdesignation_ge"]
                if code == "GE"
                else pri["p_isdesignation_lp"]
            )
        )
        for code in students["r1_programcode"]
    ]

    # --- list-shaped columns ---------------------------------------------
    students["r1_ranked_idschool"] = [str(lst) for lst in lists]
    students["r1_programs"] = [str(c) for c in codes]
    students["r1_listed_ranks"] = [
        str(list(range(1, len(lst) + 1))) for lst in lists
    ]
    students["r1_randomnumber"] = [
        str([round(float(x), 8) for x in rng.uniform(0, 1, len(lst))])
        for lst in lists
    ]
    students["r1_cohortstring"] = [
        str(
            [
                cohort_string(
                    school,
                    code,
                    students["ctip1"].iloc[i],
                    students["sibling"].iloc[i],
                    students["aa"].iloc[i],
                    students["aaprek"].iloc[i],
                    students["prek"].iloc[i],
                    students["currentlp"].iloc[i],
                    students["currentlpsibling"].iloc[i],
                )
                for school, code in zip(lists[i], codes[i])
            ]
        )
        for i in range(n)
    ]
    students["r1_designation_randomnumber"] = [
        float(rng.uniform(0, 1)) if lst else np.nan for lst in lists
    ]
    excess = priors["missingness"]["num_ranked_excess"]
    students["num_ranked"] = [
        len(lst) + int(float(draw(excess, rng, default="0"))) for lst in lists
    ]
    for column in (
        "sibling",
        "currentlpsibling",
        "currentlp",
        "aaprek",
        "prek",
        "aa",
    ):
        students[column] = students[column].apply(str)

    # --- constants and rounds this dataset does not model ----------------
    students["grade"] = GRADE
    for column in (
        "bayview_to_all_ms",
        "brown_ms_to_hs",
        "bayview_to_brown_ms",
    ):
        students[column] = 0.0
    for column in ("lowell_ranked", "sota_ranked"):
        students[column] = 0
    students["msf"] = np.nan
    for column in (
        "r2_ranked_idschool",
        "r2_listed_ranks",
        "r2_programs",
        "r2_randomnumber",
        "r2_cohortstring",
    ):
        students[column] = "[]"
    for column in (
        "r2_designation_randomnumber",
        "r2_idschool",
        "r2_programcode",
        "r2_rank",
        "r2_isdesignation",
        "r2_distance",
    ):
        students[column] = np.nan

    # --- reproduce the source extract's own missingness ------------------
    miss = priors["missingness"]
    p_block = float(miss["p_no_census_block"])
    no_block = rng.random(n) < p_block
    no_latlon = no_block & (
        rng.random(n) < float(miss["p_no_latlon"]) / max(p_block, 1e-9)
    )
    for column in [
        "census_block",
        "census_blockgroup",
        "census_tract",
        "ctip1",
    ] + BLOCK_ATTR_COLUMNS:
        students.loc[no_block, column] = np.nan
    for column in ("latitude", "longitude", "idschoolattendance", "zipcode"):
        students.loc[no_latlon, column] = np.nan

    students = students[STUDENT_COLUMNS]

    # --- programs table, re-derived from the synthetic cohort ------------
    first_counts = Counter(
        f"{lists[i][0]}-{codes[i][0]}-{GRADE}" for i in range(n) if lists[i]
    )
    assigned_counts = Counter(
        f"{int(school)}-{code}-{GRADE}"
        for school, code in zip(
            students["r1_idschool"], students["r1_programcode"]
        )
        if not pd.isna(school) and isinstance(code, str)
    )
    programs_out = programs.copy()
    programs_out["r1_assigned"] = [
        float(assigned_counts.get(str(p), 0))
        for p in programs_out["program_id"]
    ]
    programs_out["r1_noenroll"] = programs_out["r1_assigned"]
    programs_out["r1_first_choice"] = [
        float(first_counts.get(str(p), 0)) for p in programs_out["program_id"]
    ]

    cleaned_dir = data_dir / "Cleaned"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    estimates_path = (
        data_dir / "choice_model" / f"estimates_{year}_synthetic.csv"
    )
    # The simulator's utility-model loader parses the index as
    # "<year>-<studentno>", which is also how the choice model writes it.
    estimates = utilities.round(6)
    estimates.index = [f"{year}-{s}" for s in estimates.index]
    estimates.index.name = "studentno"
    estimates.to_csv(estimates_path)
    student_path = data_dir / f"student_{year}_synthetic.csv"
    programs_path = data_dir / f"programs_without_specialprogs_{year}.csv"
    students.to_csv(student_path, index=False)
    programs_out.to_csv(programs_path)
    if schools_csv is not None:
        schools.to_csv(
            cleaned_dir / f"schools_rehauled_{year}.csv", index=False
        )
    logger.info("wrote %s (%d rows)", student_path, len(students))
    logger.info("wrote %s (%d rows)", programs_path, len(programs_out))
    logger.info(
        "wrote %s (%d x %d utilities)",
        estimates_path,
        utilities.shape[0],
        utilities.shape[1],
    )
    _log_summary(students, lists, codes, distances, index_of)
    return students


def _log_summary(
    students: pd.DataFrame,
    lists: list[list[int]],
    codes: list[list[str]],
    distances: np.ndarray,
    index_of: dict,
) -> None:
    """Log the headline statistics of the generated cohort."""
    lengths = np.array([len(x) for x in lists])
    own_aa = [
        int(lists[i][0]) == int(aa)
        for i, aa in enumerate(students["idschoolattendance"])
        if lists[i] and not pd.isna(aa)
    ]
    logger.info(
        "students=%d  mean list length=%.2f  median=%d  empty lists=%.1f%%",
        len(students),
        lengths.mean(),
        int(np.median(lengths)),
        100 * np.mean(lengths == 0),
    )
    logger.info(
        "general-education share of choices=%.3f  first choice is own area school=%.3f",
        float(np.mean([c == "GE" for row in codes for c in row])),
        float(np.mean(own_aa)),
    )
    listed = lengths > 0
    logger.info(
        "round 1: no offer=%.3f of applicants with a list  first choice=%.3f  placed off-list=%.3f  mean offer distance=%.2f mi",
        float(students["r1_idschool"][listed].isna().mean()),
        float((students["r1_rank"][listed] == 1).mean()),
        float(
            (students["r1_idschool"].notna() & students["r1_rank"].isna())[
                listed
            ].mean()
        ),
        float(students["r1_distance"].mean()),
    )
    logger.info(
        "CTIP1=%.3f  sibling priority=%.3f  demographics observed=%.3f",
        float(students["ctip1"].fillna(0).mean()),
        float((students["sibling"] != "[]").mean()),
        float(students["resolved_ethnicity"].notna().mean()),
    )


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data/synthetic_2324")
    )
    parser.add_argument("--year", default="2324")
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--schools-csv", type=Path, default=None)
    parser.add_argument("--programs-csv", type=Path, default=None)
    parser.add_argument("--weights-csv", type=Path, default=None)
    args = parser.parse_args()
    generate(
        args.data_dir,
        args.year,
        args.seed,
        args.schools_csv,
        args.programs_csv,
        args.weights_csv,
    )


if __name__ == "__main__":
    main()
