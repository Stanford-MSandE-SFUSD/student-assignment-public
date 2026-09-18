# SI Appendix — reproduction map

Maps **Supplementary Information (SI)** figures/tables to code and configs in
this repo and
`[SFUSD-Choice-public](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public)`.

**Main-text path:** see README [Paper quickstart](../README.md#paper-quickstart).  
**Metric key ↔ paper row names:** [PAPER_METRICS.md](PAPER_METRICS.md).

Confidential SFUSD microdata and student-level `estimates_*.csv` are **not** in
this public clone. Coefficient files (`weights.csv`) may be shared; regenerate
estimates on synthetic or authorized local data.

---

## Robustness Checks: Choice Models and Policy Configurations

Paper / table labels ↔ config and file ids used to reproduce each policy configuration.  
(For outcome-metric keys, see [PAPER_METRICS.md](PAPER_METRICS.md).)

### Choice models (A / B / C)


| Paper                   | Internal id | Typical estimates / weights stem                                       |
| ----------------------- | ----------- | ---------------------------------------------------------------------- |
| **Model A** (main text) | **t14**     | e.g. `t14_2223_k1_prog_gesplit` → `estimates_2324.csv` / `weights.csv` |
| **Model B**             | **t17**     | SI policy tables                                                       |
| **Model C**             | **t9**      | SI policy tables                                                       |


Train year for main Table 1: **2022–23**; simulate **2023–24** KG R1
(`r1_filter_student_without_specialprogs_2324.csv`), 25 iterations,
`list-length: 0.8*round(real_length)`.

### Zones (main Fig. zones)


| Paper                                     | Zone id (config / backend) | Example CSV under `data/zones/` |
| ----------------------------------------- | -------------------------- | ------------------------------- |
| **Small Zones (a)** — **main-text Small** | `13-0.25-2500_BG`          | `table1/13-0.25-2500_BG.csv`    |
| Small Zones (b) — additional small        | `10-0.15-2250_BG`          | `table1/10-0.15-2250_BG.csv`    |
| **Medium Zones (c)** — main-text Medium   | `6-0.10-1430_BG`           | `table1/6-0.10-1430_BG.csv`     |


> **Do not use** legacy `small_zones+*.yaml` / `medium_zones+*.yaml` as the
> paper maps: those still point at `18zone_2` / `6zone-1`, which were used in earlier versions of the paper.  Prefer subconfigs keyed by the zone ids above (e.g. `13-0.25-2500_BG+no_reserves`,
> `6-0.10-1430_BG+reserves_05frl`), as in the Table 1–style runner.

### Reserves


| Paper               | Definition          | Config family                                                     |
| ------------------- | ------------------- | ----------------------------------------------------------------- |
| **Main text**       | FRL **>50% / ≤50%** | `*_05frl` (`percentile:50`, `[0.5, 0.5]`)                         |
| **Reserves A** (SI) | FRL **>60% / ≤60%** | `*_06frl` (`percentile:60`, `[0.6, 0.4]`)                         |
| **Reserves B** (SI) | Income **95,292**   | bare `*+reserves` (`median_hh_income`, `[95292]`, `[0.57, 0.43]`) |


### Distance priorities


| Paper                  | Bands                 | Config                                                       |
| ---------------------- | --------------------- | ------------------------------------------------------------ |
| **Main** Dist Priority | 0–0.5, 0.5–1, 1–2, 2+ | `distance_05_1_2+reserves_05frl` (`thresholds: [0.5, 1, 2]`) |
| **Dist A** (SI)        | 0–0.5, 0.5–1, 1+      | `distance_05_1+reserves_05frl` (`thresholds: [0.5, 1]`)      |
| **Dist B** (SI)        | 0–0.75, 0.75–2, 2+    | `distance_075_2+reserves_05frl` (`thresholds: [0.75, 2]`)    |


### Status Quo variants


| Config            | Meaning                                                                               |
| ----------------- | ------------------------------------------------------------------------------------- |
| `status_quo`      | Counterfactual DA under status-quo priorities (utilities on) — **Table 1 column**     |
| `status_quo_real` | Historical / real-match assignment for that year (not the main counterfactual column) |


---

## Main-text seven policies (Table 1)


| Paper column             | Subconfig / policy pattern       |
| ------------------------ | -------------------------------- |
| Status Quo               | `status_quo`                     |
| Small Zones              | `13-0.25-2500_BG+no_reserves`    |
| Small + Reserves         | `13-0.25-2500_BG+reserves_05frl` |
| Medium Zones             | `6-0.10-1430_BG+no_reserves`     |
| Medium + Reserves        | `6-0.10-1430_BG+reserves_05frl`  |
| Dist Priority + Reserves | `distance_05_1_2+reserves_05frl` |
| Status Quo + Reserves    | `status_quo+reserves_05frl`      |


Runner settings (typical): `grade: KG`, `year: 23`, `iterations: 0–25`,
`utility-model.enable: true`, Model A (`t14`) `estimate-path`,
`list-length: 0.8*round(real_length)`.

Committed config (paths are placeholders):
`[configs/paper/table1_config.yaml](../configs/paper/table1_config.yaml)`.
Zone keys point at `data/zones/table1/` (Small/Medium BG maps + `concept1zones.csv`
for Dist Priority).

---

## Zone map CSVs (geography only)

Census geography ids only (block-group / block FIPS, or attendance-area ids). 

Layout:

```
data/zones/
├── table1/                # curated keys for Table 1 DA policies
│   ├── 13-0.25-2500_BG.csv
│   ├── 6-0.10-1430_BG.csv
│   ├── 10-0.15-2250_BG.csv
│   └── concept1zones.csv  # Con1 for Dist Priority
├── Small1_2500__….csv     # paper-labeled maps (Theil-H / zone figures)
├── Medium_1430__….csv
├── Zones_*__….csv         # fig:indices background maps (_BG / _B)
```


| Path / pattern                                    | Role                                                                                                                                  |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `table1/`                                         | Paper DA keys + Con1 used by `configs/paper/table1_config.yaml` — see `[data/zones/table1/README.md](../data/zones/table1/README.md)` |
| `Small*__…` / `Medium*__…` / `Status_Quo_aa_B__…` | Named maps for Theil-H / labeled zone figures                                                                                         |
| `Zones_*__FRL_Dev_*__Objective_*_{BG,B}.csv`      | Main-text `**fig:indices**` zone-map points                                                                                           |


### Main-text `fig:indices` (spatial segregation indices)


| Piece               | Where                                                                                     |
| ------------------- | ----------------------------------------------------------------------------------------- |
| Zone maps (points)  | `data/zones/` (`Zones_*__…_{BG,B}.csv` and related)                                       |
| Plot code (private) | `Model_Analysis/Notebooks/policy_paper_eda_s26/` → **s03** (`plot_structural_D_frontier`) |


> The SI Pareto frontier (`zone_frontier_plot`) uses **simulation assignment
> CSVs** (`plot_simulation_frontier.py`), not these geography files alone.

---

## SI figures


| SI item                                | Primary code / config                                                                             | Notes                                                                            |
| -------------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Zone frontier (diversity vs proximity) | `scripts/analysis/plot_simulation_frontier.py`, `configs/custom_configs/simulation_frontier.yaml` | Background = many zone **sims**; labeled geography maps live under `data/zones/` |
| ROL length by ethnicity × CTIP         | Private: `Model_Analysis/Python_Scripts/PNAS_Revision_Scripts/table03b_preference_list_length.py` | Not yet in this public repo; uses cleaned KG R1 data                             |
| Choice-model first-choice validation   | **SFUSD-Choice-public**                                                                           | See that repo’s `docs/SI_APPENDIX.md`                                            |


---

## SI tables


| SI item                              | Primary code / config                                                              | Notes                                                                            |
| ------------------------------------ | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| MNL coeffs Models A/B/C              | Choice `weights.csv` for **t14 / t17 / t9**                                        | Locate/share weights; do not publish student-level estimates                     |
| List-length sensitivity (Status Quo) | Override `utility-model.list-length`; `analyze_trends.py`                          | real / 80% / 70% / 60% / 7 / 10                                                  |
| Policy × years (17–18→18–19, etc.)   | Model A features; alternate train/test `estimate-path`                             | `configs/robustness/years_`*                                                     |
| Policy × Model B / C                 | Same seven policies; **t17** / **t9** estimates                                    |                                                                                  |
| Model A + actual length / length 10  | Override `list-length`                                                             |                                                                                  |
| Popularity-adjusted lists            | `run_augmented_da.py`, `list_augmentation.py`                                      | Popular = >1.5 first-choice apps/seat; targeted = non-white in low-income tracts |
| Reserves A vs B                      | `*_06frl` vs bare `*+reserves`                                                     |                                                                                  |
| Dist A vs B                          | `distance_05_1+reserves_05frl` vs `distance_075_2+reserves_05frl`                  |                                                                                  |
| Theil decomp (zoned vs citywide)     | Evaluator Theil metrics; named maps `Small*__…` / `Medium*__…` under `data/zones/` |                                                                                  |


---

## Related private scripts (not in this public clone)

Under the private checkout:

`student-assignment/student-assignment/Model_Analysis/Python_Scripts/PNAS_Revision_Scripts/`


| Path                                           | Role                                                   |
| ---------------------------------------------- | ------------------------------------------------------ |
| `table03b_preference_list_length.py`           | ROL length × ethnicity × CTIP (SI fig)                 |
| `table01*_` … `table05_`*                      | Applicant / preference / assignment descriptive tables |
| `zones/` (source of public `data/zones/` CSVs) | Geography CSVs now copied publicly                     |
| `frl_definitions.md`                           | FRL definition notes aligned with evaluator            |
| `run_all.py`                                   | Batch runner for those tables                          |


Candidate follow-up: port descriptive SI table scripts (no confidential student
files).

---

## Useful commands

```bash
uv run python scripts/analysis/analyze_trends.py --config <analysis.yaml>

uv run python scripts/analysis/plot_simulation_frontier.py \
    --config configs/custom_configs/simulation_frontier.yaml

uv run python run_augmented_da.py --config-path <yaml>
```

---

## Related docs


| Doc                                    | Role                                |
| -------------------------------------- | ----------------------------------- |
| [PAPER_METRICS.md](PAPER_METRICS.md)   | Paper table rows ↔ code metric keys |
| [PIPELINE.md](PIPELINE.md)             | Clone → first real simulation       |
| [DATA_SETUP.md](DATA_SETUP.md)         | Paths and placeholder tokens        |
| [CONFIG_OPTIONS.md](CONFIG_OPTIONS.md) | Full config reference               |
| [ZONE_SETUP.md](ZONE_SETUP.md) | Zone CSV setup for simulation        |


