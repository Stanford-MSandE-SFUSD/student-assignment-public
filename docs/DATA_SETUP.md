# Data Setup Guide

This guide explains **which files the simulator needs and which config key
points to each one**, so a new user can clone the repo and run it.

## How paths are resolved

At first run, `Configerator` (`student_assignment/configerator/configerator.py`)
builds your personal config `configs/<username>.config.yaml` (git-ignored) by
merging `configs/base_config.yaml` with `configs/local_path_config.yaml`.

**Override paths by editing your generated `configs/<username>.config.yaml`**
(preferred) or the `local_path_config.yaml` template itself.

All paths live under the top-level `paths:` key of the config.

## Placeholder tokens in example / custom configs

The committed configs under `configs/custom_configs/`, `configs/examples/`,
`configs/paper/`, and the analysis configs do **not** hardcode anyone's home
directory. Values use **placeholder tokens** you replace with your own
**absolute** paths.

There are no CWD-relative (`./`, `../`) values and nothing relies on a file
sitting "under" the `sfusd` root: each file is named by its exact, full path.

| Token | Replace with (absolute path) |
|-------|------------------------------|
| `<STUDENT_ASSIGNMENT_PATH>` | Your `student-assignment` checkout (e.g. `/path/to/student-assignment`). Covers filtered inputs **and** run outputs under `local-data/`. |
| `<SFUSD_CHOICE_PATH>` | Your [`SFUSD-Choice-public`](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public) checkout, which holds the MNL `estimates_*.csv`. |
| `<SFUSD_DATA_PATH>` | Your local copy of the confidential SFUSD data tree (typically contains `Data/Cleaned/`, `simulation-files/`, …). |
| `<RA_SFUSD_PATH>` | **Optional / outside this repo.** Only needed for `configs/permuted.yaml` (permuted-student experiments). Point at a private `RA_SFUSD` checkout if you have one; ignore otherwise. |

> **Why absolute everywhere?** Several keys (`student-data`, `program-data`,
> `school-data`) are passed through `os.path.join(<sfusd>, value)`. With an
> absolute value the join is a no-op, so the file you name is the file that's
> read — regardless of the `sfusd` setting or the working directory. Output keys
> (`assignment-folder`, `student-save`, `save-path`) are read directly, so they
> are absolute placeholders too rather than CWD-relative `./local-data/...`.

---

## Running without the confidential data

`data/synthetic_2324/` holds a committed **public synthetic** 2023-24
kindergarten cohort (4,308 applicants, 72 schools, 129 programs) built from
the real cohort's aggregate statistics, with ranked lists drawn from the public
choice model. Nothing in it is derived from a real
applicant's record. It is enough to run the simulator and the evaluator at full
scale:

```bash
sed "s#<STUDENT_ASSIGNMENT_PATH>#$PWD#g" \
    configs/custom_configs/status_quo_synthetic_2324.yaml > /tmp/synthetic.yaml
uv run python run_custom_config.py --config-path /tmp/synthetic.yaml
```

| File | Config key |
|------|------------|
| `data/synthetic_2324/student_2324_synthetic.csv` | `student-data` |
| `data/synthetic_2324/programs_without_specialprogs_2324.csv` | `program-data` |
| `data/synthetic_2324/Cleaned/schools_rehauled_2324.csv` | `school-data` |
| `data/zones/table1/concept1zones.csv` | `zone-files.Con1` |
| `data/synthetic_2324/choice_model/estimates_2324_synthetic.csv` | `estimate-path` |

Set `year: 23` and `grade: KG`. The dataset's preference lists are drawn from
the published `exp8` choice model, and that model's utility matrix for the
synthetic cohort ships alongside, so both `utility-model.enable: false` (read
the dataset's lists) and `true` (redraw from the matrix, see
`status_quo_synthetic_2324_umodel.yaml`) run without the confidential data.

Read [`data/synthetic_2324/README.md`](../data/synthetic_2324/README.md) for
what the dataset reproduces and
[`data/synthetic_2324/ANONYMIZATION.md`](../data/synthetic_2324/ANONYMIZATION.md)
for how it was built and which analyses it is unsuitable for.


---

## `local-data/` — scratch space for real (authorized) runs

District microdata and simulation outputs **must not** be committed. Put them
under `local-data/` at the repo root (gitignored via `.gitignore`).

| Convention | What goes here |
|------------|----------------|
| `local-data/cleaned/` | Optional local copies of cleaned student/program CSVs |
| `local-data/program_filter/` | Output of `scripts/preprocessing/filter_programs.py` |
| `local-data/local-runs/` | Assignment CSVs, precomputed caches (`student-save`), utility matrices |
| `local-data/logs/` | Pipeline logs |

**How to use it safely**

1. After you obtain SFUSD data under DUA, keep the canonical tree wherever you
   like (`<SFUSD_DATA_PATH>`). Copy or point configs at files you need.
2. Point `assignment-folder`, `student-save`, and other write paths at
   `…/local-data/…` so new individual-level outputs stay outside git.
3. Never move confidential CSVs into tracked folders (`data/`, `tests/`,
   `configs/`). Zone geography CSVs in `data/zones/` are FIPS/ids only — OK.
4. Your auto-generated `configs/<username>.config.yaml` is also gitignored —
   it often contains absolute paths into the confidential tree.

A bare clone has no `local-data/`; it appears when you first run preprocess or
sim scripts. CI and newcomers use the committed **small** test fixture under
`tests/fixtures/small_2223/` instead (no district data).

---

## Quick start

The confidential SFUSD data is **not** in the repo and cannot be redistributed.
Obtain it from an **authorized** source, then point
`local_path_config.yaml` (or your `<username>.config.yaml`) at your local copy.
See the per-file table below.

Paper Table 1 zone maps that *are* in the repo live under
[`data/zones/table1/`](../data/zones/table1/).

```bash
git clone <repo> && cd student-assignment-public
uv sync
# auto-creates configs/<user>.config.yaml on first run:
uv run python run_custom_config.py --config-path configs/paper/table1_config.yaml
```

---

## Path reference: which key points to which file

### Required keys (under `paths:`)

| Config key | What it points to | Notes |
|------------|-------------------|-------|
| `sfusd` | **Root folder** of the confidential SFUSD data tree | Relative cleaned-data defaults resolve against this root. Sanity check: it usually contains a `Data/` subdirectory. |
| `student-save` | Precomputed-data folder (distances, etc.) | Written/read during runs. |
| `assignment-folder` | Folder where assignment CSVs are written | Created if missing. |
| `estimate-path` | MNL choice-model estimates (`.npy` or `estimates_*.csv`) | Required when `utility-model.enable: true`. Produced by the **SFUSD-Choice-public** repo — only this file is needed, not that repo's code. |

### Files resolved automatically under `sfusd`

When you set `sfusd`, these are found automatically (year `{yy}` = config `year`,
e.g. `18` → `1819`). Defined in `student_assignment/definitions/sfusd_files.py`:

| File (relative to `sfusd`) | Purpose |
|----------------------------|---------|
| `Data/program_codes.csv` | Program code lookup |
| `Data/SF 2010 blks ... .xlsx` | Census block attributes |
| `Data/Cleaned/student_{yy}{yy+1}.csv` | Student records |
| `Data/Cleaned/programs_{yy}{yy+1}.csv` | Program records |
| `Data/Cleaned/schools_rehauled_{yy}{yy+1}.csv` | School records |
| `Data/Precomputed/student_program_distances_{yy}{yy+1}.csv` | Student↔program distances |
| `Data/Student Location Data/out_...cbeds20{yy}.dta` | Student locations (CBEDS) |
| `Census 2010_ Blocks .../*.shp` | Census block shapefile |

### Optional override keys

Set any of these to an **absolute path** to bypass the `sfusd`-relative default
above (used by experiment configs in `configs/custom_configs/`):

| Config key | Overrides | Default if omitted |
|------------|-----------|--------------------|
| `student-data` | student records CSV | `<sfusd>/Data/Cleaned/student_{yy}{yy+1}.csv` |
| `program-data` | programs records CSV | `<sfusd>/Data/Cleaned/programs_{yy}{yy+1}.csv` |
| `school-data` | schools records CSV | `<sfusd>/Data/Cleaned/schools_rehauled_{yy}{yy+1}.csv` |

### Zone keys (needed only for zone-restricted policies)

| Config key | What it points to | Notes |
|------------|-------------------|-------|
| `zone-files` | Mapping `<name>: <zone CSV>` | Referenced by `policies:` in policy configs. See `docs/ZONE_SETUP.md` to register new ones. Paper Table 1 maps: `data/zones/table1/`. |
| `citywide-or-lp-zones` | Mapping `<name>: <zone .txt>` | Language / special-education / citywide zones. |

### Keys for precomputed-preference mode (rarely needed)

| Config key | What it points to | Required when |
|------------|-------------------|---------------|
| `student-codex` | Student index codex | `utility-model.read-precomuted-umodel-prefs: true` |
| `program-codex` | Program index codex | same |
| `lotteries-path` | Precomputed lottery numbers | using precomputed lotteries |

---

## Minimal `paths` block

A working `local_path_config.yaml` (or `<username>.config.yaml`) typically needs:

```yaml
paths:
  sfusd: /path/to/your/SFUSD/                 # contains Data/...
  student-save: /path/to/precomputed/
  assignment-folder: /path/to/assignments/
  estimate-path: /path/to/estimates_2324.csv  # MNL estimates from SFUSD-Choice-public
  zone-files:                                 # only if running zone policies
    my-zone: /path/to/zones/my_zone.csv
```

If your config relies on `custom_configs/` overrides, also set `student-data`,
`program-data`, and `estimate-path` to your own copies.

---

## Troubleshooting

- **`FileNotFoundError` on a `Data/Cleaned/...` path** → `sfusd` is wrong, or
  you're missing the cleaned data for that `year`.
- **`estimate-path` not found** → an experiment config points at someone else's
  SFUSD-Choice-public output; repoint it to your own `estimates_*.csv`.
- **Zone key not found** → the name under `policies:` must match a key in
  `zone-files` / `citywide-or-lp-zones`.
