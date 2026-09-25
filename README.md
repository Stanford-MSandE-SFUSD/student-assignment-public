# Student Assignment Simulator

Simulation tools for the **San Francisco Unified School District (SFUSD)**
school-choice system. The simulator runs Deferred Acceptance (and variants)
under different zone, priority, and tie-breaking policies, then compares a
**Status Quo** baseline against these policy variants on choice attainment (top-k),
travel distance, and equity (racial / socioeconomic composition).

**Companion repo:** choice-model training and `estimates_*.csv` live in
[SFUSD-Choice-public](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public).
Point `<SFUSD_CHOICE_PATH>` at that checkout (see [Data setup](#data-setup)).

### How to navigate this repo


| Track                 | Start here                                                                                                        |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- |
| **Newcomer / CI**     | [Quick start](#quick-start) — `pytest` on the committed small dataset                                             |
| **Paper (main text)** | [Paper quickstart](#paper-quickstart) — DA policies → metrics table                                               |
| **Paper figures**     | **[docs/PAPER_FIGURES.md](docs/PAPER_FIGURES.md)** — Fig. 2 zones; Fig. 3 indices (replot)                        |
| **SI Appendix**       | **[docs/SI_APPENDIX.md](docs/SI_APPENDIX.md)** — robustness, frontiers, list augmentation, etc.                   |
| **Full setup**        | [docs/PIPELINE.md](docs/PIPELINE.md) (Track A synthetic or Track B DUA), [docs/DATA_SETUP.md](docs/DATA_SETUP.md) |


SFUSD microdata are governed by a DUA and are not in this public clone.
Without them you can still: run tests and the small-fixture pipeline
(`scripts/settings/models_test.env`); or use the public synthetic 2023–24
pack in `data/synthetic_2324/` for paper-scale Track A runs
([PIPELINE.md](docs/PIPELINE.md)).

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
# small dataset. Works on a bare clone, with no confidential microdata.
uv run python -m pytest tests -q

# Prove the checkout is self-sufficient (tracked files only, fresh env):
bash scripts/test_clean_checkout.sh
```

Paper-scale runs without SFUSD microdata: see
[PIPELINE.md Track A](docs/PIPELINE.md) (pack in `data/synthetic_2324/`).

## Paper quickstart

Main-text policy comparison (Status Quo vs zones / reserves / distance
priority): simulate with Deferred Acceptance under **Model A (t14)**, then
aggregate metrics. Setup:
**[docs/PIPELINE.md](docs/PIPELINE.md)**. SI variants:
**[docs/SI_APPENDIX.md](docs/SI_APPENDIX.md)**. Figures:
**[docs/PAPER_FIGURES.md](docs/PAPER_FIGURES.md)**.

1. **Data + estimates** — [docs/PIPELINE.md](docs/PIPELINE.md) Track A
  (synthetic) or Track B (DUA SFUSD). Use Model A (`t14`) utilities for
   2023–24 (train 2022–23). Set `paths.estimate-path`.
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
   Zone CSVs:
   `[data/zones/table1/](data/zones/table1/)` (see README there for
   `concept1zones.csv` / Con1 = Concept 1 attendance areas used by Dist Priority).
3. **Simulate** — edit paths in
  `[configs/paper/table1_config.yaml](configs/paper/table1_config.yaml)`,
   then:

```bash
uv run python run_custom_config.py \
    --config-path configs/paper/table1_config.yaml
```

1. **Metrics workbook** — after all seven policies have run,
  `scripts/analysis/analyze_trends.py` → `metrics_comparison.xlsx`
   (**Mean Values** = average over iterations).
  Row-name map: [docs/PAPER_METRICS.md](docs/PAPER_METRICS.md). Details:
   [docs/PIPELINE.md](docs/PIPELINE.md#step-5--aggregate-metrics).

Table 1 Status Quo column uses counterfactual `status_quo` with utilities on.

## Entry points

Everything that drives a simulation or analysis is **config-file driven**;
preprocessing utilities take plain CLI flags. Prefix each with `uv run`.

**Default paper path**


| Script                               | Invocation             | Purpose                                                                           |
| ------------------------------------ | ---------------------- | --------------------------------------------------------------------------------- |
| `run_custom_config.py`               | `--config-path <yaml>` | Run one simulation from a YAML config.                                            |
| `scripts/run_models_estimates.sh`    | `--settings <env>`     | Full pipeline: generate → simulate → analyze → `metrics_comparison.xlsx`.         |
| `scripts/analysis/analyze_trends.py` | `--config <yaml>`      | Mean/std metrics workbook (`metrics_comparison.xlsx`) over assignment iterations. |


**Also useful** (when to use them: [SI_APPENDIX.md](docs/SI_APPENDIX.md))


| Script                                         | Invocation                | Purpose                                           |
| ---------------------------------------------- | ------------------------- | ------------------------------------------------- |
| `scripts/analysis/plot_simulation_frontier.py` | `--config <yaml>`         | Pareto frontier (e.g. distance vs dissimilarity). |
| `run_augmented_da.py`                          | `--config-path <yaml>`    | DA with preference-list augmentation.             |
| `scripts/preprocessing/filter_programs.py`     | `--data-dir --output-dir` | Drop special programs from program CSVs.          |


Other maintainer utilities (`create_simulator_input.py`,
`recompute_lottery_number.py`, zone / small-dataset generators): see each
script’s `--help`.

Full config reference: **[docs/CONFIG_OPTIONS.md](docs/CONFIG_OPTIONS.md)**.

## Repository layout

```
student_assignment/         Core library (installed as a package by uv sync)
  da/                       Deferred-acceptance variants (vanilla, guardrails, quotas)
  market_generator/         Preference/utility generation, list augmentation
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

Every option is documented in **[docs/CONFIG_OPTIONS.md](docs/CONFIG_OPTIONS.md)**.

## Data setup

Point configs at your data (Track A synthetic and/or Track B DUA; see
[PIPELINE.md](docs/PIPELINE.md)). Defaults load from
`configs/local_path_config.yaml`; on first run the `Configerator` also writes
`configs/<user>.config.yaml` for personal overrides.

Write run outputs and local copies of cleaned microdata under
`**local-data/`** (gitignored) — see
[docs/DATA_SETUP.md](docs/DATA_SETUP.md#local-data--scratch-space-for-runs).

Paths in example configs use **placeholder tokens** you replace with your own
**absolute** paths:


| Token                       | Replace with (absolute path)                                                                                              |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `<STUDENT_ASSIGNMENT_PATH>` | your `student-assignment` checkout (inputs and run outputs under `local-data/`)                                           |
| `<SFUSD_CHOICE_PATH>`       | your [SFUSD-Choice-public](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public) checkout (MNL `estimates_*.csv`) |
| `<SFUSD_DATA_PATH>`         | your local copy of the confidential SFUSD data tree                                                                       |


Apply them quickly, e.g. `sed -i "s#<STUDENT_ASSIGNMENT_PATH>#$PWD#g" configs/<your-config>.yaml`.
Full guide: **[docs/DATA_SETUP.md](docs/DATA_SETUP.md)**.

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


| Doc                                                              | Contents                                                |
| ---------------------------------------------------------------- | ------------------------------------------------------- |
| [docs/PAPER_FIGURES.md](docs/PAPER_FIGURES.md)                   | Main-text Fig. 2 / Fig. 3 reproduction                  |
| [docs/SI_APPENDIX.md](docs/SI_APPENDIX.md)                       | SI Appendix: locked paper↔code map + figure/table index |
| [docs/PAPER_METRICS.md](docs/PAPER_METRICS.md)                   | Paper table rows ↔ code metric keys                     |
| [docs/CONFIG_OPTIONS.md](docs/CONFIG_OPTIONS.md)                 | Every config key, layer by layer                        |
| [docs/PIPELINE.md](docs/PIPELINE.md)                             | Clone → first simulation (Track A or Track B)           |
| [docs/DATA_SETUP.md](docs/DATA_SETUP.md)                         | Data files, path config, placeholder tokens             |
| [docs/KG_SCHEMA.md](docs/KG_SCHEMA.md)                           | Shared KG columns (synthetic + adapted cleaned)         |
| [docs/KG_VARIABLE_DICTIONARY.md](docs/KG_VARIABLE_DICTIONARY.md) | How KG columns are derived from district extracts       |
| [docs/ZONE_SETUP.md](docs/ZONE_SETUP.md)                         | Registering zone files for simulation                   |
| [data/zones/README.md](data/zones/README.md)                     | `table1/` vs `fig3/` zone geography                     |


Project onboarding documentation is maintained internally by the Stanford   
research group and is available to collaborators on request.

This work builds on the original `sfusd-project` codebase by Kaleigh Mentzer
and collaborators.