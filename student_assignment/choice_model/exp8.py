"""Utilities from the public SFUSD-Choice MNL model (the ``exp8`` specification).

This is a self-contained port of the feature construction in
``SFUSD-Choice-public/choice_model/data/features.py`` for the eight feature
groups of ``config_exp8.yaml``, together with the linear predictor that repo's
``Model._compute_estimates`` builds:

    u[student, program] = sum_k beta_k * x_k[student, program]

with ``-inf`` for programs outside the student's choice set. The coefficients
``beta`` come from the model's published ``weights.csv``; nothing is refitted
here.

The port exists so that the synthetic dataset's preference lists can be
generated from the choice model using only public inputs. It is checked against
the model's own output by
``scripts/generators/validate_choice_model_port.py``, which recomputes the
released ``estimates_2324.csv`` for the real cohort and diffs it; keep that
check passing when touching anything in this module.

Two deliberate quirks of the published specification are reproduced rather than
corrected, because the coefficients were fitted under them:

* ``PROGRAM_2_LANGS`` maps ``FB`` (and every ``XE`` type) to ``"XX"``, which no
  student's language code can equal, so ``lang_match_FB`` is structurally zero.
* ``HOME_LANG_2_CODE`` maps Korean to ``"KN"`` while ``PROGRAM_2_LANGS`` maps
  the ``KN`` program type to ``"KO"``, so Korean speakers never register a
  language match either. Japanese and Vietnamese are absent from
  ``HOME_LANG_2_CODE`` altogether and fall back to ``"EN"``.

Consequently ``lang_match`` is nonzero only for Cantonese, Mandarin and
Spanish speakers.
"""

import enum

import numpy as np
import pandas as pd

# --- Feature groups of config_exp8.yaml -------------------------------------
EXP8_FEATURES = (
    "sibling",
    "fixed_effect_schools",
    "fixed_effect_program_types",
    "prog_XE_x_English_x_ethn_match",
    "prog_XN_x_English",
    "lang_match_XB",
    "distance_indicator_lt_0_5",
    "distance_x_low_income",
)

# --- Constants mirrored from SFUSD-Choice-public/choice_model/data ----------
LOW_INCOME_THRESHOLD = 83_150

PROGRAM_TYPES = (
    "GE",
    "SE",
    "SN",
    "SB",
    "FB",
    "CB",
    "CE",
    "CN",
    "CT",
    "JE",
    "JN",
    "MN",
    "ME",
    "NC",
    "KN",
    "KE",
    "NS",
)

PROGRAM_2_LANGS = {
    "CE": "XX",
    "CB": "CC",
    "CN": "CC",
    "CT": "CC",
    "NS": "SP",
    "SB": "SP",
    "SE": "XX",
    "SN": "SP",
    "JB": "JA",
    "JE": "XX",
    "JN": "JA",
    "KE": "XX",
    "KN": "KO",
    "ME": "XX",
    "MN": "CM",
    "GE": "XX",
    "SA": "XX",
    "MS": "XX",
    "MM": "XX",
    "FB": "XX",
    "DT": "XX",
    "NC": "XX",
    "ED": "XX",
    "AF": "XX",
    "DA": "XX",
    "TC": "XX",
    "AO": "XX",
}

# Descriptive home-language label -> language code used by `lang_match`.
HOME_LANG_2_CODE = {
    "Cantonese": "CC",
    "Mandarin (Putonghua)": "CM",
    "Spanish": "SP",
    "Korean": "KN",
    "Italian": "IT",
    "Vietnamese": "IV",
    "English": "EN",
}

# The two-letter codes the assignment-side student files use, mapped through
# the same composition. Kept separate so either schema can be fed in.
HOME_LANG_CODE_2_CODE = {
    "CC": "CC",
    "CM": "CM",
    "SP": "SP",
    "KO": "KN",
    "IT": "IT",
    "IV": "IV",
    "EN": "EN",
}

# Program types a student's home language entitles them to rank.
HOME_LANG_2_PROG = {
    "CC-Chinese Cantonese": ["CN", "CB", "CT", "NC"],
    "CM-Chinese Mandarin": ["MN"],
    "SP-Spanish": ["SN", "SB", "NS"],
    "KO-Korean": ["KN"],
    "Cantonese": ["CN", "CB", "CT", "NC"],
    "Mandarin (Putonghua)": ["MN"],
    "Spanish": ["SN", "SB", "NS"],
    "Korean": ["KN"],
    "CC": ["CN", "CB", "CT", "NC"],
    "CM": ["MN"],
    "SP": ["SN", "SB", "NS"],
    "KO": ["KN"],
}

# Program types every student may rank regardless of home language.
ALWAYS_QUALIFIED = ("GE", "SE", "CE", "JE", "KE", "ME")

# Columns whose ranked program types widen the estimation-time choice set.
RANKED_TYPE_COLUMNS = ("r1_programs", "r2_programs", "r3_programs")

ENGLISH_LABELS = ("English", "EN-English", "EN")

ASIAN = (
    "Asian",
    "Chinese",
    "Vietnamese",
    "Filipino",
    "Japanese",
    "Korean",
    "Other Asian",
    "Cambodian",
)
HISPANIC = ("Hispanic/Latino", "'Hispanic/Latinx", "Hispanic")
WHITE = ("White",)
BLACK = ("Black or African American",)
OTHERS = (
    "Two or More Races",
    "American Indian or Alaskan Native",
    "Pacific Islander",
    "Asian Indian",
)

# Labels the assignment-side student files use that differ from the choice
# model's vocabulary. Anything unmapped falls through to "No Information",
# which is what the model does with an unrecognised label.
ETHNICITY_ALIASES = {
    "Multi-Racial": "Two or More Races",
    "Two or More": "Two or More Races",
    "Am. Indian/Alaskan": "American Indian or Alaskan Native",
    "Other Pacific Islander": "Pacific Islander",
    "Samoan": "Pacific Islander",
    "Laotian": "Other Asian",
    "Hmong": "Other Asian",
}

XE_PROGRAMS = ("CE", "SE", "JE", "ME", "KE")
XN_PROGRAMS = ("CN", "JN", "KN", "MN", "SN")
XB_PROGRAMS = ("CB", "FB", "SB")

# WGS84, matching geopy's geodesic default.
_WGS84_A = 6_378_137.0
_WGS84_F = 1 / 298.257223563
_METERS_PER_MILE = 1609.344


class ChoiceSetMode(enum.Enum):
    """Which choice-set rule to apply when masking ineligible programs.

    ``ESTIMATION`` reproduces the rule the published estimates were produced
    under: the always-qualified types, plus the types the student's home
    language entitles them to, **plus every type they were observed to rank in
    any round**, closed over language groups. That last term makes the choice
    set depend on the outcome, which is fine for fitting a likelihood but
    circular for generating preferences.

    ``FORWARD`` drops it, leaving only what a student is entitled to rank given
    their home language. Use it when generating lists.
    """

    ESTIMATION = "estimation"
    FORWARD = "forward"


def geodesic_miles(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    """Vectorised WGS84 geodesic distance in miles (Vincenty inverse).

    The choice model measures distance with ``geopy.distance.geodesic``, which
    solves the inverse geodesic problem on the WGS84 ellipsoid rather than
    treating the earth as a sphere. Haversine differs from it by a few tenths
    of a percent, which is enough to move points across the 0.5-mile boundary
    that ``distance_indicator_lt_0_5`` keys on, so the ellipsoidal distance is
    reproduced here. Vincenty's inverse formula agrees with geopy's Karney
    algorithm to well under a millimetre at city scale, and unlike geopy it
    vectorises.

    Args:
        lat1: Latitudes of the first points, in degrees.
        lon1: Longitudes of the first points, in degrees.
        lat2: Latitudes of the second points, in degrees.
        lon2: Longitudes of the second points, in degrees.

    Returns:
        Distances in miles, broadcast over the inputs.
    """
    lat1, lon1, lat2, lon2 = np.broadcast_arrays(
        np.asarray(lat1, dtype=float),
        np.asarray(lon1, dtype=float),
        np.asarray(lat2, dtype=float),
        np.asarray(lon2, dtype=float),
    )
    b = _WGS84_A * (1 - _WGS84_F)
    u1 = np.arctan((1 - _WGS84_F) * np.tan(np.radians(lat1)))
    u2 = np.arctan((1 - _WGS84_F) * np.tan(np.radians(lat2)))
    sin_u1, cos_u1 = np.sin(u1), np.cos(u1)
    sin_u2, cos_u2 = np.sin(u2), np.cos(u2)
    length = np.radians(lon2 - lon1)

    lam = length.copy()
    sin_sigma = cos_sigma = sigma = cos_2sm = cos_sq_alpha = None
    for _ in range(200):
        sin_lam, cos_lam = np.sin(lam), np.cos(lam)
        sin_sigma = np.sqrt(
            (cos_u2 * sin_lam) ** 2
            + (cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam) ** 2
        )
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = np.arctan2(sin_sigma, cos_sigma)
        # Coincident points leave sin_sigma at zero; the guard keeps the
        # intermediate quantities finite and the final distance lands at 0.
        safe_sin = np.where(sin_sigma == 0, 1.0, sin_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / safe_sin
        cos_sq_alpha = 1 - sin_alpha**2
        cos_2sm = np.where(
            cos_sq_alpha == 0,
            0.0,
            cos_sigma
            - 2
            * sin_u1
            * sin_u2
            / np.where(cos_sq_alpha == 0, 1.0, cos_sq_alpha),
        )
        c = (
            _WGS84_F
            / 16
            * cos_sq_alpha
            * (4 + _WGS84_F * (4 - 3 * cos_sq_alpha))
        )
        lam_prev = lam
        lam = length + (1 - c) * _WGS84_F * sin_alpha * (
            sigma
            + c * sin_sigma * (cos_2sm + c * cos_sigma * (-1 + 2 * cos_2sm**2))
        )
        if np.max(np.abs(lam - lam_prev)) < 1e-12:
            break

    u_sq = cos_sq_alpha * (_WGS84_A**2 - b**2) / (b**2)
    big_a = 1 + u_sq / 16384 * (
        4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq))
    )
    big_b = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    delta_sigma = (
        big_b
        * sin_sigma
        * (
            cos_2sm
            + big_b
            / 4
            * (
                cos_sigma * (-1 + 2 * cos_2sm**2)
                - big_b
                / 6
                * cos_2sm
                * (-3 + 4 * sin_sigma**2)
                * (-3 + 4 * cos_2sm**2)
            )
        )
    )
    return b * big_a * (sigma - delta_sigma) / _METERS_PER_MILE


def load_weights(path) -> pd.Series:
    """Read a model ``weights.csv`` into a feature -> coefficient series.

    Args:
        path: Path to the coefficient table.

    Returns:
        Coefficients indexed by feature name.
    """
    weights = pd.read_csv(path)
    return weights.set_index("feature")["coefficient"].astype(float)


def _ethnic_group(label) -> str:
    """Map a reported ethnicity to the model's coarse group."""
    if not isinstance(label, str):
        return "No Information"
    label = ETHNICITY_ALIASES.get(label, label)
    if label in ASIAN:
        return "Asian"
    if label in HISPANIC:
        return "Hispanic"
    if label in BLACK:
        return "Black"
    if label in WHITE:
        return "White"
    if label in OTHERS:
        return "Others"
    return "No Information"


def _language_code(label) -> str:
    """Map a home-language label (descriptive or two-letter) to its code."""
    if not isinstance(label, str):
        return "EN"
    if label in HOME_LANG_2_CODE:
        return HOME_LANG_2_CODE[label]
    return HOME_LANG_CODE_2_CODE.get(label, "EN")


def _parse_school_list(value) -> list[int]:
    """Parse a stringified list of school ids, tolerating blanks."""
    if isinstance(value, list):
        return [int(x) for x in value]
    if not isinstance(value, str) or value.strip() in ("", "[]", "nan"):
        return []
    out = []
    for part in value.strip()[1:-1].split(","):
        part = part.strip().strip("'\"")
        if part:
            try:
                out.append(int(float(part)))
            except ValueError:
                continue
    return out


def _parse_type_list(value) -> list[str]:
    """Parse a stringified list of program-type codes."""
    if isinstance(value, list):
        return [str(x) for x in value]
    if not isinstance(value, str) or value.strip() in ("", "[]", "nan"):
        return []
    return [
        part.strip().strip("'\"")
        for part in value.strip()[1:-1].split(",")
        if part.strip().strip("'\"")
    ]


def _qualified_types(
    home_lang, ranked_types: list[str], mode: ChoiceSetMode
) -> set[str]:
    """Program types a student may rank, under the requested rule."""
    qualified = set(ALWAYS_QUALIFIED)
    if mode is ChoiceSetMode.ESTIMATION:
        qualified.update(ranked_types)
    if isinstance(home_lang, str) and home_lang in HOME_LANG_2_PROG:
        qualified.update(HOME_LANG_2_PROG[home_lang])
    # Ranking one type of a language group opens the whole group.
    for group in HOME_LANG_2_PROG.values():
        if qualified.intersection(group):
            qualified.update(group)
    qualified.discard("")
    return qualified


def compute_utilities(
    students: pd.DataFrame,
    programs: pd.DataFrame,
    schools: pd.DataFrame,
    weights: pd.Series,
    mode: ChoiceSetMode = ChoiceSetMode.FORWARD,
    grade: str = "KG",
) -> pd.DataFrame:
    """Build the student x program utility matrix for the exp8 model.

    Accumulates ``beta_k * x_k`` straight into the ``(n_students,
    n_programs)`` result rather than materialising the full feature tensor,
    which for a full cohort would be tens of gigabytes.

    Args:
        students: One row per student, indexed arbitrarily, with columns
            ``studentno``, ``latitude``, ``longitude``, ``homelang``,
            ``resolved_ethnicity``, ``median_hh_income``, ``sibling`` and --
            only for :attr:`ChoiceSetMode.ESTIMATION` -- whichever of
            ``r1_programs`` / ``r2_programs`` / ``r3_programs`` exist.
        programs: Programs table with ``program_id``, ``school_id`` and
            ``program_type``.
        schools: Schools table with ``school_id``, ``lat`` and ``lon``.
        weights: Coefficients from :func:`load_weights`.
        mode: Choice-set rule; see :class:`ChoiceSetMode`.
        grade: Grade tag used in program ids.

    Returns:
        Utilities indexed by ``studentno`` with one column per ``program_id``,
        ``-inf`` where the program is outside the student's choice set.
    """
    programs = programs.reset_index(drop=True)
    program_ids = programs["program_id"].astype(str).tolist()
    program_school = programs["school_id"].astype(int).to_numpy()
    program_type = programs["program_type"].astype(str).to_numpy()
    n, p = len(students), len(program_ids)
    u = np.zeros((n, p), dtype=float)

    def coef(name: str) -> float:
        return float(weights.get(name, 0.0))

    # --- distance -------------------------------------------------------
    school_ll = schools.dropna(subset=["lat", "lon"]).set_index("school_id")
    prog_lat = np.array(
        [school_ll["lat"].get(s, np.nan) for s in program_school],
        dtype=float,
    )
    prog_lon = np.array(
        [school_ll["lon"].get(s, np.nan) for s in program_school],
        dtype=float,
    )
    distance = geodesic_miles(
        students["latitude"].to_numpy(dtype=float)[:, None],
        students["longitude"].to_numpy(dtype=float)[:, None],
        prog_lat[None, :],
        prog_lon[None, :],
    )
    # A student with no coordinates gets no distance information at all: the
    # model leaves their distance missing, so `distance <= 0.5` is False and
    # the continuous term drops out. Filling the distance with zero instead
    # would wrongly fire the within-half-a-mile indicator for every program.
    known = np.isfinite(distance)
    distance = np.where(known, distance, 0.0)

    u += coef("distance_indicator_lt_0_5") * (known & (distance <= 0.5))

    income = pd.to_numeric(students["median_hh_income"], errors="coerce")
    low_income = (income <= LOW_INCOME_THRESHOLD).to_numpy()
    u += np.where(
        low_income[:, None],
        coef("distance_x_low_income1") * distance,
        coef("distance_x_low_income0") * distance,
    )

    # --- school and program-type fixed effects --------------------------
    school_coef = np.array(
        [coef(f"school_{s}") for s in program_school], dtype=float
    )
    type_coef = np.array(
        [coef(f"program_type_{t}") for t in program_type], dtype=float
    )
    u += (school_coef + type_coef)[None, :]

    # --- sibling --------------------------------------------------------
    school_to_columns: dict[int, list[int]] = {}
    for j, school in enumerate(program_school):
        school_to_columns.setdefault(int(school), []).append(j)
    sibling_coef = coef("sibling")
    if sibling_coef and "sibling" in students.columns:
        for i, raw in enumerate(students["sibling"].to_numpy()):
            for school in _parse_school_list(raw):
                for j in school_to_columns.get(school, ()):
                    u[i, j] += sibling_coef

    # --- language and ethnicity interactions ----------------------------
    groups = np.array(
        [_ethnic_group(x) for x in students["resolved_ethnicity"]], dtype=object
    )
    is_hispanic = (groups == "Hispanic")[:, None]
    is_asian = (groups == "Asian")[:, None]
    home_lang = students["homelang"].to_numpy()
    is_english = np.array(
        [isinstance(x, str) and x in ENGLISH_LABELS for x in home_lang]
    )[:, None]
    lang_code = np.array([_language_code(x) for x in home_lang], dtype=object)
    program_lang = np.array(
        [PROGRAM_2_LANGS.get(t, "XX") for t in program_type], dtype=object
    )
    lang_match = (lang_code[:, None] == program_lang[None, :]).astype(float)

    for xe in XE_PROGRAMS:
        is_xe = (program_type == xe)[None, :]
        # SE keys off Hispanic identity, the other XE types off Asian.
        matched = is_hispanic if xe == "SE" else is_asian
        base = is_xe & is_english
        u += coef(f"prog_{xe}_x_English_x_ethn_match0") * (base & ~matched)
        u += coef(f"prog_{xe}_x_English_x_ethn_match1") * (base & matched)

    is_xn = np.isin(program_type, XN_PROGRAMS)[None, :]
    u += coef("prog_XN_x_English") * (is_xn & is_english)

    is_xb = np.isin(program_type, XB_PROGRAMS)
    for xb in XB_PROGRAMS:
        u += (
            coef(f"lang_match_{xb}")
            * lang_match
            * (program_type == xb)[None, :]
        )
    u += coef("lang_match_not_XB") * lang_match * (~is_xb)[None, :]

    # --- choice-set mask ------------------------------------------------
    ranked_columns = [
        students[c].to_numpy()
        for c in RANKED_TYPE_COLUMNS
        if c in students.columns
    ]
    for i in range(n):
        ranked_types: list[str] = []
        if mode is ChoiceSetMode.ESTIMATION:
            for column in ranked_columns:
                ranked_types.extend(_parse_type_list(column[i]))
        qualified = _qualified_types(home_lang[i], ranked_types, mode)
        ineligible = ~np.isin(program_type, list(qualified))
        u[i, ineligible] = -np.inf

    index = pd.Index(students["studentno"].to_numpy(), name="studentno")
    return pd.DataFrame(u, index=index, columns=program_ids)
