# Kindergarten input schema (Tracks A and B)

Paper simulations in this repo use **kindergarten** student / program / school
CSVs with a **fixed column set**. Track A (synthetic) and Track B (DUA SFUSD)
should match that set so the same configs work on either.

Column lists (source of truth):

| File | List |
| --- | --- |
| Students | [`schemas/kg_student_columns.txt`](../schemas/kg_student_columns.txt) |
| Programs | [`schemas/kg_program_columns.txt`](../schemas/kg_program_columns.txt) |
| Schools | [`schemas/kg_school_columns.txt`](../schemas/kg_school_columns.txt) |

How each column is derived from district extracts (public dictionary):
[KG_VARIABLE_DICTIONARY.md](KG_VARIABLE_DICTIONARY.md).

Who needs what:

| You have… | Do you need this doc / the adapter? |
| --- | --- |
| **Track A** synthetic pack already built to this schema | Usually **no** — point configs at the pack |
| **Track B** cleaned files with **extra** columns beyond this list | **Yes** — run the adapter so the file matches the public synthetic columns |
| Any file that already matches the schema lists | **No** |

The adapter’s only job: **keep the schema columns (in order) and drop everything else**, so Track B inputs match the public synthetic structure. The simulator can often ignore extras, but aligning columns avoids accidental use of research-only fields and keeps both tracks identical.

---

## Adapter

```bash
uv run python scripts/preprocessing/adapt_to_kg_schema.py \
  --student <SFUSD_DATA_PATH>/Data/Cleaned/student_2324.csv \
  --programs <SFUSD_DATA_PATH>/Data/Cleaned/programs_2324.csv \
  --schools <SFUSD_DATA_PATH>/Data/Cleaned/schools_rehauled_2324.csv \
  --out-dir local-data/kg_ready
```

Use your real absolute paths (or synthetic pack paths) instead of the
placeholders. Then point `student-data` / `program-data` / `school-data` at
`local-data/kg_ready/…` (see [PIPELINE.md](PIPELINE.md) Track B).

The adapter:

- Keeps only the columns in the schema lists (stable order)
- Drops any other student/program/school columns (with a log line)
- Removes stray `Unnamed: 0` index columns on programs
- Fills empty placeholder columns if needed (`r2_*`, `msf` for KG)

Anything not listed in the schema files is out of scope for the KG paper path
(including older research-only fields and middle-/high-school-only priority
flags).

---

## Track B only — where full cleaned files come from

District SIS dumps are not simulator inputs. Under a DUA, build cleaned
student / program / school tables that follow
[KG_VARIABLE_DICTIONARY.md](KG_VARIABLE_DICTIONARY.md), then run the adapter
so columns match Track A (and drop any extras).

More path detail: [DATA_SETUP.md](DATA_SETUP.md), [PIPELINE.md](PIPELINE.md).
