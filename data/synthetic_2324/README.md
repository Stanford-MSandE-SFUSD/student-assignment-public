# Synthetic 2023–24 kindergarten cohort

A public, fully synthetic stand-in for the confidential SFUSD 2023–24 (`2324`)
kindergarten application data. It has the schema the simulator and evaluator
expect, reproduces the cohort-level statistics the analysis depends on, and
contains no real applicant's location, attributes, or ranked list.

**Read [ANONYMIZATION.md](ANONYMIZATION.md) before using or citing this
dataset.** It documents what real information the release does and does not
contain and, importantly, which analyses this data is *not* suitable for.
[FIDELITY.md](FIDELITY.md) tabulates 53 statistics side by side against the
source cohort.

## Contents

| Path | Rows | What it is |
| --- | --- | --- |
| `student_2324_synthetic.csv` | 4,308 | The synthetic cohort. Drop-in replacement for `student_2324.csv` / `student_2324_filtered.csv`. |
| `programs_without_specialprogs_2324.csv` | 129 | Real program offerings and capacities; the three `r1_*` outcome columns are recomputed from the synthetic cohort. |
| `Cleaned/schools_rehauled_2324.csv` | 72 | Real school-level reference table (names, coordinates, capacity floor, ratings). |
| `zones/concept1zones.csv` | 58 | Status-quo zone map: one zone per attendance area. Generated. |
| `reference/block_reference_2324.csv` | 7,319 | Public census-block geography: block group, tract, ZIP, attendance area, CTIP 2013 designation, 2010 Census population, TIGER internal point, land area. |
| `priors/synthetic_priors_2324.json` | — | Every aggregate statistic the generator consumes, each noised, suppressed, and/or coarsened. This file is the complete disclosure surface of the release. |

The three real files are school- and geography-level facts with no
applicant-level content; see the "What is in the release that is not synthetic"
table in [ANONYMIZATION.md](ANONYMIZATION.md) if a data agreement requires
removing them.

## What is reproduced

Headline agreement with the source cohort (full table in
[FIDELITY.md](FIDELITY.md)):

- **Cohort size and geography.** 4,308 applicants against 4,304, across the
  same 58 attendance areas; the per-area applicant count correlates at 0.995
  with the real one.
- **Ranked lists.** Mean length 5.62 against 5.59; the same median of 5; 6.8%
  against 8.1% filing no list at all, and 14.1% against 15.0% filing ten or
  more choices.
- **School demand.** First-choice share by school correlates at 0.94 across the
  72 schools; any-rank share at 0.96.
- **Language pathways.** 76.3% of choices are general education, matching the
  source exactly, and 26.5% of applicants rank two programs at the same school
  against 25.0%.
- **Choice geography.** Mean home-to-school distance matches within 0.07 mi at
  every list position, from 1.41 mi at the first choice to 2.25 mi beyond the
  eighth.
- **Block characteristics.** Mean and standard deviation of free-lunch
  probability, AALPI score, neighbourhood SES, home opportunity index, median
  household income, and the CTIP1 share.
- **Demographics.** Ethnicity shares within 0.034 total absolute deviation;
  home language and English proficiency within 0.10. The share of applicants in
  CTIP1 blocks matches by race (34.4% of AALPI applicants against 34.1%).
- **Priorities.** Sibling (28.9% against 28.4%), pre-K (3.9% against 3.8%),
  attendance-area, and language-pathway priority rates.

## What is not reproduced

Summarised here; reasoned through in [ANONYMIZATION.md](ANONYMIZATION.md).

- **Absolute segregation magnitudes are compressed.** The gap in mean block
  free-lunch probability between AALPI and other applicants is 0.15 here
  against 0.19 in the source — about 80% of the real gradient. Use
  this dataset to compare policies, not to report levels of segregation.
- **Block-level attribute geography is synthetic.** Socio-economic attributes
  are real at the census block group level; variation *within* a block group is
  noise.
- **Rare demographic groups are placed citywide**, not by area.
- **List structure beyond popularity, distance and same-school pairs is not
  modeled** — no idiosyncratic substitution patterns between specific schools.
- **Rounds 2 and 4 are not modeled.** `r2_*` columns are present and empty;
  `r4_*` columns are dropped, so the loader sees two rounds.
- **No choice-model utility matrix is shipped.** Runs with
  `utility-model.enable: false` work out of the box; `true` needs an
  `estimates_2324.csv` estimated for this cohort.

## Running the simulator on it

`configs/custom_configs/status_quo_synthetic_2324.yaml` is a working config.
Replace `<STUDENT_ASSIGNMENT_PATH>` with your absolute checkout path (the
convention used throughout `configs/`, see `docs/DATA_SETUP.md`) and run:

```bash
uv run python run_custom_config.py --config-path configs/custom_configs/status_quo_synthetic_2324.yaml
```

To point an existing config at this dataset instead, set:

```yaml
paths:
  student-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/student_2324_synthetic.csv
  program-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/programs_without_specialprogs_2324.csv
  school-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/Cleaned/schools_rehauled_2324.csv
  sfusd: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/
  zone-files:
    Con1: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/zones/concept1zones.csv
```

with `year: 23`, `grade: KG`, and `utility-model.enable: false`.

## Regenerating

```bash
uv run python scripts/generators/generate_synthetic_dataset.py \
    --data-dir data/synthetic_2324 --year 2324
```

Output is a deterministic function of the committed priors, the committed block
reference, and `--seed` (default `20260917`). Pass a different seed to draw an
independent cohort — useful for checking that a result is not an artifact of one
synthetic draw.

Rebuilding the priors from the confidential data needs
`scripts/generators/extract_synthetic_priors.py` and data access; see
[ANONYMIZATION.md](ANONYMIZATION.md).

## Relationship to `tests/fixtures/fake_2223/`

`tests/fixtures/fake_2223/` is a 200-row, 15-school, entirely invented fixture
whose only job is to make `tests/test_full_pipeline.py` run fast. It is not
calibrated to anything. This dataset is the one to use for analysis.
