# Student Assignment Simulator

Simulation tools for the **San Francisco Unified School District (SFUSD)**
school-choice system. The simulator runs Deferred Acceptance (and variants)
under different zone, priority, and tie-breaking policies, then compares a
**Status Quo** baseline against these policy variatnces on choice attainment (top-k),   
travel distance, and equity (racial / socioeconomic composition).



**Companion repo:** choice-model training and `estimates_*.csv` live in
`[SFUSD-Choice-public](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public)`.
Point `<SFUSD_CHOICE_PATH>` at that checkout (see [Data setup](#data-setup)).

### How to navigate this repo


| Track                 | Start here                                                                                      |
| --------------------- | ----------------------------------------------------------------------------------------------- |
| **Newcomer / CI**     | [Quick start](#quick-start) — `pytest` on the committed small dataset                           |
| **Paper (main text)** | [Paper quickstart](#paper-quickstart) — DA policies → metrics table                             |
| **SI Appendix**       | **[docs/SI_APPENDIX.md](docs/SI_APPENDIX.md)** — robustness, frontiers, list augmentation, etc. |
| **Full setup**        | [docs/PIPELINE.md](docs/PIPELINE.md), [docs/DATA_SETUP.md](docs/DATA_SETUP.md)                  |


Real SFUSD microdata are governed by a DUA and are **not** in this public clone.
A bare clone still runs tests and the fake-data pipeline.

---

## Requirements

- **Python 3.10+** (pinned to 3.10 via `[.python-version](.python-version)`;
`uv` installs a matching interpreter for you).
- **[uv](https://docs.astral.sh/uv/)** for dependency management.

## Installing uv

`uv` is a single static binary — no root required.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# or via pip / pipx / Homebrew
pip install uv     #  •  pipx install uv  •  brew install uv
```

The installer adds `~/.local/bin` to your `PATH`; restart your shell (or
`source ~/.bashrc`) if `uv` is not found.

## Installation

From a fresh clone, **one command** provisions the exact pinned environment
(Python interpreter included) from the tracked `pyproject.toml` + `uv.lock`:

```bash
git clone <repo> && cd student-assignment-public
uv sync
```

This creates a `.venv/` with every locked dependency. Run project commands with
`uv run <cmd>` (no activation needed), or `source .venv/bin/activate` for a
classic shell.

## Quick start

```bash
# Run the test suite — including the end-to-end pipeline on the committed
# small dataset. Works on a bare clone, with no confidential data.
uv run python -m pytest tests -q

# Prove the checkout is self-sufficient (tracked files only, fresh env):
bash scripts/test_clean_checkout.sh
```

A bare clone can also simulate a **full-scale** cohort, using the committed
public synthetic 2023-24 kindergarten data in
**[data/synthetic_2324/](data/synthetic_2324/README.md)** — 4,308 synthetic
applicants, no confidential data required:

```bash
sed "s#<STUDENT_ASSIGNMENT_PATH>#$PWD#g" \
    configs/custom_configs/status_quo_synthetic_2324.yaml > /tmp/synthetic.yaml
uv run python run_custom_config.py --config-path /tmp/synthetic.yaml
```

Its preference lists are drawn from the published `exp8` choice model applied
to the synthetic features, and it ships that model's utility matrix, so
`utility-model.enable: true` works too
(`status_quo_synthetic_2324_umodel.yaml`). See
**[data/synthetic_2324/](data/synthetic_2324/README.md)** for what the dataset
does and does not reproduce, and
**[data/synthetic_2324/ANONYMIZATION.md](data/synthetic_2324/ANONYMIZATION.md)**
for how it was built.

## Paper quickstart

Main-text policy comparison (Status Quo vs zones / reserves / distance
priority): simulate with Deferred Acceptance under **Model A (t14)**, then
aggregate metrics. Details and SI variants:
**[docs/SI_APPENDIX.md](docs/SI_APPENDIX.md)**.

1. **Data + estimates** — [docs/PIPELINE.md](docs/PIPELINE.md). Use Model A
  (`t14`) utilities for 2023–24 (train 2022–23). Set `paths.estimate-path`.
   Do not commit student-level `estimates_*.csv` to public git.
2. **Policies (Table 1)**:

  | Column                   | Subconfig pattern                                |
  | ------------------------ | ------------------------------------------------ |
  | Status Quo               | `status_quo`                                     |
  | Small Zones              | `13-0.25-2500_BG+no_reserves` (Fig. zones **a**) |
  | Small + Reserves         | `13-0.25-2500_BG+reserves_05frl`                 |
  | Medium Zones             | `6-0.10-1430_BG+no_reserves` (Fig. zones **c**)  |
  | Medium + Reserves        | `6-0.10-1430_BG+reserves_05frl`                  |
  | Dist Priority + Reserves | `distance_05_1_2+reserves_05frl`                 |
  | Status Quo + Reserves    | `status_quo+reserves_05frl`                      |

   Main-text reserves = FRL **50%** (`*_05frl`). Dist bands =
   `[0.5, 1, 2]` miles. List length = `0.8*round(real_length)`; 25 MC
   iterations; KG 2023–24 R1 filter file.
   Zone CSVs for these columns:
   `[data/zones/table1/](data/zones/table1/)` (see README there for
   `concept1zones.csv` / Con1 = Concept 1 attendance areas used by Dist Priority).
3. **Simulate** — edit paths in
   [`configs/paper/table1_config.yaml`](configs/paper/table1_config.yaml),
   then `run_custom_config.py` (or `scripts/run_models_estimates.sh`).
4. **Metrics table** — `scripts/analysis/analyze_trends.py` →
   `metrics_comparison.xlsx` (`short_match_evaluator.py`). Row-name map:
   [docs/PAPER_METRICS.md](docs/PAPER_METRICS.md).
```bash
# Table 1 seven policies (needs real data + paths; see Data setup)
uv run python run_custom_config.py \
    --config-path configs/paper/table1_config.yaml
```

`status_quo_real` = historical assignment; Table 1 Status Quo column uses
counterfactual `status_quo` with utilities on.

Appendix / robustness: **[docs/SI_APPENDIX.md](docs/SI_APPENDIX.md)**.

## Entry points

Everything that drives a simulation or analysis is **config-file driven**;
preprocessing utilities take plain CLI flags. Prefix each with `uv run`.

**Default paper path**


| Script                               | Invocation             | Purpose                                                                   |
| ------------------------------------ | ---------------------- | ------------------------------------------------------------------------- |
| `run_custom_config.py`               | `--config-path <yaml>` | Run one simulation from a YAML config.                                    |
| `scripts/run_models_estimates.sh`    | `--settings <env>`     | Full pipeline: generate → simulate → analyze → `metrics_comparison.xlsx`. |
| `scripts/analysis/analyze_trends.py` | `--config <yaml>`      | Aggregate runs into a metrics workbook + plots.                           |


**Also useful (see SI Appendix for when to use them)**


| Script                                            | Invocation                        | Purpose                                                          |
| ------------------------------------------------- | --------------------------------- | ---------------------------------------------------------------- |
| `scripts/analysis/plot_simulation_frontier.py`    | `--config <yaml>`                 | Pareto frontier (e.g. distance vs dissimilarity).                |
| `run_augmented_da.py`                             | `--config-path <yaml>`            | DA with preference-list augmentation.                            |
| `create_simulator_input.py`                       | CLI flags                         | Build simulator input tables.                                    |
| `recompute_lottery_number.py`                     | `--students --schools --output`   | Recompute tie-breaker lotteries.                                 |
| `scripts/preprocessing/filter_programs.py`        | `--data-dir --output-dir`         | Drop special programs from program CSVs.                         |
| `scripts/generators/generate_zone_from_pickle.py` | CLI flags                         | Build a zone CSV from a pickled plan.                            |
| `scripts/generators/generate_small_dataset.py`    | `--out-dir --num-students --seed` | Regenerate the committed small test dataset.                     |


Use `--help` on any script for its options. Full config reference:
**[docs/CONFIG_OPTIONS.md](docs/CONFIG_OPTIONS.md)**.

## Repository layout

```
student_assignment/         Core library (installed as a package by uv sync)
  da/                       Deferred-acceptance variants (vanilla, guardrails, quotas)
  market_generator/         Preference/utility generation, list augmentation
  choice_model/             Port of the public exp8 MNL (utilities from weights)
  data_interfaces/          Student, program, zone loaders
  evaluation/               Match evaluation and metrics
  configerator/             Layered config loading + schema validation
  utils/plotting.py         Shared matplotlib/seaborn styling

scripts/
  run_models_estimates.sh   End-to-end pipeline (generate → simulate → analyze)
  settings/                 Pipeline settings files (local, test)
  analysis/analyze_trends.py    Aggregate runs into metrics_comparison.xlsx
  preprocessing/            Data filtering and extraction
  generators/               Zone, small-dataset and synthetic-dataset generators
  test_clean_checkout.sh    Verify the repo runs from tracked files only

configs/
  base_config.yaml          Simulation defaults
  local_path_config.yaml    Default path template (edit or override in configs/<user>.config.yaml)
  config_schema.yaml        yamale schema for the user config
  custom_configs/           Representative run configs (status quo, augmented, …)
  policy_configs/           Policy definitions (zones, distance bands, reserves)
  examples/                 One canonical sample per generated config family
  paper/                    Table 1–style paper configs

data/
  synthetic_2324/           Public synthetic 2023-24 KG cohort + its provenance docs
  zones/                    Committed zone definitions

tests/                      pytest suite (incl. end-to-end test_full_pipeline.py)
tests/fixtures/small_2223/  Committed small dataset the pipeline test runs on
docs/                       CONFIG_OPTIONS.md, PIPELINE.md, DATA_SETUP.md, Sphinx sources
```

## Configuration

Config is resolved in layers (each overrides the previous): `base_config.yaml`
→ environment path config → auto-created `configs/<user>.config.yaml` → custom
run YAML → policy subconfig. The first time you run any entry point, the
`Configerator` writes your personal `configs/<user>.config.yaml` automatically.

Every option (top-level keys, `paths.*`, `utility-model.*`, policy subconfigs,
list-augmentation, the analysis config, and pipeline settings files) is
documented in **[docs/CONFIG_OPTIONS.md](docs/CONFIG_OPTIONS.md)**.

## Data setup

**Without the confidential data**, use the committed public synthetic cohort in
**[data/synthetic_2324/](data/synthetic_2324/README.md)**: 4,308 synthetic
kindergarten applicants built from aggregate statistics of the real 2023-24
cohort, with preferences drawn from the public choice model, runnable at full
scale via `configs/custom_configs/status_quo_synthetic_2324.yaml`. Read its
[ANONYMIZATION.md](data/synthetic_2324/ANONYMIZATION.md) for the limits before
drawing conclusions from it.

For the real data, point configs at your own copy of the confidential SFUSD
data (not in this repo). Defaults load from
`configs/local_path_config.yaml`; on first run the `Configerator` also writes
`configs/<user>.config.yaml` for personal overrides.

Write run outputs and any local copies of cleaned microdata under
**`local-data/`** (gitignored) so individual-level files are not committed —
see [docs/DATA_SETUP.md](docs/DATA_SETUP.md#local-data--scratch-space-for-real-authorized-runs).

Paths in example configs use **placeholder tokens** you replace with your own
**absolute** paths:


| Token                       | Replace with (absolute path)                                                                                                |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `<STUDENT_ASSIGNMENT_PATH>` | your `student-assignment` checkout (inputs and run outputs under `local-data/`)                                             |
| `<SFUSD_CHOICE_PATH>`       | your `[SFUSD-Choice-public](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public)` checkout (MNL `estimates_*.csv`) |
| `<SFUSD_DATA_PATH>`         | your local copy of the confidential SFUSD data tree                                                                         |
| `<RA_SFUSD_PATH>`           | **optional / outside repo** — only for `configs/permuted.yaml`                                                              |


Apply them quickly, e.g. `sed -i "s#<STUDENT_ASSIGNMENT_PATH>#$PWD#g" configs/<your-config>.yaml`.
Full guide (which key points to which file, what runs out-of-the-box):
**[docs/DATA_SETUP.md](docs/DATA_SETUP.md)**.

## Development

```bash
make install         # uv sync
make test            # uv run pytest tests -q
make lint            # uv run ruff check .
make format          # uv run ruff format . && uv run ruff check --fix .
make clean-checkout  # bash scripts/test_clean_checkout.sh
```

- **Lint + format:** [Ruff](https://docs.astral.sh/ruff/) (line length 80;
`ruff format` for layout, `ruff check` for lint). Config in `pyproject.toml`.
- **Docstrings:** [Google style](https://google.github.io/styleguide/pyguide.html).
- **Dependencies:** `uv add <pkg>` / `uv remove <pkg>` (edits `pyproject.toml`
and re-locks `uv.lock`); commit both.

## Documentation


| Doc                                                  | Contents                                                |
| ---------------------------------------------------- | ------------------------------------------------------- |
| [docs/SI_APPENDIX.md](docs/SI_APPENDIX.md)           | SI Appendix: locked paper↔code map + figure/table index |
| [docs/PAPER_METRICS.md](docs/PAPER_METRICS.md) | Paper table rows ↔ code metric keys |
| [docs/CONFIG_OPTIONS.md](docs/CONFIG_OPTIONS.md)     | Every config key, layer by layer                        |
| [docs/PIPELINE.md](docs/PIPELINE.md)                 | Clone → first real simulation runbook                   |
| [docs/DATA_SETUP.md](docs/DATA_SETUP.md)             | Data files, path config, placeholder tokens             |
| [docs/ZONE_SETUP.md](docs/ZONE_SETUP.md)             | Registering zone files for simulation                   |


Project onboarding documentation is maintained internally by the SFUSD
research group and is available to collaborators on request.

This work builds on the original `sfusd-project` codebase by Kaleigh Mentzer
and collaborators.