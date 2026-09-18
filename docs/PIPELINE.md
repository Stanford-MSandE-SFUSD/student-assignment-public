# From Clone to First Simulation

End-to-end runbook: everything needed to go from a fresh `git clone` to a
running simulation. Each step links to the detailed guide where relevant.

> **TL;DR.** A bare clone is **not** runnable on its own: the confidential data
> is not in the repo, and the filtered inputs under `local-data/` are
> git-ignored. The order is: **env → data → substitute placeholders →
> generate filtered inputs → (zones, only for zone-restricted policies) → run.**
> Generating zones is *not* the first step, and most baselines don't need zones
> at all.

---

## Step 0 — Python environment

```bash
uv sync            # install pinned deps into .venv (see README for uv setup)
# prefix commands below with `uv run`, or `source .venv/bin/activate` first
```

## Step 1 — Get the confidential SFUSD data

The data is **not** redistributable and is **not** in the repo. Obtain it from
an **authorized** source, then point `configs/local_path_config.yaml` (or your
generated `configs/<username>.config.yaml`) at your local copy.

Paper Table 1 zone geography that *is* in the repo:
`[data/zones/table1/](../data/zones/table1/)`.

See **[DATA_SETUP.md](DATA_SETUP.md)** for the per-file path reference.

## Step 2 — Substitute the placeholder tokens

Committed configs use explicit placeholder tokens instead of anyone's home
directory. Replace them with your **absolute** paths:


| Token                       | Replace with                                                                                                        |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `<STUDENT_ASSIGNMENT_PATH>` | your `student-assignment` checkout                                                                                  |
| `<SFUSD_CHOICE_PATH>`       | your `[SFUSD-Choice-public](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public)` checkout (MNL estimates) |
| `<SFUSD_DATA_PATH>`         | your local copy of the SFUSD data tree                                                                              |
| `<RA_SFUSD_PATH>` | **Optional / outside this repo** — only for `configs/permuted.yaml` if you have a private `RA_SFUSD` checkout |


```bash
# Example: point everything at the current checkout.
grep -rl '<STUDENT_ASSIGNMENT_PATH>' configs/ \
  | xargs sed -i "s#<STUDENT_ASSIGNMENT_PATH>#$PWD#g"
```

Details and the full key→file table: **[DATA_SETUP.md](DATA_SETUP.md)**.

## Step 3 — Prepare simulation inputs (`local-data/` + cleaned students)

`local-data/` is **gitignored** (see `.gitignore`), so a fresh clone has none
of it. Put authorized run inputs/outputs there so individual-level files are
not committed — details in [DATA_SETUP.md](DATA_SETUP.md#local-data--scratch-space-for-real-authorized-runs).

### 3a. Program filter → `local-data/program_filter/` (usual)

Removes special programs from each year's cleaned program file:

```bash
python scripts/preprocessing/filter_programs.py \
  --data-dir <SFUSD_DATA_PATH>/Data
# reads  <SFUSD_DATA_PATH>/Data/Cleaned/programs_{YY}.csv  (years 2013–2023)
# writes local-data/program_filter/programs_without_specialprogs_{YY}.csv
```

### 3b. Student file 

Point `student-data` at the cleaned round-1 file with special programs already
removed, e.g.

`<SFUSD_DATA_PATH>/Data/Cleaned/r1_filter_student_without_specialprogs_2324.csv`

(or a local copy under `local-data/cleaned/`, as in
`[configs/paper/table1_config.yaml](../configs/paper/table1_config.yaml)`).

> Tip: `program-data` should match the same special-program filtering as
> `student-data`.

## Step 4 — Zones (only for zone-restricted policies)

Skip this for baselines like `status_quo_real` (no zone restriction → no zone
file is ever opened).

Use the tracked paper maps under `data/zones/table1/` (and other CSVs in
`data/zones/`) — see [SI_APPENDIX.md](SI_APPENDIX.md) for which file matches
each paper design. Full register → policy → run workflow:
**[ZONE_SETUP.md](ZONE_SETUP.md)**.

## Step 5 — Run a simulation


| Goal                                          | Command                                                                                             | Needs                                           |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| A custom config                               | `uv run python run_custom_config.py --config-path configs/custom_configs/status_quo_real_2324.yaml` | Steps 0–3 (Step 4 only if the policy is zoned). |
| Augmented DA                                  | `uv run python run_augmented_da.py --config-path configs/custom_configs/augmented_da_2324.yaml`     | Steps 0–4 (this config uses local zones).       |
| Full pipeline (generate → simulate → analyze) | `bash scripts/run_models_estimates.sh --settings scripts/settings/models_local.env`                 | Steps 0–4 + MNL estimates.                      |


`--config_path` is also accepted. Use `--help` for the argparse scripts.

---

## Dependency cheat-sheet


| Config family                          | Cleaned data | Filtered inputs (Step 3) | Zones (Step 4) | MNL estimates                     |
| -------------------------------------- | ------------ | ------------------------ | -------------- | --------------------------------- |
| `status_quo_real_`*                    | ✅            | ✅                        | —              | — (`utility-model.enable: false`) |
| `augmented_da_2324`                    | ✅            | ✅                        | ✅ (local)      | —                                 |
| `all_zones*`, `selected*` (zoned)      | ✅            | ✅                        | ✅ (local)      | depends                           |
| utility-model configs (`enable: true`) | ✅            | ✅                        | depends        | ✅ `<SFUSD_CHOICE_PATH>`           |


## See also

- **[DATA_SETUP.md](DATA_SETUP.md)** — which config key points to which file, placeholder tokens.
- **[ZONE_SETUP.md](ZONE_SETUP.md)** — register zone CSVs for simulation.

