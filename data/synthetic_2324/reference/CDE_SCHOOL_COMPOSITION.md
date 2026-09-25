# Public school composition from CDE (for MNL utilities)

How school ethnicity features are built when regenerating choice-model
utilities without confidential prior-year enrollment.

## Source

- California Department of Education (CDE) Census Day Enrollment file
  `CDEnroll2324` (2023–24), district SFUSD.
- Download: https://www.cde.ca.gov/ds/ad/filesenrcensus.asp
- The raw statewide extract is **not** shipped here; only the SFUSD school
  aggregates derived from it.

## Caveats

- **Year:** 2023–24 public census. Ideal prior year for a 2324 simulation is
  2022–23; treat this as a same-year public proxy.
- **Grades:** TK–5 sum (`GR_TK` … `GR_05`), not kindergarten-only.
- **School-level** (not program-level).
- **Race mapping** into the choice-model bins:
  - Black ← RE_B; Hispanic ← RE_H; White ← RE_W
  - Asian ← RE_A + RE_F (Filipino folded into Asian)
  - Others ← RE_P, RE_I, RE_T, RE_D
  - AALPI score 1 for RE_B, RE_H, RE_P, RE_I
- **FRL / income:** Not filled from public FRPM. The Choice-compatible
  enrolled stand-in uses `freelunch_prob=0` and high `median_hh_income`, so
  `school_pct_frl` / `school_pct_low_income` are **0**. Ethnicity shares and
  `school_pct_aalpi` / `school_homophily` are the intended public signal.

## Files in this folder

| File | What it is |
| --- | --- |
| `schools_composition_cde_public.csv` | One row per `school_id` with TK–5 ethnicity shares |
| `enrolled_cde_composition.csv` | Expanded Choice-compatible enrolled stand-in (ethnicity only) |
| `CDE_SCHOOL_COMPOSITION.md` | This note |

## Coverage

Matched 72 / 72 schools in `Cleaned/schools_rehauled_2324.csv` (manual CDS
codes for Carver 625 and SF Community 493).
