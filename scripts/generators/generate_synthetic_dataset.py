"""Build the public synthetic SFUSD student dataset from aggregate priors.

Stage 2 of 2. This script reads only committed artifacts --

  * ``priors/synthetic_priors_<year>.json``  (noised / suppressed aggregates)
  * ``reference/block_reference_<year>.csv`` (public census + boundary geography)
  * ``reference/ctip_by_tract_<year>.csv`` (binary CTIP1 per census tract)
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
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

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

# Minimum weight of the (distance-localised) citywide prior when smoothing an
# attendance area's rank-1 counts. Above this floor the prior is given exactly
# the mass that small-cell suppression removed from the area's own counts,
# matching the smoothing rule the priors file was built with.
RANK1_PRIOR_FLOOR = 2.0

# Public seed for stage 2. The committed dataset is exactly
# generate(..., seed=PUBLIC_SEED); publishing it costs no privacy because this
# stage reads only the already-noised priors and public reference tables. It is
# unrelated to the private seed stage 1 used for the Laplace noise.
PUBLIC_SEED = 170261502658718873328289898402210487511

# Internal generator profiles (priors meta / CLI). The shipped public folder
# is always data/synthetic_2324/; profile names never appear as "v1"/"v2".
PROFILE_BASELINE = "baseline"
PROFILE_JOINT_FRL_ETH = "joint_frl_eth"
VALID_PROFILES = (PROFILE_BASELINE, PROFILE_JOINT_FRL_ETH)

# List positions that share one distance-decay coefficient, matching the
# position groups the priors report a mean choice distance for.
POSITION_STAGES = [
    ("1", 1, 1),
    ("2", 2, 2),
    ("3", 3, 3),
    ("4-6", 4, 6),
    ("7+", 7, 10**6),
]
BETA_BOUNDS = (0.0, 8.0)
BETA_ITERATIONS = 18

# Iterations of the availability-corrected fit for program-type weights, and
# of the outer loop that keeps the fit on target after same-school repeats.
PROGRAM_WEIGHT_ITERATIONS = 200
CODE_CALIBRATION_ITERATIONS = 6

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
    "sibling",
    "currentlpsibling",
    "currentlp",
    "aaprek",
    "prek",
    "aa",
    "zipcode",
    "median_hh_income",
]

# Sampled onto students and written to the public CSV.
BLOCK_ATTR_COLUMNS = [
    "freelunch_prob",
    "reducedlunch_prob",
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
    # Sort keys so choice indices are stable across PYTHONHASHSEED / processes.
    keys = sorted(dist, key=lambda k: str(k))
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
    out = {
        k: v * float(factors.get(k, 1.0))
        for k, v in sorted(dist.items(), key=lambda kv: str(kv[0]))
    }
    total = sum(out.values())
    if total <= 0:
        return dict(dist)
    return {k: v / total for k, v in out.items()}


def blend_dists(a: dict, b: dict, weight_a: float) -> dict:
    """Convex combination of two distributions over a shared support."""
    keys = sorted(set(a) | set(b), key=str)
    if not keys:
        return {}
    w = float(np.clip(weight_a, 0.0, 1.0))
    out = {
        k: w * float(a.get(k, 0.0)) + (1.0 - w) * float(b.get(k, 0.0))
        for k in keys
    }
    total = sum(out.values())
    if total <= 0:
        return dict(a) if a else dict(b)
    return {k: v / total for k, v in out.items() if v > 0}


def frl_total(free, reduced) -> float:
    """Block free-or-reduced lunch probability used for race|FRL bins."""
    if pd.isna(free) and pd.isna(reduced):
        return float("nan")
    return float(
        np.clip(np.nan_to_num(free) + np.nan_to_num(reduced), 0.0, 1.0)
    )


def assign_frl_bin(score, edges) -> str:
    """Map an FRL score to ``low`` / ``mid`` / ``high``."""
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return "mid"
    lo, hi = edges
    if score <= lo:
        return "low"
    if score <= hi:
        return "mid"
    return "high"


def canonicalize_ethnicity_label(label):
    """Rewrite known ethnicity aliases to the evaluator's canonical strings."""
    if not isinstance(label, str):
        return label
    fixes = {
        "Multi-Racial": "Two or More Races",
        "Multiracial": "Two or More Races",
        "Two or More": "Two or More Races",
        "Middle Eastern/Arab": "Middle Eastern/Arabic",
    }
    return fixes.get(label, label)


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
        One row per student with its block, block group, tract, ZIP, and
        jittered coordinates (CTIP1 is joined from the tract table later).
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
    students: pd.DataFrame,
    priors: dict,
    rng: np.random.Generator,
    *,
    profile: str = PROFILE_BASELINE,
) -> pd.DataFrame:
    """Draw ethnicity, home language, English proficiency and SPED status.

    Race is drawn from the attendance area's coarse-group distribution tilted
    by the citywide CTIP1 effect, then refined to a reported label citywide;
    home language is drawn conditional on the coarse group and CTIP1 status,
    and English proficiency conditional on the language. Because each layer is
    a separate draw, the joint (area, reported race, language) cell of any real
    student is never reproduced as a unit.

    Under ``joint_frl_eth``, coarse race is a blend of the AA(+CTIP) prior and
    ``P(coarse eth | FRL tercile)`` where the FRL score comes from the already
    sampled block attributes (place → FRL → race|FRL), and reported labels are
    canonicalized (``Two or More Races`` rather than ``Multi-Racial``).

    Args:
        students: Frame with ``idschoolattendance``, ``ctip1``, and (for the
            joint profile) block FRL columns.
        priors: The priors dict.
        rng: Seeded generator.
        profile: ``baseline`` or ``joint_frl_eth``.

    Returns:
        Frame with the demographic columns plus an ``observed`` flag.
    """
    dem = priors["demographics"]
    observed_by_aa = dem["p_demographics_observed_by_aa"]
    p_observed = dem["p_demographics_observed"]
    eth_tilts = dem["coarse_eth_tilt_by_ctip1"]
    aa_values = students["idschoolattendance"].to_numpy()
    ctip_values = students["ctip1"].fillna(0).to_numpy()
    use_frl = (
        profile == PROFILE_JOINT_FRL_ETH
        and "coarse_eth_by_frl_bin" in dem
        and "frl_bin_edges" in dem
    )
    frl_edges = dem.get("frl_bin_edges", [1.0 / 3.0, 2.0 / 3.0])
    frl_tables = dem.get("coarse_eth_by_frl_bin", {})
    aa_weight = float(dem.get("race_frl_aa_blend", 0.5))
    free_vals = (
        students["freelunch_prob"].to_numpy()
        if use_frl and "freelunch_prob" in students.columns
        else None
    )
    reduced_vals = (
        students["reducedlunch_prob"].to_numpy()
        if use_frl and "reducedlunch_prob" in students.columns
        else None
    )

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
        aa_dist = tilt(
            dem["coarse_eth_by_aa"].get(aa, dem["coarse_eth_citywide"]),
            eth_tilts[str(ctip)],
        )
        if use_frl:
            score = frl_total(free_vals[i], reduced_vals[i])
            bin_label = assign_frl_bin(score, frl_edges)
            frl_dist = frl_tables.get(bin_label, dem["coarse_eth_citywide"])
            coarse_dist = blend_dists(aa_dist, frl_dist, aa_weight)
        else:
            coarse_dist = aa_dist
        coarse = draw(coarse_dist, rng, default="Hispanic")
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
        fine = draw(
            dem["fine_eth_by_coarse"].get(coarse, {}),
            rng,
            default=coarse,
        )
        if profile == PROFILE_JOINT_FRL_ETH:
            fine = canonicalize_ethnicity_label(fine)
        rows.append(
            {
                "resolved_ethnicity": fine,
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


def first_choice_weights(
    students: pd.DataFrame,
    priors: dict,
    school_ids: list[int],
    distances: np.ndarray,
    beta: float,
) -> np.ndarray:
    """Per-student weights over schools for the top of the ranked list.

    An attendance area's own rank-1 counts are smoothed toward the citywide
    rank-1 popularity localised to the household, ``citywide(j) * exp(-beta *
    miles)``. The prior receives exactly the mass that small-cell suppression
    removed from the area's counts, so areas whose cells survived keep their
    real pattern while thin areas fall back to schools near the household
    rather than to the city as a whole.

    Args:
        students: Frame with ``idschoolattendance``.
        priors: The priors dict.
        school_ids: Column order of ``distances``.
        distances: ``(n_students, n_schools)`` miles matrix.
        beta: Distance decay for the fallback prior.

    Returns:
        ``(n_students, n_schools)`` non-negative weights.
    """
    choice = priors["choice"]
    citywide = np.array(
        [
            float(choice["rank1_school_citywide"].get(str(sid), 0.0))
            for sid in school_ids
        ]
    )
    if (citywide > 0).any():
        citywide = np.where(
            citywide > 0, citywide, citywide[citywide > 0].min() * 0.05
        )
    else:
        citywide = np.ones(len(school_ids))
    local = citywide[None, :] * np.exp(-beta * distances)
    local = local / local.sum(axis=1, keepdims=True)

    index_of = {sid: j for j, sid in enumerate(school_ids)}
    own = np.zeros_like(local)
    weight = np.zeros(len(students))
    counts_by_aa = choice["rank1_counts_by_aa"]
    totals_by_aa = choice["rank1_total_by_aa"]
    for i, aa in enumerate(students["idschoolattendance"].to_numpy()):
        key = str(int(aa))
        cells = counts_by_aa.get(key) or {}
        for school, count in cells.items():
            j = index_of.get(int(school))
            if j is not None:
                own[i, j] = float(count)
        suppressed = float(totals_by_aa.get(key, 0.0)) - own[i].sum()
        weight[i] = max(suppressed, 0.0) + RANK1_PRIOR_FLOOR
    return own + weight[:, None] * local


def build_lists(
    heads: list[list[int]],
    lengths: np.ndarray,
    log_popularity: np.ndarray,
    distances: np.ndarray,
    betas: dict[str, float],
    school_ids: list[int],
    rng: np.random.Generator,
) -> list[list[int]]:
    """Sample a ranked school list for every student.

    Schools the student is steered to -- their drawn first choice, and any
    school they hold a sibling or pre-K priority at -- lead the list in order.
    The remaining positions are filled in stages, one per position group, each
    sampling without replacement with probability proportional to
    ``citywide_popularity * exp(-beta_stage * miles)``. Later stages use a
    weaker decay, which is how real lists behave: the first few choices are
    close to home and the tail reaches across the city. Each stage is drawn
    exactly, and in one shot, with the Gumbel-top-k trick.

    Args:
        heads: Schools that must lead each student's list, in order.
        lengths: Target list length per student.
        log_popularity: Log citywide tail popularity per school.
        distances: ``(n_students, n_schools)`` miles matrix.
        betas: Distance decay per position-stage name.
        school_ids: Column order of ``distances``.
        rng: Seeded generator.

    Returns:
        One ranked list of school ids per student.
    """
    n, n_schools = distances.shape
    index_of = {sid: j for j, sid in enumerate(school_ids)}
    ids = np.asarray(school_ids)
    taken = np.zeros((n, n_schools), dtype=bool)
    lists: list[list[int]] = [[] for _ in range(n)]
    for i, head in enumerate(heads):
        for school in head[: int(lengths[i])]:
            lists[i].append(school)
            taken[i, index_of[school]] = True

    for name, lo, hi in POSITION_STAGES:
        if name not in betas:
            continue
        need = np.array(
            [
                max(min(int(lengths[i]), hi) - max(len(lists[i]), lo - 1), 0)
                for i in range(n)
            ]
        )
        if not need.any():
            continue
        keys = log_popularity[None, :] - betas[name] * distances
        keys = keys + rng.gumbel(0.0, 1.0, keys.shape)
        keys[taken] = -np.inf
        order = np.argsort(-keys, axis=1)
        for i in np.flatnonzero(need):
            picks = ids[order[i, : need[i]]]
            for school in picks:
                lists[i].append(int(school))
                taken[i, index_of[int(school)]] = True
    return lists


def calibrate_betas(
    heads: list[list[int]],
    lengths: np.ndarray,
    log_popularity: np.ndarray,
    distances: np.ndarray,
    school_ids: list[int],
    priors: dict,
    seed: int,
) -> dict[str, float]:
    """Fit one distance decay per position stage to the released mean distances.

    The priors record the mean home-to-school distance of real choices at each
    list position. Stages are calibrated in order, each by bisection with the
    earlier stages held at their fitted values, so the synthetic lists match
    that distance profile without any real list being copied.

    Args:
        heads: Schools that must lead each student's list.
        lengths: Target list length per student.
        log_popularity: Log citywide tail popularity per school.
        distances: ``(n_students, n_schools)`` miles matrix.
        school_ids: Column order of ``distances``.
        priors: The priors dict.
        seed: Seed for the trial draws.

    Returns:
        Distance decay per position-stage name.
    """
    targets = priors["choice"]["target_mean_dist_by_position"]
    index_of = {sid: j for j, sid in enumerate(school_ids)}
    betas: dict[str, float] = {}
    for name, lo, hi in POSITION_STAGES:
        if name == "1" or name not in targets:
            continue
        target = float(targets[name])

        def stage_mean(beta: float) -> float:
            trial = dict(betas)
            trial[name] = beta
            lists = build_lists(
                heads,
                lengths,
                log_popularity,
                distances,
                trial,
                school_ids,
                np.random.default_rng(seed),
            )
            values = [
                distances[i, index_of[s]]
                for i, lst in enumerate(lists)
                for s in lst[lo - 1 : hi]
            ]
            return float(np.mean(values)) if values else np.inf

        low, high = BETA_BOUNDS
        for _ in range(BETA_ITERATIONS):
            mid = (low + high) / 2
            if stage_mean(mid) > target:
                low = mid  # choices still too far away: decay harder
            else:
                high = mid
        betas[name] = (low + high) / 2
        logger.info(
            "position %-4s target %.2f mi -> beta %.3f (achieved %.2f mi)",
            name,
            target,
            betas[name],
            stage_mean(betas[name]),
        )
    return betas


def calibrate_first_choice_beta(
    students: pd.DataFrame,
    lengths: np.ndarray,
    priors: dict,
    school_ids: list[int],
    distances: np.ndarray,
    seed: int,
) -> float:
    """Fit the decay of the rank-1 fallback prior to the mean first-choice distance.

    Args:
        students: Frame with ``idschoolattendance``.
        lengths: List length per student (students with no list are skipped).
        priors: The priors dict.
        school_ids: Column order of ``distances``.
        distances: ``(n_students, n_schools)`` miles matrix.
        seed: Seed for the trial draws.

    Returns:
        The calibrated decay.
    """
    targets = priors["choice"]["target_mean_dist_by_position"]
    if "1" not in targets:
        return 1.0
    target = float(targets["1"])
    listed = np.flatnonzero(lengths > 0)

    def mean_distance(beta: float) -> float:
        weights = first_choice_weights(
            students, priors, school_ids, distances, beta
        )
        rng = np.random.default_rng(seed)
        keys = np.log(np.maximum(weights, 1e-300)) + rng.gumbel(
            0.0, 1.0, weights.shape
        )
        picked = keys.argmax(axis=1)
        return float(np.mean(distances[listed, picked[listed]]))

    low, high = BETA_BOUNDS
    for _ in range(BETA_ITERATIONS):
        mid = (low + high) / 2
        if mean_distance(mid) > target:
            low = mid
        else:
            high = mid
    beta = (low + high) / 2
    logger.info(
        "position 1    target %.2f mi -> prior beta %.3f (achieved %.2f mi)",
        target,
        beta,
        mean_distance(beta),
    )
    return beta


def sample_priorities(
    students: pd.DataFrame,
    priors: dict,
    school_ids: list[int],
    distances: np.ndarray,
    beta: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Draw sibling, pre-K and language-pathway priorities.

    A sibling school is either the applicant's own attendance-area school (at
    the citywide rate) or a nearby school drawn from the same popularity times
    distance-decay kernel the ranked lists use.

    Args:
        students: Frame with ``idschoolattendance``.
        priors: The priors dict.
        school_ids: Column order of ``distances``.
        distances: ``(n_students, n_schools)`` miles matrix.
        beta: Distance-decay coefficient.
        rng: Seeded generator.

    Returns:
        Frame of priority columns aligned to ``students``.
    """
    pri = priors["priorities"]
    sib_cfg = pri["sibling"]
    popularity = np.array(
        [
            float(priors["choice"]["school_pop_tail"].get(str(sid), 1e-4))
            for sid in school_ids
        ]
    )
    kernel = popularity[None, :] * np.exp(-beta * distances)
    kernel = kernel / kernel.sum(axis=1, keepdims=True)
    aa_values = students["idschoolattendance"].to_numpy()
    rows = []
    for i in range(len(students)):
        aa = int(aa_values[i])
        sibling: list[int] = []
        if rng.random() < float(
            pri["p_sibling_by_aa"].get(str(aa), pri["p_sibling"])
        ):
            if rng.random() < float(sib_cfg["p_sibling_is_aa_school"]):
                sibling = [aa]
            else:
                sibling = [
                    school_ids[int(rng.choice(len(school_ids), p=kernel[i]))]
                ]
            if rng.random() < float(sib_cfg["p_two_schools"]):
                extra = school_ids[
                    int(rng.choice(len(school_ids), p=kernel[i]))
                ]
                if extra not in sibling:
                    sibling.append(extra)
        aaprek = (
            [aa]
            if rng.random()
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
                "sibling_first": bool(
                    rng.random() < float(sib_cfg["p_sibling_first_choice"])
                ),
                "sibling_in_list": bool(
                    rng.random() < float(sib_cfg["p_sibling_in_list"])
                ),
                "lp_sibling": bool(
                    sibling
                    and rng.random()
                    < float(sib_cfg["p_currentlpsibling_given_sibling"])
                ),
            }
        )
    return pd.DataFrame(rows, index=students.index)


def fit_program_weights(
    lists: list[list[int]],
    groups: list[str],
    priors: dict,
    targets: dict[str, dict[str, float]] | None = None,
) -> dict[str, dict[str, float]]:
    """Fit program-type weights that reproduce the real citywide type shares.

    The priors release ``P(program type | home-language group)`` pooled over
    all choices, but most schools only run general education, so using those
    shares directly as per-school probabilities over-picks GE. This fits a
    Luce weight per (group, type) by multiplicative updates until the shares
    implied by the synthetic availability sets match the released targets --
    the standard availability correction for a choice model whose alternatives
    differ across observations.

    Args:
        lists: Ranked school ids per student.
        groups: Home-language group per student.
        priors: The priors dict.
        targets: Share targets per group; defaults to the released
            ``program_by_hlgroup`` table.

    Returns:
        Fitted weights per group, keyed by program type.
    """
    offered = {
        int(k): v for k, v in priors["choice"]["school_program_types"].items()
    }
    by_group: dict[str, Counter] = defaultdict(Counter)
    for lst, group in zip(lists, groups):
        for school in lst:
            by_group[group][tuple(offered.get(school, ["GE"]))] += 1

    fitted = {}
    for group, target in (
        targets or priors["choice"]["program_by_hlgroup"]
    ).items():
        availability = by_group.get(group) or Counter()
        if not availability:
            fitted[group] = dict(target)
            continue
        total = sum(availability.values())
        weights = {t: max(float(p), 1e-9) for t, p in target.items()}
        for _ in range(PROGRAM_WEIGHT_ITERATIONS):
            share = Counter()
            for types, count in availability.items():
                pool = sum(weights.get(t, 0.0) for t in types)
                if pool <= 0:
                    continue
                for t in types:
                    share[t] += count * weights.get(t, 0.0) / pool
            for t in list(weights):
                achieved = share[t] / total
                if achieved > 0:
                    weights[t] *= float(target.get(t, 0.0)) / achieved
                elif float(target.get(t, 0.0)) > 0:
                    weights[t] *= 4.0
            norm = sum(weights.values())
            if norm > 0:
                weights = {t: w / norm for t, w in weights.items()}
        fitted[group] = weights
    return fitted


def assign_program_codes(
    lists: list[list[int]],
    groups: list[str],
    weights: dict[str, dict[str, float]],
    priors: dict,
    rng: np.random.Generator,
    rank1_weights: dict[str, dict[str, float]] | None = None,
) -> list[list[str]]:
    """Pick a program type for each ranked school.

    Args:
        lists: Ranked school ids per student.
        groups: Home-language group per student.
        weights: Fitted weights from :func:`fit_program_weights` (all ranks).
        priors: The priors dict.
        rng: Seeded generator.
        rank1_weights: Optional weights used only for list position 1, so the
            first-choice GE/pathway mix can track ``program_rank1_by_hlgroup``
            without retargeting the all-rank shares.

    Returns:
        Program types parallel to ``lists``.
    """
    offered = {
        int(k): v for k, v in priors["choice"]["school_program_types"].items()
    }
    out = []
    for lst, group in zip(lists, groups):
        table = weights.get(group, weights.get("EN", {}))
        head_table = (
            rank1_weights.get(group, rank1_weights.get("EN", table))
            if rank1_weights
            else table
        )
        codes = []
        for pos, school in enumerate(lst):
            use = head_table if pos == 0 else table
            allowed = offered.get(school, ["GE"])
            restricted = {t: use.get(t, 0.0) for t in allowed}
            if sum(restricted.values()) <= 0:
                restricted = {t: 1.0 for t in allowed}
            codes.append(draw(restricted, rng, default="GE"))
        out.append(codes)
    return out


def add_same_school_repeats(
    lists: list[list[int]],
    codes: list[list[str]],
    groups: list[str],
    weights: dict[str, dict[str, float]],
    lengths: np.ndarray,
    priors: dict,
    rng: np.random.Generator,
) -> tuple[list[list[int]], list[list[str]]]:
    """Let applicants rank a second program at a school they already ranked.

    Nearly a quarter of real applicants do this -- typically an immersion
    pathway and general education at the same school -- and 7% of all ranked
    choices are such a repeat. Repeats are inserted immediately after the first
    entry for that school, which is where 69% of real ones sit, and the list is
    then trimmed back to its drawn length.

    Args:
        lists: Ranked school ids per student, each school appearing once.
        codes: Program types parallel to ``lists``.
        groups: Home-language group per student.
        weights: Fitted weights from :func:`fit_program_weights`.
        lengths: Drawn total list length per student.
        priors: The priors dict.
        rng: Seeded generator.

    Returns:
        The lists and codes with repeats inserted and lengths trimmed.
    """
    offered = {
        int(k): v for k, v in priors["choice"]["school_program_types"].items()
    }
    p_repeat = float(priors["choice"].get("p_same_school_repeat", 0.0))
    if p_repeat <= 0:
        return lists, codes
    # p_repeat is a share of all choices; a repeat can only be added at a school
    # with a spare program, so scale it up by how often that is the case.
    eligible = sum(
        1
        for lst, row in zip(lists, codes)
        for school, code in zip(lst, row)
        if len(offered.get(school, [])) > 1
    )
    total = sum(len(lst) for lst in lists)
    if eligible == 0:
        return lists, codes
    p_per_choice = min(p_repeat * total / eligible, 1.0)

    out_lists, out_codes = [], []
    for i, (lst, row) in enumerate(zip(lists, codes)):
        schools, types = [], []
        for school, code in zip(lst, row):
            schools.append(school)
            types.append(code)
            spare = [t for t in offered.get(school, []) if t != code]
            if spare and rng.random() < p_per_choice:
                table = weights.get(groups[i], weights.get("EN", {}))
                restricted = {t: table.get(t, 0.0) for t in spare}
                if sum(restricted.values()) <= 0:
                    restricted = {t: 1.0 for t in spare}
                schools.append(school)
                types.append(draw(restricted, rng, default=spare[0]))
        limit = int(lengths[i])
        out_lists.append(schools[:limit])
        out_codes.append(types[:limit])
    return out_lists, out_codes


def calibrate_program_weights(
    lists: list[list[int]],
    groups: list[str],
    lengths: np.ndarray,
    priors: dict,
    seed: int,
) -> dict[str, dict[str, float]]:
    """Fit program-type weights that survive the same-school repeat pass.

    :func:`fit_program_weights` matches the released type shares on the
    one-entry-per-school lists, but the repeat pass then adds a *second*
    program at some schools, which shifts those shares. This wraps the fit in
    an outer loop that nudges the fit targets until the shares of the final,
    post-repeat lists match what was released.

    Args:
        lists: Ranked school ids per student, each school appearing once.
        groups: Home-language group per student.
        lengths: Drawn total list length per student.
        priors: The priors dict.
        seed: Seed for the trial draws.

    Returns:
        Fitted weights per group, keyed by program type.
    """
    released = priors["choice"]["program_by_hlgroup"]
    overall = Counter()
    for group, table in released.items():
        for program_type, share in table.items():
            overall[program_type] += share
    targets = {g: dict(t) for g, t in released.items()}
    weights = fit_program_weights(lists, groups, priors, targets)
    for _ in range(CODE_CALIBRATION_ITERATIONS):
        rng = np.random.default_rng(seed)
        codes = assign_program_codes(lists, groups, weights, priors, rng)
        _, final_codes = add_same_school_repeats(
            lists, codes, groups, weights, lengths, priors, rng
        )
        achieved = Counter(c for row in final_codes for c in row)
        total = sum(achieved.values())
        if not total:
            break
        for group, table in targets.items():
            for program_type in table:
                want = released[group].get(program_type, 0.0)
                got = achieved[program_type] / total
                reference = overall[program_type] / max(
                    sum(overall.values()), 1e-9
                )
                if got > 0 and reference > 0:
                    table[program_type] = want * (reference / got)
            norm = sum(table.values())
            if norm > 0:
                targets[group] = {t: v / norm for t, v in table.items()}
        weights = fit_program_weights(lists, groups, priors, targets)
    return weights


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
    # placed administratively at a school that still has space.
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
    *,
    profile: str = PROFILE_BASELINE,
) -> pd.DataFrame:
    """Build and write the synthetic dataset.

    Args:
        data_dir: Dataset root; holds ``priors/`` and ``reference/`` and
            receives the generated CSVs.
        year: Two-school-year tag, e.g. ``"2324"``.
        seed: Master seed; the output is a deterministic function of it.
        schools_csv: Schools table; defaults to ``<data_dir>/Cleaned/``.
        programs_csv: Programs table; defaults to ``<data_dir>/``.
        profile: ``baseline`` (today's independent race draw) or
            ``joint_frl_eth`` (race|FRL blend + rank-1 program codes).

    Returns:
        The generated student frame.
    """
    if profile not in VALID_PROFILES:
        raise ValueError(
            f"Unknown profile {profile!r}; expected one of {VALID_PROFILES}"
        )
    rng = np.random.default_rng(seed)
    with open(data_dir / "priors" / f"synthetic_priors_{year}.json") as handle:
        priors = json.load(handle)
    blocks = pd.read_csv(data_dir / "reference" / f"block_reference_{year}.csv")
    if "ctip_2013" in blocks.columns:
        raise ValueError(
            "block_reference still has ctip_2013; rebuild with "
            "extract_synthetic_priors.py so CTIP ships only as "
            f"reference/ctip_by_tract_{year}.csv"
        )
    ctip_path = data_dir / "reference" / f"ctip_by_tract_{year}.csv"
    if not ctip_path.is_file():
        raise FileNotFoundError(f"missing tract CTIP table: {ctip_path}")
    ctip_by_tract = pd.read_csv(ctip_path)
    schools = pd.read_csv(
        schools_csv or data_dir / "Cleaned" / f"schools_rehauled_{year}.csv"
    )
    programs = pd.read_csv(
        programs_csv or data_dir / f"programs_without_specialprogs_{year}.csv"
    )
    if "Unnamed: 0" in programs.columns:
        programs = programs.drop(columns=["Unnamed: 0"])
    # Older releases used the first column as a pandas index; recover program_id.
    if "program_id" not in programs.columns and programs.index.name in (
        None,
        "program_id",
        "Unnamed: 0",
    ):
        programs = programs.reset_index()
        if "program_id" not in programs.columns and "index" in programs.columns:
            programs = programs.rename(columns={"index": "program_id"})


    students = sample_locations(priors["students_per_aa"], blocks, rng)
    n = len(students)
    ctip_map = dict(
        zip(
            ctip_by_tract["Tract"].astype("int64"),
            ctip_by_tract["ctip1"].astype(float),
        )
    )
    students["ctip1"] = (
        students["census_tract"].astype("int64").map(ctip_map).fillna(0.0)
    )
    logger.info(
        "sampled %d synthetic households across %d attendance areas (profile=%s)",
        n,
        students["idschoolattendance"].nunique(),
        profile,
    )

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

    demographics = sample_demographics(students, priors, rng, profile=profile)
    for column in ("resolved_ethnicity", "homelang", "englprof", "sped"):
        students[column] = demographics[column]
    lengths = sample_lengths(students, priors, rng)

    tail = np.array(
        [
            float(priors["choice"]["school_pop_tail"].get(str(sid), 0.0))
            for sid in school_ids
        ]
    )
    floor = tail[tail > 0].min() * 0.05 if (tail > 0).any() else 1.0
    log_popularity = np.log(np.where(tail > 0, tail, floor))

    # --- first choices, then the rest of each list ------------------------
    head_beta = calibrate_first_choice_beta(
        students, lengths, priors, school_ids, distances, seed + 1
    )
    weights = first_choice_weights(
        students, priors, school_ids, distances, head_beta
    )
    keys = np.log(np.maximum(weights, 1e-300)) + rng.gumbel(
        0.0, 1.0, weights.shape
    )
    first_choice = [school_ids[j] for j in keys.argmax(axis=1)]

    priorities = sample_priorities(
        students, priors, school_ids, distances, head_beta, rng
    )
    heads: list[list[int]] = []
    for i in range(n):
        if lengths[i] <= 0:
            heads.append([])
            continue
        row = priorities.iloc[i]
        head: list[int] = []
        sibling = [s for s in row["sibling"] if s in index_of]
        if sibling and row["sibling_first"]:
            head.append(sibling[0])
        if first_choice[i] not in head:
            head.append(first_choice[i])
        if sibling and row["sibling_in_list"]:
            head.extend(s for s in sibling if s not in head)
        for school in (
            list(row["aaprek"]) + list(row["prek"]) + list(row["currentlp"])
        ):
            if school in index_of and school not in head:
                head.append(int(school))
        heads.append(head)
    # Forced priority schools can exceed the drawn length; keep them all rather
    # than dropping a priority the applicant is meant to hold.
    lengths = np.maximum(lengths, [len(h) for h in heads])

    # Each school can appear once in this stage; same-school repeats (an
    # immersion pathway plus general education, say) are added afterwards. The
    # cap also guarantees every stage has enough unpicked schools to draw from.
    unique_lengths = np.minimum(lengths, len(school_ids))
    betas = calibrate_betas(
        heads,
        unique_lengths,
        log_popularity,
        distances,
        school_ids,
        priors,
        seed + 2,
    )
    lists = build_lists(
        heads, unique_lengths, log_popularity, distances, betas, school_ids, rng
    )
    groups = [hl_group(x) for x in students["homelang"]]
    program_weights = calibrate_program_weights(
        lists, groups, lengths, priors, seed + 3
    )
    rank1_program_weights = None
    if (
        profile == PROFILE_JOINT_FRL_ETH
        and "program_rank1_by_hlgroup" in priors["choice"]
    ):
        # Fit first-choice pathway weights to the rank-1 table only.
        heads_only = [[lst[0]] for lst in lists if lst]
        head_groups = [g for g, lst in zip(groups, lists) if lst]
        rank1_program_weights = fit_program_weights(
            heads_only,
            head_groups,
            priors,
            targets=priors["choice"]["program_rank1_by_hlgroup"],
        )
    codes = assign_program_codes(
        lists,
        groups,
        program_weights,
        priors,
        rng,
        rank1_weights=rank1_program_weights,
    )
    lists, codes = add_same_school_repeats(
        lists, codes, groups, program_weights, lengths, priors, rng
    )

    # --- priority bookkeeping --------------------------------------------
    students["sibling"] = [
        [s for s in row if s in index_of] for row in priorities["sibling"]
    ]
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
    students["studentno"] = np.arange(1_000_000, 1_000_000 + n)
    students["grade"] = GRADE
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
    # Public release ships only syn-computed assignment/first-choice counts —
    # not r1_noenroll (unused by the simulator; was previously a placeholder).
    programs_out["r1_first_choice"] = [
        float(first_counts.get(str(p), 0)) for p in programs_out["program_id"]
    ]
    drop_cols = [
        c
        for c in programs_out.columns
        if c.startswith("Unnamed") or c == "r1_noenroll"
    ]
    if drop_cols:
        programs_out = programs_out.drop(columns=drop_cols)

    # The status-quo zone map is one zone per attendance area, which is fully
    # determined by the list of attendance-area schools.
    zones_dir = data_dir / "zones"
    zones_dir.mkdir(parents=True, exist_ok=True)
    zone_path = zones_dir / "concept1zones.csv"
    with open(zone_path, "w") as handle:
        for aa in sorted(int(a) for a in priors["students_per_aa"]):
            handle.write(f"{aa}\n")

    cleaned_dir = data_dir / "Cleaned"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    student_path = data_dir / f"student_{year}_synthetic.csv"
    programs_path = data_dir / f"programs_without_specialprogs_{year}.csv"
    students.to_csv(student_path, index=False)
    # Stable public schema: no pandas index column.
    out_cols = [
        c
        for c in [
            "program_id",
            "school_id",
            "program_type",
            "capacity",
            "programno",
            "r1_assigned",
            "r1_first_choice",
        ]
        if c in programs_out.columns
    ]
    programs_out[out_cols].to_csv(programs_path, index=False)
    if schools_csv is not None:
        schools.to_csv(
            cleaned_dir / f"schools_rehauled_{year}.csv", index=False
        )
    logger.info("wrote %s (%d rows)", student_path, len(students))
    logger.info("wrote %s (%d rows)", programs_path, len(programs_out))
    logger.info("wrote %s", zone_path)
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
    parser.add_argument(
        "--seed",
        type=int,
        default=PUBLIC_SEED,
        help="Public generation seed (default: the one used for the committed "
        "dataset). Unrelated to the private extraction noise seed.",
    )
    parser.add_argument("--schools-csv", type=Path, default=None)
    parser.add_argument("--programs-csv", type=Path, default=None)
    parser.add_argument(
        "--profile",
        choices=VALID_PROFILES,
        default=PROFILE_JOINT_FRL_ETH,
        help="joint_frl_eth = race|FRL blend + rank-1 program-type calibration "
        "(public release default); baseline = independent race draw.",
    )
    args = parser.parse_args()
    generate(
        args.data_dir,
        args.year,
        args.seed,
        args.schools_csv,
        args.programs_csv,
        profile=args.profile,
    )


if __name__ == "__main__":
    main()
