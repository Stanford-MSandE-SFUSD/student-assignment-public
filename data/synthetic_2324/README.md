# Synthetic 2023–24 kindergarten cohort

A public, fully synthetic stand-in for the confidential SFUSD 2023–24 (`2324`)
kindergarten application data. It has the schema the simulator and evaluator
expect, reproduces the cohort-level statistics the analysis depends on, and
contains no real applicant's location, attributes, or ranked list.

**Preference lists come from the published choice model.** Household features
are sampled from privacy-protected aggregates; the ranked lists are then a
Gumbel draw over the utilities the public `exp8` MNL assigns to those features.
Nothing about *what* applicants rank is calibrated to the observed lists, which
is both why the priors file is small and why the lists inherit the model's
accuracy — see "What is not reproduced".

**Read [ANONYMIZATION.md](ANONYMIZATION.md) before using or citing this
dataset.** It documents what real information the release does and does not
contain and, importantly, which analyses this data is *not* suitable for.
[FIDELITY.md](FIDELITY.md) tabulates 55 statistics side by side against the
source cohort.

## Contents

| Path | Rows | What it is |
| --- | --- | --- |
| `student_2324_synthetic.csv` | 4,308 | The synthetic cohort. Drop-in replacement for `student_2324.csv` / `student_2324_filtered.csv`. |
| `programs_without_specialprogs_2324.csv` | 129 | Real program offerings and capacities; the three `r1_*` outcome columns are recomputed from the synthetic cohort. |
| `Cleaned/schools_rehauled_2324.csv` | 72 | Real school-level reference table (names, coordinates, capacity floor, ratings). |
| `reference/block_reference_2324.csv` | 7,319 | Public census-block geography: block group, tract, ZIP, attendance area, CTIP 2013 designation, 2010 Census population, TIGER internal point, land area. |
| `choice_model/weights_exp8.csv` | 109 | The published MNL coefficients the preference lists are drawn from, plus `config_exp8.yaml`, its feature specification. |
| `choice_model/estimates_2324_synthetic.csv` | 4,308 × 129 | The utility matrix those coefficients imply for this cohort. Point `estimate-path` at it to run with `utility-model.enable: true`. |
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
- **Ranked lists.** Mean length 5.78 against 5.59; the same median of 5; 6.8%
  against 8.1% filing no list at all, and 15.4% against 15.0% filing ten or
  more choices.
- **School demand.** Any-rank share by school correlates at 0.97 across the 72
  schools. First choices are weaker, at 0.84 — that is the model's top-1
  accuracy showing through (see below).
- **Language pathways.** 75.9% of choices are general education against 76.3%,
  and 25.8% of applicants rank two programs at the same school against 25.4%.
  Both are emergent: the model ranks *programs*, so the immersion/general mix
  and the habit of ranking two pathways at one school are its predictions, not
  fitted quantities.
- **Choice geography.** Mean home-to-school distance rises with list position
  exactly as it does in the source (1.33 mi at the first choice to 2.10 mi
  beyond the eighth), though uniformly about 9% short — see below.
- **Block characteristics.** Mean and standard deviation of free-lunch
  probability, AALPI score, neighbourhood SES, home opportunity index, median
  household income, and the CTIP1 share.
- **Demographics.** Ethnicity shares within 0.041 total absolute deviation;
  home language within 0.055 and English proficiency within 0.030. The share of
  applicants in CTIP1 blocks matches by race (33.8% of AALPI applicants against
  34.1%).
- **Priorities.** Sibling (28.4% against 28.4%), attendance-area pre-K (4.4%
  against 3.8%), citywide pre-K (1.3% against 1.7%), and language pathway (3.9%
  against 3.9%).

## What is not reproduced

Summarised here; reasoned through in [ANONYMIZATION.md](ANONYMIZATION.md).

The first three items are all the same thing: the lists are the choice model's
predictions, so wherever the model is imperfect, this dataset inherits that
imperfection rather than papering over it. That is the deliberate trade for
having preferences derive from a public model instead of from calibrated
statistics about the real lists.

- **First-choice demand across schools is only moderately accurate**
  (correlation 0.84; the previous list-generation approach, calibrated directly
  to area-level first-choice tables, reached 0.94). The published model's own
  top-1 accuracy is about 0.44, and that ceiling propagates. Any-rank demand,
  which averages over the whole list, holds up much better at 0.97.
- **Choices are about 9% closer to home than in reality**, at every list
  position. The model weights proximity more heavily than the observed lists
  do; no correction is applied.
- **Siblings are followed too faithfully.** The sibling coefficient is 14.5
  against a Gumbel(0,1) shock, so an applicant with a sibling ranks that
  school first essentially always — 1.00 here against 0.92 in the source.

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

## Running the simulator on it

`configs/custom_configs/status_quo_synthetic_2324.yaml` is a working config.
Replace `<STUDENT_ASSIGNMENT_PATH>` with your absolute checkout path (the
convention used throughout `configs/`, see `docs/DATA_SETUP.md`) and run:

```bash
uv run python run_custom_config.py --config-path configs/custom_configs/status_quo_synthetic_2324.yaml
```

`status_quo_synthetic_2324_umodel.yaml` is the same run with
`utility-model.enable: true`, redrawing lists from the shipped utility matrix
each iteration instead of reading them off the dataset.

To point an existing config at this dataset instead, set:

```yaml
paths:
  student-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/student_2324_synthetic.csv
  program-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/programs_without_specialprogs_2324.csv
  school-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/Cleaned/schools_rehauled_2324.csv
  sfusd: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/
  estimate-path: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/choice_model/estimates_2324_synthetic.csv
  zone-files:
    Con1: <STUDENT_ASSIGNMENT_PATH>/data/zones/table1/concept1zones.csv
```

with `year: 23` and `grade: KG`. Both `utility-model.enable: false` (use the
dataset's lists) and `true` (redraw from the utility matrix) work.

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

## Relationship to `tests/fixtures/small_2223/`

`tests/fixtures/small_2223/` is a 200-row, 15-school, entirely invented fixture
whose only job is to make `tests/test_full_pipeline.py` run fast. It is not
calibrated to anything. This dataset is the one to use for analysis.

The status-quo zone map the configs above use, `Con1`, is the repository's
existing [`data/zones/table1/concept1zones.csv`](../zones/table1/concept1zones.csv)
— one zone per attendance area, geography only.
