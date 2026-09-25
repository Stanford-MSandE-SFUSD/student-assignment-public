# Data Setup Guide

Which files the simulator needs, and which config key points to each one.
For clone → simulate → metrics, see [PIPELINE.md](PIPELINE.md).

---

## How paths are resolved

At first run, `Configerator` (`student_assignment/configerator/configerator.py`)
builds your personal config `configs/<username>.config.yaml` (git-ignored) by
merging `configs/base_config.yaml` with `configs/local_path_config.yaml`.

**Override paths by editing your generated `configs/<username>.config.yaml`**
(preferred) or the `local_path_config.yaml` template itself.

All paths live under the top-level `paths:` key of the config.

## Placeholder tokens in example / custom configs

The committed configs under `configs/custom_configs/`, `configs/examples/`,
`configs/paper/`, and the analysis configs use **placeholder tokens** you
replace with your own **absolute** paths.


| Token                       | Replace with (absolute path) |
| --------------------------- | ---------------------------- |
| `<STUDENT_ASSIGNMENT_PATH>` | This checkout (inputs and run outputs under `local-data/`). |
| `<SFUSD_CHOICE_PATH>`       | Your [SFUSD-Choice-public](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public) checkout (MNL `estimates_*.csv`), or synthetic estimates when using Track A. |
| `<SFUSD_DATA_PATH>`         | Your local copy of the confidential SFUSD data tree (typically contains `Data/Cleaned/`, …). |


> Several keys (`student-data`, `program-data`, `school-data`) are passed through
> `os.path.join(<sfusd>, value)`. An absolute value makes the join a no-op, so
> the file you name is the file that’s read. Output keys (`assignment-folder`,
> `student-save`, `save-path`) are read directly and should be absolute too.

---

## `local-data/` — scratch space for runs

Individual-level inputs/outputs stay under `local-data/` at the repo root
(gitignored). Use it for Track B (DUA) copies and for Track A synthetic-run
artifacts.


| Convention | What goes here |
|------------|----------------|
| `local-data/cleaned/` | Optional local copies of cleaned student/program CSVs |
| `local-data/program_filter/` | Output of `scripts/preprocessing/filter_programs.py` |
| `local-data/local-runs/` | Assignment CSVs, precomputed caches (`student-save`), utility matrices |
| `local-data/metrics/` | Recommended home for `analyze_trends.py` `output_dir` |
| `local-data/logs/` | Pipeline logs |

1. Keep the canonical Track B tree at `<SFUSD_DATA_PATH>`; copy or point
   configs at files you need.
2. Point write paths (`assignment-folder`, `student-save`, …) at
   `…/local-data/…`.
3. Do not put confidential microdata CSVs in tracked folders (`data/`, `tests/`,
   `configs/`). Zone geography under `data/zones/` is FIPS/ids only — OK.
4. `configs/<username>.config.yaml` is gitignored (often holds absolute paths).

A bare clone has no `local-data/` until the first preprocess or sim run. CI
uses `tests/fixtures/small_2223/` (see PIPELINE Track A smoke test).

---

## Synthetic data

**How to run:** [PIPELINE.md](PIPELINE.md) § Track A — estimates, then Table 1
and SI ladder runners (or point your own YAML at the pack).

**Pack:** `data/synthetic_2324/`. Typical contents:

| Path under pack | Role |
| --- | --- |
| `student_2324_synthetic.csv` | Synthetic applicants (KG schema) |
| `programs_without_specialprogs_2324.csv` | Programs (special types already dropped) |
| `Cleaned/schools_rehauled_2324.csv` | Schools |
| `reference/enrolled_cde_composition.csv` | Public CDE composition for estimate gen |

Example `paths:` after the pack is present (Track A):

```yaml
paths:
  sfusd: <STUDENT_ASSIGNMENT_PATH>/local-data/   # rare relative resolves only
  student-save: <STUDENT_ASSIGNMENT_PATH>/local-data/Precomputed/
  assignment-folder: <STUDENT_ASSIGNMENT_PATH>/local-data/local-runs/table1_syn/
  estimate-path: <STUDENT_ASSIGNMENT_PATH>/local-data/estimates_syn/mnl_cde/estimates_t14_2223_k1_prog_gesplit_2324.csv
  student-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/student_2324_synthetic.csv
  program-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/programs_without_specialprogs_2324.csv
  school-data: <STUDENT_ASSIGNMENT_PATH>/data/synthetic_2324/Cleaned/schools_rehauled_2324.csv
```

---

## Cleaned inputs vs raw SFUSD

District extracts are **not** simulator inputs. Two steps:

1. **Dump → cleaned** (Track B, DUA): map district extracts into cleaned
   student / program / school CSVs using the rules in
   [KG_VARIABLE_DICTIONARY.md](KG_VARIABLE_DICTIONARY.md). That file may still
   be a **superset** of the paper columns.
2. **Cleaned (or synthetic) → KG schema** (Tracks A and B):  
   [`adapt_to_kg_schema.py`](../scripts/preprocessing/adapt_to_kg_schema.py)
   selects/orders columns so both tracks match. See [KG_SCHEMA.md](KG_SCHEMA.md)
   and [`schemas/`](../schemas/).

This repo’s other `scripts/preprocessing/` tools (e.g. `filter_programs.py`)
run **after** the KG-ready files exist.

```bash
uv run python scripts/preprocessing/adapt_to_kg_schema.py \
  --student <SFUSD_DATA_PATH>/Data/Cleaned/student_2324.csv \
  --programs <SFUSD_DATA_PATH>/Data/Cleaned/programs_2324.csv \
  --schools <SFUSD_DATA_PATH>/Data/Cleaned/schools_rehauled_2324.csv \
  --out-dir local-data/kg_ready
```

Then point configs at `local-data/kg_ready/…` (or run `filter_programs` on
programs under that tree).

### Filtered student / program files (Table 1)

Paper Table 1 sets `remove-special-lps: true` and points at **already-filtered**
CSVs (see [CONFIG_OPTIONS.md](CONFIG_OPTIONS.md) for what that flag drops at
runtime):

| File | Role |
| --- | --- |
| `programs_without_specialprogs_{year}.csv` | Programs with special types removed (`filter_programs.py`) |
| `r1_filter_student_without_specialprogs_{year}.csv` | Round-1 applicants after the same filter (Track B); Track A synthetic pack ships an equivalent student file |

[`configs/paper/table1_config.yaml`](../configs/paper/table1_config.yaml)
wires these via `student-data` / `program-data` overrides.

---

## Quick start

Track B: obtain confidential SFUSD microdata under your DUA, then point
`local_path_config.yaml` or `configs/<username>.config.yaml` at your copy.

In-repo geography (no microdata):

- Table 1 zones: [`data/zones/table1/`](../data/zones/table1/)
- Figure 3 zone cloud: [`data/zones/fig3/`](../data/zones/fig3/)
- Figure 2 clipped BG geometry: [`data/shapefiles/`](../data/shapefiles/)
- Figure 3 plotted values: [`data/figures/fig3/`](../data/figures/fig3/)

```bash
git clone <repo> && cd student-assignment-public
uv sync
uv run python run_custom_config.py --config-path configs/paper/table1_config.yaml
```

(Edit placeholders / paths first — see [PIPELINE.md](PIPELINE.md).)

---

## Path reference: which key points to which file

### Required keys (under `paths:`)


| Config key | What it points to | Notes |
|------------|-------------------|-------|
| `sfusd` | Root of the confidential SFUSD data tree | Relative cleaned-data defaults resolve against this. Usually contains a `Data/` subdirectory. |
| `student-save` | Precomputed-data folder (distances, etc.) | Written/read during runs. |
| `assignment-folder` | Folder for assignment CSVs | Created if missing. |
| `estimate-path` | MNL utilities (`.npy` or `estimates_*.csv`) | Required when `utility-model.enable: true`. From SFUSD-Choice-public or the synthetic pack. |


### Files resolved automatically under `sfusd`

When `student-data` / `program-data` / `school-data` are omitted, cleaned files
resolve under `sfusd` (year `{yy}` = config `year`, e.g. `23` → `2324`).
Paper Table 1 and Track A usually set those three keys explicitly instead.


| File (relative to `sfusd`) | Purpose |
|----------------------------|---------|
| `Data/Cleaned/student_{yy}{yy+1}.csv` | Student records (default) |
| `Data/Cleaned/programs_{yy}{yy+1}.csv` | Program records (default) |
| `Data/Cleaned/schools_rehauled_{yy}{yy+1}.csv` | School records (default) |
| `Data/program_codes.csv` | Code → index map — **only if** the programs CSV lacks a usable `programno` column |

Distances are computed or cached under `paths.student-save`, not under a fixed
`sfusd` Precomputed path.

### Optional override keys

Set any of these to an **absolute path** to bypass the `sfusd`-relative
default (used by `configs/custom_configs/` and paper configs):


| Config key | Overrides | Default if omitted |
|------------|-----------|--------------------|
| `student-data` | student records CSV | `<sfusd>/Data/Cleaned/student_{yy}{yy+1}.csv` |
| `program-data` | programs records CSV | `<sfusd>/Data/Cleaned/programs_{yy}{yy+1}.csv` |
| `school-data` | schools records CSV | `<sfusd>/Data/Cleaned/schools_rehauled_{yy}{yy+1}.csv` |

### Zone keys (needed only for zone / distance policies)


| Config key | What it points to | Notes |
|------------|-------------------|-------|
| `zone-files` | Mapping `<name>: <zone CSV>` | Referenced by `policies:` in policy configs. See [ZONE_SETUP.md](ZONE_SETUP.md). Paper Table 1: `data/zones/table1/`. |
| `citywide-or-lp-zones` | Mapping `<name>: <zone file>` | Supplemental access zones when a policy sets `citywide-or-lp`. |

Rare: `student-codex` / `program-codex` / `lotteries-path` when reading
precomputed preferences or lotteries (`utility-model.read-precomuted-umodel-prefs`
or `read-lotteries`).

---

## Minimal `paths` block

```yaml
paths:
  sfusd: /path/to/your/SFUSD/                 # contains Data/...
  student-save: /path/to/local-data/.../precomputed/
  assignment-folder: /path/to/local-data/.../assignments/
  estimate-path: /path/to/estimates_2324.csv  # Choice or synthetic
  zone-files:                                 # if running zone policies
    13-0.25-2500_BG: data/zones/table1/13-0.25-2500_BG.csv
```

Experiment configs often set `student-data` / `program-data` / `school-data`
explicitly as well.

---

## Troubleshooting

- **`FileNotFoundError` on a `Data/Cleaned/...` path** → check `sfusd` and that
  cleaned files exist for that `year`, or set the three override keys.
- **`estimate-path` not found** → repoint to your Choice (or synthetic)
  `estimates_*.csv`.
- **Zone key not found** → each `policies:` name must be a key in
  `zone-files` / `citywide-or-lp-zones`.
- **`ctip: 5` / five-level CTIP** → needs the block CTIP workbook resolved via
  `sfusd` (`Data/SF 2010 blks … .xlsx`). Table 1 uses `ctip: 1` (student
  `ctip1`) and does not read that file.
