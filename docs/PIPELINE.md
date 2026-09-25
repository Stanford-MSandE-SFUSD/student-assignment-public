# From Clone to First Simulation

End-to-end runbook: from a fresh `git clone` to a Table 1–style metrics
workbook. Details live in the linked docs.

> **TL;DR.** Choose a **data track** (Track A synthetic vs Track B DUA SFUSD),
> set paths, then: zones (if needed) → simulate → `metrics_comparison.xlsx`.
> For paper-scale synthetic, see § A1; for a quick smoke test, § A2.

---

## Two tracks (data only)


| Track | Who | Step 1 |
| --- | --- | --- |
| **A — Synthetic** | Anyone with a clone | Public pack `data/synthetic_2324/` (§ A1). Smoke test: § A2. |
| **B — DUA SFUSD** | Access under a data-use agreement | Confidential microdata + filtered student/program files. |


After Step 1, **both tracks follow Steps 2–5**. Main-text Table 1 is the
goal of this runbook; SI robustness is in [SI_APPENDIX.md](SI_APPENDIX.md).

Zone geography for Table 1 (both tracks):
[`data/zones/table1/`](../data/zones/table1/).

---

## Step 0 — Python environment

```bash
uv sync
# prefix commands with `uv run`, or `source .venv/bin/activate`
```

---

## Step 1 — Get inputs (choose a track)

### Track A — Synthetic

#### A1. Paper-scale synthetic (2023–24 kindergarten)

| Path | Role |
| --- | --- |
| `data/synthetic_2324/` | Students, programs, schools, public CDE school composition |
| `scripts/generate_syn_estimates_cde.py` | CDE → MNL utilities from Choice weights (`t14` / `t17` / `t9` / `t14_1718`) |
| `scripts/generate_syn_mnl_cde_configs.py` | Emit Table 1 + SI sim/analysis YAMLs under `local-data/` |
| `scripts/run_syn_mnl_cde_table1.py` | Run + analyze Table 1 |
| `scripts/run_syn_mnl_cde_step3.py` | Run + analyze SI robustness ladder (comparable takeaways) |

Requires a [SFUSD-Choice-public](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public)
checkout with calibrated weights. Set `SFUSD_CHOICE_PATH` to that directory
(or place it as a sibling of this repo named `SFUSD-Choice-public`).

```bash
uv sync
# optional: export SFUSD_CHOICE_PATH=/path/to/SFUSD-Choice-public

uv run python scripts/generate_syn_estimates_cde.py
# → local-data/estimates_syn/mnl_cde/estimates_*_2324.csv

uv run python scripts/generate_syn_mnl_cde_configs.py
uv run python scripts/run_syn_mnl_cde_table1.py
# SI robustness ladder (comparable takeaways):
uv run python scripts/run_syn_mnl_cde_step3.py
```

Point any hand-written config at `data/synthetic_2324/` for
`student-data` / `program-data` / `school-data` and at the generated
`estimate-path`, then continue at **Step 2**, or use the runners above.

For a quick check without the MNL weights, use the smoke test in § A2.

#### A2. Smoke test (today, not paper-scale)

Tiny committed fixture for CI / a self-sufficient clone — not a numerical
Table 1 reproduction:

```bash
uv sync
uv run python -m pytest tests -q
bash scripts/run_models_estimates.sh --settings scripts/settings/models_test.env
```

Inputs: `tests/fixtures/small_2223/`. Outputs default under
`local-data/local-runs/small_pipeline_test/`. See
`tests/test_full_pipeline.py`.

### Track B — DUA SFUSD data

1. Obtain confidential SFUSD extracts under your DUA.
2. Build cleaned `student_*.csv`, `programs_*.csv`, and
   `schools_rehauled_*.csv` that follow
   [KG_VARIABLE_DICTIONARY.md](KG_VARIABLE_DICTIONARY.md)
   (often a **superset** of the paper columns). Details:
   [DATA_SETUP.md](DATA_SETUP.md).
3. Adapt to the shared KG schema ([KG_SCHEMA.md](KG_SCHEMA.md)):

```bash
uv run python scripts/preprocessing/adapt_to_kg_schema.py \
  --student <SFUSD_DATA_PATH>/Data/Cleaned/student_2324.csv \
  --programs <SFUSD_DATA_PATH>/Data/Cleaned/programs_2324.csv \
  --schools <SFUSD_DATA_PATH>/Data/Cleaned/schools_rehauled_2324.csv \
  --out-dir local-data/kg_ready
```

4. Point `configs/local_path_config.yaml` or `configs/<username>.config.yaml`
   at the KG-ready files (or keep `sfusd` and override `student-data` /
   `program-data` / `school-data`); write run I/O under `local-data/`.
5. Filter programs (from cleaned or kg_ready programs dir as appropriate):

```bash
python scripts/preprocessing/filter_programs.py \
  --data-dir <SFUSD_DATA_PATH>/Data
# → local-data/program_filter/programs_without_specialprogs_{YY}.csv
```

6. Point `student-data` at a round-1 file with special programs already
   removed (and `program-data` at a matching filtered programs file), e.g. as
   in [`configs/paper/table1_config.yaml`](../configs/paper/table1_config.yaml).

Then continue at **Step 2**.

---

## Shared steps (Tracks A and B)

### Step 2 — Substitute placeholder tokens

Committed configs use absolute-path placeholders. Replace them in the config
you will run:


| Token                       | Replace with |
| --------------------------- | ------------ |
| `<STUDENT_ASSIGNMENT_PATH>` | this checkout |
| `<SFUSD_CHOICE_PATH>`       | [SFUSD-Choice-public](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public) checkout (MNL estimates), or synthetic estimates on Track A |
| `<SFUSD_DATA_PATH>`         | SFUSD data tree (Track B); omit if every path is already explicit |


```bash
grep -rl '<STUDENT_ASSIGNMENT_PATH>' configs/ \
  | xargs sed -i "s#<STUDENT_ASSIGNMENT_PATH>#$PWD#g"
```

Full key → file map: [DATA_SETUP.md](DATA_SETUP.md).

### Step 3 — Zones (zone / distance policies only)

Baselines like `status_quo` do not open a zone file.

**Table 1:** maps under [`data/zones/table1/`](../data/zones/table1/) — see
that folder’s [README](../data/zones/table1/README.md).
[`configs/paper/table1_config.yaml`](../configs/paper/table1_config.yaml)
already registers them.

Other designs: [SI_APPENDIX.md](SI_APPENDIX.md), [ZONE_SETUP.md](ZONE_SETUP.md).

### Step 4 — Run a simulation

**Main path (Table 1, seven policies):**

```bash
uv run python run_custom_config.py \
    --config-path configs/paper/table1_config.yaml
```

Needs Steps 0–3 and Model A (or synthetic) estimates at `paths.estimate-path`.

Other examples live under `configs/custom_configs/` and `configs/examples/`
([CONFIG_OPTIONS.md](CONFIG_OPTIONS.md)).

### Step 5 — Aggregate metrics

```bash
uv run python scripts/analysis/analyze_trends.py --config <analysis.yaml>
```

Produces `metrics_comparison.xlsx` under the analysis YAML’s `output_dir`
(relative to your cwd; prefer `local-data/metrics/...`). Sheets: `Mean Values`,
`Std Values`, `Mean ± Std`. CSV fallbacks if Excel export fails.

**Table 1 shape:** simulate all seven policies (typically 25 iterations), point
one `runs:` entry per policy folder, then map row keys with
[PAPER_METRICS.md](PAPER_METRICS.md).

Simulation assignments land under `paths.assignment-folder`; caches under
`paths.student-save`; optional utility matrix under `utility-model.save-path`.

---

## See also

- [DATA_SETUP.md](DATA_SETUP.md) — paths and placeholder tokens
- [ZONE_SETUP.md](ZONE_SETUP.md) — registering zone CSVs
- [PAPER_METRICS.md](PAPER_METRICS.md) — paper rows ↔ workbook keys
- [SI_APPENDIX.md](SI_APPENDIX.md) — main text vs SI policy map
