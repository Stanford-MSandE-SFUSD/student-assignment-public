"""Build public school ethnicity composition + Choice enrolled stand-in (Step 4).

Uses CDE Census Day Enrollment (public). Default file: CDEnroll2324
(2023–24) because the historical 2022–23 download is not currently
reachable from this environment. Documented caveat: composition year is
same-year as the synthetic cohort, not prior-year 2223.

Outputs (public-safe, under student-assignment-public/local-data/):
  - synthetic_2324/reference/schools_composition_cde_public.csv
  - synthetic_2324/reference/enrolled_cde_composition.csv  (Choice-compatible)
  - synthetic_2324/reference/CDE_SCHOOL_COMPOSITION.md

Does not read confidential cleaned student files.
"""

from __future__ import annotations

import re
import os
from pathlib import Path

import pandas as pd

# Repo root (this file lives in scripts/). Override output pack with SYN_DIR.
PUB = Path(__file__).resolve().parents[1]
SYN = Path(os.environ.get("SYN_DIR", str(PUB / "data" / "synthetic_2324")))
REF = SYN / "reference"
CDE_PATH = Path(os.environ.get("CDE_PATH", str(REF / "cdenroll2324.txt")))
SCHOOLS = SYN / "Cleaned" / "schools_rehauled_2324.csv"

OUT_COMP = REF / "schools_composition_cde_public.csv"
OUT_ENR = REF / "enrolled_cde_composition.csv"
OUT_DOC = REF / "CDE_SCHOOL_COMPOSITION.md"

# CDE ReportingCategory → (model ethn group, AALPI score 0/1)
RACE_MAP = {
    "RE_B": ("black", 1),  # African American
    "RE_H": ("hispanic", 1),  # Hispanic/Latino
    "RE_P": ("others", 1),  # Pacific Islander → others bin, AALPI
    "RE_I": ("others", 1),  # American Indian → others, treat as AALPI-ish
    "RE_A": ("asian", 0),  # Asian
    "RE_F": ("asian", 0),  # Filipino → asian (coarser model bins)
    "RE_W": ("white", 0),
    "RE_T": ("others", 0),  # Two or more
    "RE_D": ("others", 0),  # Decline / not reported
}

GRADE_COLS = ["GR_TK", "GR_KN", "GR_01", "GR_02", "GR_03", "GR_04", "GR_05"]

# Manual CDS overrides when name match fails
MANUAL_CDS = {
    625: "6093496",  # Carver (George Washington) Elementary
    493: "6093488",  # San Francisco Community Alternative
}


def norm_name(s: str) -> str:
    s = str(s).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    for w in [
        "ELEMENTARY",
        "SCHOOL",
        "ES",
        "ACADEMY",
        "THE",
        "OF",
        "AND",
        "PK",
        "TK",
        "K",
        "8",
        "5",
    ]:
        s = re.sub(rf"\b{w}\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_sfusd_cde(path: Path) -> pd.DataFrame:
    chunks = []
    for ch in pd.read_csv(path, sep="\t", encoding="latin1", dtype=str, chunksize=200_000):
        m = (
            (ch["CountyCode"] == "38")
            & (ch["DistrictCode"] == "68478")
            & (ch["AggregateLevel"] == "S")
            & (ch["SchoolCode"] != "0000000")
        )
        chunks.append(ch.loc[m])
    sf = pd.concat(chunks, ignore_index=True)
    for c in GRADE_COLS + ["TOTAL_ENR"]:
        sf[c] = pd.to_numeric(sf[c], errors="coerce").fillna(0)
    sf["tk5"] = sf[GRADE_COLS].sum(axis=1)
    return sf


def match_schools(sch: pd.DataFrame, cde_names: pd.DataFrame) -> dict[int, str]:
    """school_id -> SchoolCode"""
    cde_names = cde_names.copy()
    cde_names["norm"] = cde_names["SchoolName"].map(norm_name)
    out: dict[int, str] = {}
    for _, row in sch.iterrows():
        sid = int(row.school_id)
        if sid in MANUAL_CDS:
            out[sid] = MANUAL_CDS[sid]
            continue
        for key in (norm_name(row.school_name_long), norm_name(row.school_name)):
            hits = cde_names[cde_names["norm"] == key]
            if len(hits) == 1:
                out[sid] = str(hits.iloc[0].SchoolCode)
                break
            toks = [t for t in key.split() if len(t) > 3]
            found = False
            for t in toks[:3]:
                cand = cde_names[
                    cde_names["norm"].str.contains(rf"\b{re.escape(t)}\b", na=False)
                ]
                if len(cand) == 1:
                    out[sid] = str(cand.iloc[0].SchoolCode)
                    found = True
                    break
            if found:
                break
    return out


def main() -> None:
    if not CDE_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CDE_PATH}. Download CDEnroll2324 from "
            "https://www.cde.ca.gov/ds/ad/filesenrcensus.asp"
        )

    sf = load_sfusd_cde(CDE_PATH)
    sch = pd.read_csv(SCHOOLS)
    names = sf[["SchoolCode", "SchoolName"]].drop_duplicates()
    sid2cds = match_schools(sch, names)
    missing = sorted(set(sch.school_id.astype(int)) - set(sid2cds))
    if missing:
        raise RuntimeError(f"Unmatched school_ids: {missing}")

    race = sf[sf.ReportingCategory.isin(RACE_MAP)].copy()
    rows = []
    enrolled_rows = []
    eid = 9_000_000

    for sid, cds in sid2cds.items():
        sub = race[race.SchoolCode == cds]
        school_name = names.loc[names.SchoolCode == cds, "SchoolName"].iloc[0]
        counts = {g: 0 for g in ["black", "white", "asian", "hispanic", "others"]}
        aalpi_num = 0
        total = 0
        for _, r in sub.iterrows():
            group, aalpi = RACE_MAP[r.ReportingCategory]
            n = int(r.tk5)
            if n <= 0:
                continue
            counts[group] += n
            aalpi_num += aalpi * n
            total += n
            # Expand into Choice enrolled-like rows (ethnicity only;
            # FRL/income left neutral so school_pct_frl / low_income → 0).
            for _ in range(n):
                enrolled_rows.append(
                    {
                        "enrolled_idschool": sid,
                        "resolved_ethnicity": {
                            "black": "Black or African American",
                            "white": "White",
                            "asian": "Chinese",
                            "hispanic": "Hispanic/Latino",
                            "others": "Two or More Races",
                        }[group],
                        "AALPI Score": float(aalpi),
                        "freelunch_prob": 0.0,
                        "reducedlunch_prob": 0.0,
                        # Above LOW_INCOME_THRESHOLD (83150) → not low-income
                        "median_hh_income": 120000.0,
                    }
                )
                eid += 1

        if total == 0:
            # Still emit a composition row of zeros
            rows.append(
                {
                    "school_id": sid,
                    "cds_school_code": cds,
                    "cde_school_name": school_name,
                    "tk5_n": 0,
                    "pct_black": 0.0,
                    "pct_white": 0.0,
                    "pct_asian": 0.0,
                    "pct_hispanic": 0.0,
                    "pct_others": 0.0,
                    "pct_aalpi": 0.0,
                    "source": "CDE CDEnroll2324 TK-5",
                }
            )
            continue

        rows.append(
            {
                "school_id": sid,
                "cds_school_code": cds,
                "cde_school_name": school_name,
                "tk5_n": total,
                "pct_black": counts["black"] / total,
                "pct_white": counts["white"] / total,
                "pct_asian": counts["asian"] / total,
                "pct_hispanic": counts["hispanic"] / total,
                "pct_others": counts["others"] / total,
                "pct_aalpi": aalpi_num / total,
                "source": "CDE CDEnroll2324 TK-5",
            }
        )

    comp = pd.DataFrame(rows).sort_values("school_id")
    enr = pd.DataFrame(enrolled_rows)
    REF.mkdir(parents=True, exist_ok=True)
    comp.to_csv(OUT_COMP, index=False)
    enr.to_csv(OUT_ENR, index=False)

    OUT_DOC.write_text(
        f"""# Public school composition from CDE (for MNL utilities)

## Source
- CDE Census Day Enrollment file `CDEnroll2324` (2023–24), district SFUSD.
- Local copy: `{CDE_PATH.name}` (gitignored under `local-data/`).
- Download: https://www.cde.ca.gov/ds/ad/filesenrcensus.asp

## Caveats
- **Year:** Used 2023–24 public census (reachable download). Ideal prior year
  for a 2324 simulation is 2022–23; treat as same-year public proxy.
- **Grades:** TK–5 sum (`GR_TK`…`GR_05`), not KG-only.
- **School-level** (not program-level).
- **Race mapping** into model bins:
  - Black ← RE_B; Hispanic ← RE_H; White ← RE_W
  - Asian ← RE_A + RE_F (Filipino folded into Asian)
  - Others ← RE_P, RE_I, RE_T, RE_D
  - AALPI score 1 for RE_B, RE_H, RE_P, RE_I
- **FRL / income:** Not filled from public FRPM here. Pseudo-enrolled rows use
  `freelunch_prob=0` and high `median_hh_income`, so Choice
  `school_pct_frl` / `school_pct_low_income` are **0**. Ethnicity shares and
  `school_pct_aalpi` / `school_homophily` are the intended public signal.

## Outputs
- `{OUT_COMP.name}` — one row per `school_id` with TK–5 ethnicity shares
- `{OUT_ENR.name}` — expanded Choice-compatible enrolled stand-in
  ({len(enr)} rows)

## Coverage
- Matched {len(sid2cds)} / {len(sch)} schools (manual CDS for Carver 625,
  SF Community 493).
""",
        encoding="utf-8",
    )
    print(f"Wrote {OUT_COMP} ({len(comp)} schools)")
    print(f"Wrote {OUT_ENR} ({len(enr)} rows)")
    print(f"Wrote {OUT_DOC}")


if __name__ == "__main__":
    main()
