# Synthetic 2023–24 kindergarten cohort

A public, fully synthetic stand-in for the confidential SFUSD 2023–24 (`2324`)
kindergarten application data used in the paper’s Table 1 universe. It has the
schema the simulator and evaluator expect, contains no real applicant’s
location, attributes, or ranked list, and is the **only** public synthetic
cohort in this repository.

**Generator profile:** `joint_frl_eth`, variant `joint_v4_blend1` (n=3887).
Public generation seed `170261502658718873328289898402210487511`.

**Intended use:** directional / claim replication and code-path checks — policy
rankings, Results-style narratives, and SI robustness patterns. **Do not**
quote synthetic cells as the paper’s estimates, and do not treat absolute
segregation levels as faithful to the district.

**Read [ANONYMIZATION.md](ANONYMIZATION.md) before using or citing this
dataset.** [FIDELITY.md](FIDELITY.md) tabulates aggregate statistics against
the source extract. School ethnicity for public MNL utilities is documented in
[reference/CDE_SCHOOL_COMPOSITION.md](reference/CDE_SCHOOL_COMPOSITION.md).

## Contents

| Path | Rows | What it is |
| --- | --- | --- |
| `student_2324_synthetic.csv` | **3,887** | Synthetic cohort. Drop-in for Table‑1–style KG applicants (nonempty R1, no special programs in lists). |
| `programs_without_specialprogs_2324.csv` | 129 | Real program offerings and capacities; `r1_assigned` / `r1_first_choice` are recomputed from the synthetic cohort. |
| `Cleaned/schools_rehauled_2324.csv` | 72 | Real school-level reference table (names, coordinates, capacity floor, ratings). |
| `zones/concept1zones.csv` | 58 | Status-quo zone map: one zone per attendance area. Generated. |
| `reference/block_reference_2324.csv` | 7,319 | Public census-block geography (no student counts; no CTIP). |
| `reference/ctip_by_tract_2324.csv` | ~195 | Binary CTIP1 by census tract (joined in stage 2). |
| `reference/schools_composition_cde_public.csv` | 72 | CDE TK–5 ethnicity shares by school (public). |
| `reference/enrolled_cde_composition.csv` | — | Choice-compatible enrolled stand-in built from those shares. |
| `priors/synthetic_priors_2324.json` | — | Aggregate statistics the generator consumes (noised / suppressed / coarsened). With the two reference tables, everything the generator reads; see ANONYMIZATION.md for what is and is not noised. |

Mechanism / profile: **`joint_frl_eth`** (race blended with block FRL after
residence is known; rank‑1 program type calibrated).

## What this is good for

- Reproducing **policy rankings** and Results-style stories (diversity–proximity
  tradeoffs, reserves help, distance+reserves and status-quo+reserves preserving
  choice, etc.).
- Running the **public MNL path** (CDE school composition → utilities → DA).
- SI robustness **direction** (list length, Model B / t17, reserves A/B,
  distance A/B).

## What this is not

- A levels-faithful clone of paper Table 1 (diversity metrics such as B/W
  exposure, AALPI concentration, Theil are systematically lower than the paper).
- A complete SI archive (no Model C, popular-schools tables, or true 1819
  reruns in the public pack).

## Running the simulator (listed preferences)

`configs/custom_configs/status_quo_synthetic_2324.yaml` is a listed-preference
smoke config (`utility-model.enable: false`). Replace path tokens and run:

```bash
uv run python run_custom_config.py --config-path configs/custom_configs/status_quo_synthetic_2324.yaml
```

Point any config at this dataset with:

```yaml
paths:
  student-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/student_2324_synthetic.csv
  program-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/programs_without_specialprogs_2324.csv
  school-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/Cleaned/schools_rehauled_2324.csv
  sfusd: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/
  zone-files:
    Con1: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/zones/concept1zones.csv
```

Use `year: 23`, `grade: KG`. Soft paper guardrails use `guard-rails: 0`.

## Regenerating students (stage 2, public)

```bash
uv run python scripts/generators/generate_synthetic_dataset.py \
    --data-dir data/synthetic_2324 --year 2324 \
    --profile joint_frl_eth --seed 170261502658718873328289898402210487511
```

`--seed` defaults to that public seed (`PUBLIC_SEED` in the script), and the
output is byte-identical to the committed files given the committed priors and
references (`tests/test_synthetic_dataset.py` checks this). Rebuilding the
priors (stage 1) needs confidential access **and** the data custodians' private
noise seed, which is deliberately not published — see
[ANONYMIZATION.md](ANONYMIZATION.md).

## Estimating MNL utilities (public composition)

Paper weights live in SFUSD-Choice (`local_outputs/models/t14_2223_…`, etc.).
Rebuild utilities for **this** cohort with CDE school composition (not
confidential enrolled):

```bash
SFUSD_CHOICE_PATH=path/to/SFUSD-Choice-public \
    uv run python scripts/generate_syn_estimates_cde.py
```

Run from this repo's root. The script reads this pack and the enrolled
stand-in `reference/enrolled_cde_composition.csv` directly, and writes
estimates under `local-data/estimates_syn/mnl_cde/`. The calibrated weights
must already exist in that checkout's `local_outputs/models/`. Default Table 1
MNL uses Model A weights (`t14_2223`) and list length `0.8*round(real_length)`.
Model B uses `t17_2223`. See
[reference/CDE_SCHOOL_COMPOSITION.md](reference/CDE_SCHOOL_COMPOSITION.md).

## Relationship to `tests/fixtures/`

Fixtures under `tests/fixtures/` are tiny invented markets for fast CI. This
dataset is the one to use for analysis and replication demos.
