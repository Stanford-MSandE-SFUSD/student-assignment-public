# Kindergarten variable dictionary

Public description of how each column in the [KG schema](KG_SCHEMA.md)
(`schemas/kg_*.txt`) relates to district choice / demographics / geography
inputs. For district-cleaned (Track B) data, this is what the simulator expects
and, at a high level, how those fields are obtained.

It does **not** ship confidential extracts, dump filenames, or columns outside
the schema. DUA file layouts vary by year; map whatever extracts you receive
into these semantics, write KG-oriented CSVs, then run
`[adapt_to_kg_schema.py](../scripts/preprocessing/adapt_to_kg_schema.py)` if
you still have extras.

Source-of-truth column order: `[schemas/](../schemas/)`.

---

## Source families (conceptual)


| Family                        | Typical contents                                                                                                    |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **Choice prerun — requests**  | One row per ranked program: student id, school, program code, rank, grade, lottery / cohort strings, priority flags |
| **Choice prerun — students**  | One row per student: lat/lon, designation lottery, pathway / feeder fields                                          |
| **Choice postrun — requests** | Assigned or requested outcomes (school, program, rank, designation)                                                 |
| **Choice postrun — students** | Distance, attendance-area school, CTIP flag, etc.                                                                   |
| **Demographics / enrollment** | Ethnicity, language, SPED, enrolled school, zip (year-dependent extracts)                                           |
| **Geography**                 | Census block polygons; block↔block-group↔tract crosswalk; optional attendance-area polygons                         |
| **Block socioeconomic joins** | Block-level free/reduced lunch rates; median household income by block                                              |


Under a DUA, build cleaned tables that implement the rules below (privately),
then align to the schema with the adapter if needed.

---

## Students (`schemas/kg_student_columns.txt`)

### Identity and grade


| Column      | How it is produced                                                                            |
| ----------- | --------------------------------------------------------------------------------------------- |
| `studentno` | Student id from choice / demographics extracts (string normalized in cleaning).               |
| `grade`     | From prerun requests; `K` → `KG`; later standardized to zero-padded codes for numeric grades. |


### Round-1 preference lists (from prerun requests)

Built by grouping request rows by `studentno` (sorted by rank):


| Column               | How it is produced                                                           |
| -------------------- | ---------------------------------------------------------------------------- |
| `r1_ranked_idschool` | List of `idschool` in rank order.                                            |
| `r1_listed_ranks`    | List of `rank` values.                                                       |
| `r1_programs`        | List of `programcode` in rank order.                                         |
| `r1_randomnumber`    | Per-request lottery number, aggregated into a list with the other R1 fields. |
| `r1_cohortstring`    | Cohort / priority string from requests (`NaN` → `""`), aggregated as a list. |


### Round-1 assignment / distance (from postrun)

Restrict to the relevant request-status subset, then rename with an `r1`_ prefix:


| Column             | How it is produced                           |
| ------------------ | -------------------------------------------- |
| `r1_idschool`      | Assigned / resulting school id.              |
| `r1_programcode`   | Program code.                                |
| `r1_rank`          | Rank (missing → 0).                          |
| `r1_isdesignation` | Designation indicator from postrun requests. |
| `r1_distance`      | Distance from postrun student file.          |


### Round-2 placeholders


| Column                                                                                                                                                                                                     | How it is produced                                                                                                                                         |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `r2_ranked_idschool`, `r2_listed_ranks`, `r2_programs`, `r2_randomnumber`, `r2_cohortstring`, `r2_designation_randomnumber`, `r2_idschool`, `r2_programcode`, `r2_rank`, `r2_isdesignation`, `r2_distance` | Filled when round-2 extracts exist (same transforms as R1 with `r2_`). For PNAS paper inputs they may be empty; the adapter can create empty placeholders. |


### Designation / pathway / feeder (from prerun students)


| Column                        | How it is produced                                                                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `r1_designation_randomnumber` | Prerun student `randomnumber` renamed.                                                                                               |
| `requestprogramdesignation`   | From prerun student file.                                                                                                            |
| `previous_pathway`            | From `nextprogramcode`.                                                                                                              |
| `msf`                         | From feeder-school field (`idfeederschool`); may be remapped through an ES→MSF table. Often unused / empty for KG after the adapter. |


### Location


| Column                  | How it is produced                                                                                                                                                      |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `latitude`, `longitude` | From prerun students; `NULL` / invalid coords cleared; values outside a SF-ish lat/lon window set to missing; `(0,0)` treated as missing before geo joins.              |
| `zipcode`               | From demographics (and applicant fallbacks); codes like `NOZIP` / `CA` → 0; numeric. Missing AA/zip may be filled via student point-in-polygon against a zip shapefile. |
| `idschoolattendance`    | Attendance-area school from postrun students; may be filled from later rounds or inferred from lat/lon vs attendance-area polygons.                                     |


### Priorities (tiebreakers)

From prerun **request** flag codes, mapped to the school (or program) id on that row, then aggregated across the student’s list and across rounds into one list column:


| Column             | Code → value rule                                         | Result shape       |
| ------------------ | --------------------------------------------------------- | ------------------ |
| `sibling`          | `S` → that row’s `idschool`, else empty                   | List of school ids |
| `currentlp`        | `CL` → `idschool`                                         | List               |
| `currentlpsibling` | `CLS` → constructed `program_id` (`school-program-grade`) | List               |
| `aaprek`           | `AAP` → `idschool`                                        | List               |
| `prek`             | `PK` → `idschool`                                         | List               |
| `aa`               | `AA` → `idschool`                                         | List               |


After round-wise `r*_` lists exist, **merge rounds** into the unprefixed
columns above (union of non-empty entries).


| Column  | How it is produced                             |
| ------- | ---------------------------------------------- |
| `ctip1` | From postrun student CTIP field; coded to 0/1. |


### Demographics and enrollment


| Column               | How it is produced                                                                                                                                                                                                                                                                                               |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `homelang`           | Home / primary language from demographics or CBEDS-style applicant files (year-dependent column names).                                                                                                                                                                                                          |
| `englprof`           | English proficiency from demographics (`englprof_desc` or equivalent).                                                                                                                                                                                                                                           |
| `sped`               | Special education flag from demographics (`sped` / `speced`).                                                                                                                                                                                                                                                    |
| `resolved_ethnicity` | From demographics / applicant race–ethnicity fields; missing filled from alternate applicant file when present; **canonical labels** applied (e.g. `Two or More` → `Two or More Races`, `Hispanic` → `Hispanic/Latino`, `African American` → `Black or African American`, decline/unspecified variants aligned). |
| `enrolled_idschool`  | Enrolled school from demographics (name→id translation when needed) or CBEDS `schno`.                                                                                                                                                                                                                            |
| `final_school`       | Last non-missing `r{k}_idschool` over rounds (high round first); else 0.                                                                                                                                                                                                                                         |
| `num_ranked`         | Count of **unique** school ids across all `r*_ranked_idschool` lists.                                                                                                                                                                                                                                            |


### Geography and block SES joins


| Column                              | How it is produced                                                                                                                            |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `census_block`                      | Spatial join of student lat/lon to 2010 census block polygons (`geoid10`).                                                                    |
| `census_blockgroup`, `census_tract` | Lookup from block via a block↔BG↔tract crosswalk.                                                                                             |
| `freelunch_prob`                    | Join block id to a block-level free/(FRPM) rate table (construction differs by year: share of FRPM vs students on block, or a free_% column). |
| `reducedlunch_prob`                 | Same join; may be 0 when only a combined FRPM rate is available.                                                                              |
| `median_hh_income`                  | Join block id to a block median household income table (currency formatting stripped; non-numeric → missing).                                 |


---

## Programs (`schemas/kg_program_columns.txt`)


| Column            | How it is produced                                                                      |
| ----------------- | --------------------------------------------------------------------------------------- |
| `program_id`      | `{school_id}-{program_type}-{grade}` (string).                                          |
| `school_id`       | From capacity extract `idschool`.                                                       |
| `program_type`    | From capacity extract `programcode`.                                                    |
| `capacity`        | Round-1 seats from prerun **capacity** extract (`seats`).                               |
| `programno`       | Sequential index `1…N` after filtering to the grade.                                    |
| `r1_assigned`     | Count of cleaned students with that R1 program assignment (from cleaned student table). |
| `r1_noenroll`     | Among those, count with missing `enrolled_idschool`.                                    |
| `r1_first_choice` | Count of prerun request rows with `rank == 1` for that `program_id`.                    |


Grade filter: keep the target grade only (`K` → `KG` when needed).

---

## Schools (`schemas/kg_school_columns.txt`)


| Column                                                                                    | How it is produced                                                                                      |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `school_id`, `school_name`, `school_name_long`, `lat`, `lon`, `zip`, `category`, `grades` | From a schools master list (filtered to elementary grade spans for KG).                                 |
| `cap_lb`                                                                                  | Optional capacity lower bound when available from school metadata.                                      |
| `greatschools_rating`                                                                     | Merged from an auxiliary school ratings table when available.                                           |
| `ela_color`, `math_color`, `chronic_color`, `suspension_color`                            | Dashboard color categories joined by school id.                                                         |
| `index`                                                                                   | Row index after cleaning (may be present in rehaused exports).                                          |
| `Block`, `BlockGroup`, `Tract`                                                            | Point-in-polygon of school lat/lon to census blocks, then crosswalk (same geography stack as students). |


Attendance-area polygons may be used when building related fields; they are not separate KG schema columns.

---

## Track A (synthetic)

Synthetic packs should **emit the same column names and value conventions**
(lists, ethnicity labels, `KG` grade, `program_id` pattern). They do not need
to replay district dumps; they must be interchangeable with adapted Track B
files at the schema boundary.

---

## Related docs

- [KG_SCHEMA.md](KG_SCHEMA.md) — keep-lists and adapter
- [DATA_SETUP.md](DATA_SETUP.md) — paths and tracks
- [PIPELINE.md](PIPELINE.md) — clone → simulate

