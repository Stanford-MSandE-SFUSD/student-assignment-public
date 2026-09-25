# How the synthetic 2324 dataset was anonymized

This document is the disclosure record for `data/synthetic_2324/`. It states
what real information the released files do and do not contain, the mechanisms
used to protect it, and the fidelity that was deliberately given up.

The design priority was reducing what the release reveals about any one
applicant, even when that costs fidelity to the source extract. Measurable
costs are listed under "What fidelity was given up" and quantified in
[FIDELITY.md](FIDELITY.md).

## The short version

No record in the released dataset is derived from, or corresponds to, any real
applicant. The generator never sees a student record. It is handed three
committed artifacts — a file of **aggregate statistics**, a file of **public
geography**, and a **tract-level CTIP1** table — and samples an entirely new
cohort from them.

Three properties follow:

1. **There is no record-level linkage.** Synthetic applicant *i* is not a
   perturbation, swap, or reweighting of any real applicant. Every synthetic
   attribute is an independent draw, so the released dataset contains no row
   whose combination of location, demographics, priorities, and ranked list
   traces back to one household.
2. **Every household location is drawn from public geography.** No real
   coordinate is released, and synthetic homes are placed by 2010 Census child
   population rather than by where applicants lived. Two released tables are
   still shaped by where real applicants lived: which block groups get their
   own socio-economic value (Mechanism 3), and the block-to-ZIP crosswalk in
   the block reference (see "What is in the release that is not synthetic").
3. **Every real statistic that does inform the release is an aggregate.**
   Count-based statistics are noised and suppressed (Mechanism 1). The
   block-group socio-economic values, residual quantiles, FRL bin edges, and
   tract CTIP1 are coarsened but not noised, and a few fallback rates are fixed
   constants. Everything the generator reads is committed — the 156 KB
   `priors/synthetic_priors_2324.json` plus the two reference tables — so that
   is the disclosure surface of the dataset itself. Separately, FIDELITY.md and
   this document quote rounded real-cohort statistics without noise (see "Real
   statistics quoted in the documentation").

## The two-stage pipeline

| Stage | Script | Reads | Writes |
| --- | --- | --- | --- |
| 1. Extract | `scripts/generators/extract_synthetic_priors.py` | confidential Table-1 student file (`r1_filter_student_without_specialprogs_2324.csv`), SFUSD block database, public census block shapefile | `priors/synthetic_priors_2324.json`, `reference/block_reference_2324.csv`, `reference/ctip_by_tract_2324.csv` |
| 2. Generate | `scripts/generators/generate_synthetic_dataset.py` | the stage-1 outputs, plus the school and program tables | `student_2324_synthetic.csv`, `programs_without_specialprogs_2324.csv`, `zones/concept1zones.csv` |

Stage 1 requires data access and cannot be re-run from a public clone. Stage 2
can: it is a deterministic function of its committed inputs and a published
seed (`PUBLIC_SEED` in `generate_synthetic_dataset.py`), so any reader can
reproduce the dataset bit-for-bit, or draw a different cohort with a different
seed. The two stages use unrelated seeds; only stage 2's is public (see
Mechanism 1, item 5). Disclosure risk in the released records is therefore bounded by
what the generator reads: `synthetic_priors_2324.json` — 41 aggregate statistic
families, listed under `meta.query_families` in that file — and the two
reference tables.

## Mechanism 1: noise and suppression on every count

Every count-based statistic in the priors file was produced by:

1. **Laplace noise.** Each released cell gets independent `Laplace(1/ε)` noise
   with `ε = 0.5`, i.e. noise of scale 2 applicants. The scale assumes one
   applicant changes one cell by 1. That holds for per-applicant histograms
   (applicants per area, list-length bins, rank-1 school), but not for
   statistics counted per choice — program-type shares, citywide tail
   popularity, same-school repeats, pathway and pre-K counts by school — or for
   the per-position mean distances, where one applicant can move several cells,
   or a value by more than 1. For those, the noise per applicant is smaller
   than the nominal scale. Only cells present in the data are noised, so a
   released cell implies its true count was nonzero.
2. **Small-cell suppression.** A cell whose *noisy* count falls below
   `min_cell = 5` is dropped entirely. Because suppression is applied to the
   noisy count, whether a true count of 5 survives is itself random.
3. **Smoothing toward a coarser parent.** What survives is blended with a
   parent distribution (citywide, or the next-coarser stratum), which is given
   exactly the mass that suppression removed plus a `prior_floor = 2`
   applicant-equivalents. Thin attendance areas therefore fall back toward the
   city pattern; denser areas keep more of their own shape.
4. **Floors on both tails of a rate.** A conditional rate is reported only if
   its denominator clears `min_rate_denominator = 20` and both its numerator
   and its complement clear `min_cell = 5`. The floors are checked on the
   **true** counts; the numerator and denominator are then noised separately.
   Otherwise the rate falls back to its parent or to a fixed constant, so a
   fallback value itself reveals that the true counts were below the floor. This is why, for example, the language-designation request rate is
   reported for the larger home-language groups (English, Spanish,
   Cantonese/Mandarin, Korean, other) but falls back to a fixed 0.25 for
   Arabic, Japanese, and Russian speakers. For per-area rates the
   fallback is the pooled rate over the *suppressed* areas, not the overall
   citywide rate: for a rare priority the areas that clear the floor are
   exactly the high ones, so using the overall rate for the rest would inflate
   the total.

5. **A private noise seed.** All of the noise above is drawn from one seeded
   generator. Anyone holding that seed could replay the draws and subtract them,
   recovering exact counts, so the stage-1 seed is a 128-bit random value held
   by the data custodians. It is not in the repository, the priors file, or any
   log, and `extract_synthetic_priors.py` has no default for it. It is
   unrelated to the public stage-2 seed.

### Composed privacy budget

Query labels in the priors file have the form `family | stratum`. The ledger
charges each family one ε, on the assumption that its strata are disjoint
subsets of applicants (one attendance area, one ethnic group, one list-length
bin) and so compose in parallel. That gives a nominal **ε = 20.5** across 41
families and 462 histograms.

The nominal figure understates the true composition and should not be cited as
a differential-privacy guarantee:

- Several families mix a citywide query with per-area or per-group queries over
  the same applicants: rank-1 school, list-length bins, program type, reported
  and coarse ethnicity, demographics observed, and the sibling and pre-K rates.
- Each conditional rate spends two noisy draws (numerator and denominator), not
  one.
- The per-choice statistics in item 1 have sensitivity above 1.

Read ε = 20.5 as bookkeeping for how much noise was added, not as a bound on
what the release reveals.

Releases listed under `meta.non_laplace_releases` are outside that ledger.
They include block-group socio-economic means and residual quantiles (Mechanism
3), snapped `frl_bin_edges`, and tract-level CTIP1. The fixed fallback
constants (item 4) and the per-attribute missing-value rates are also outside
the ledger. Primary protections for the
release as a whole remain structural: no record-level carry-through, public
geography for locations, small-cell suppression, and coarsening, with Laplace
noise on count aggregates.

## Mechanism 2: locations synthesized from public geography

Applicant coordinates are the most re-identifying field in the source data.
In the source cohort, 2,271 distinct census blocks are occupied and **1,248 of
them hold exactly one applicant** — a block identifier is close to a household
identifier. None of that structure is released.

Instead, for each attendance area *a*:

1. The area's number of applicants `n_a` is taken from the (noised) count.
2. `n_a` census blocks are drawn **with replacement** from *all* blocks of that
   attendance area — not only occupied ones — with probability proportional to
   the block's **2010 Census population under 18**, plus a floor of 0.25 so
   that every block in the area is reachable.
3. Within the drawn block, a point is drawn uniformly from a disc of radius
   `0.7 × sqrt(land area / π)` around the block's published TIGER internal
   point.

Every input here is public: the 2010 Census block layer (DataSF), 2010 Census
population counts, and SFUSD's elementary attendance-area boundaries. CTIP1 is
joined later from the tract table, not from a per-block flag.
The weights come from where children live in the 2010 Census, not from where
applicants live, so the released coordinates follow the city's residential
pattern and do not encode applicant addresses. A synthetic household can sit on
a block that no real applicant occupied.

`census_block`, `census_blockgroup`, `census_tract`, and `zipcode` are the
identifiers of the *drawn* block, which is why the dataset still works with the
block-group-level zone files in `data/zones/`.

## Mechanism 3: socio-economic attributes coarsened to block groups

`freelunch_prob`, `reducedlunch_prob`, and `median_hh_income` are the
block-level socio-economic fields the **shipped** student table carries
(reserves and evaluators read FRL from the lunch probabilities; income
reserves/metrics use `median_hh_income`). In the confidential source, lunch
probabilities arrive as one value per census block. Given the one-applicant
blocks above, a per-block free-lunch probability of 0.0 or 1.0 can disclose a
single family's circumstances. Attributes are therefore matched at the
**census block group** level:

- Each lunch probability is averaged over the blocks of its census block group
  (the usual census disclosure unit, and already the native resolution of
  `median_hh_income`).
- A block group must contain at least 3 distinct observed blocks **and** at
  least 5 applicants to get its own value; otherwise it falls back to its
  tract, then to the citywide mean.
- Values are rounded to 3 decimals. They are **not** noised, and which block
  groups clear the floor (rather than falling back to their tract) reveals
  where applicants were thin.

Coarsening to block groups retains about two thirds of the block-level variance
for free-lunch probability and most of the between-neighbourhood variation that
segregation metrics depend on, because those metrics average over students from
many block groups.

To keep marginal spread from collapsing, the citywide **quantiles of the
within-block-group residual** are also released (one shape per attribute,
pooled over ~2,300 blocks). Each synthetic block draws one residual from that
shape, so neighbouring blocks can differ the way real data does. That residual
is noise and does not encode the true residual for that block. The quantiles
are real and un-noised, and the extreme ones are single-block values.

`ctip1` is joined from `reference/ctip_by_tract_<year>.csv`: one binary
CTIP1 flag per census tract, collapsed from the SFUSD block workbook (CTIP is
constant within tract). It is **not** stored on the block reference file.

## Mechanism 4: features sampled in independent layers

The joint distribution of (attendance area × reported ethnicity × home language
× priorities × ranked list) is where re-identification risk concentrates: taken
together those fields are close to unique. The generator therefore never samples
that joint. Each feature is a separate draw:

- **Race.** A *coarse* group (Asian / Hispanic / White / Black / Two or More /
  Decline to State / Pacific Islander-Other) is drawn from the attendance
  area's distribution, tilted by the CTIP1 effect *within* areas. That tilt is
  an indirectly standardized ratio — observed counts over counts expected from
  each area's own distribution — because the area-level distribution already
  carries the between-area part of the race/CTIP1 association, and applying a
  raw citywide ratio on top would count it twice. The reported label
  is then drawn from the **citywide** distribution within that coarse group.
  The coarse groups match `map_ethnicity` in
  `student_assignment/evaluation/short_match_evaluator.py`, so the AALPI
  metrics see the categories they expect. Pacific Islander, American Indian and
  residual labels — about 0.5% of the cohort — are pooled and drawn citywide
  rather than by area; cell counts are too small to place geographically without
  pointing at individuals.
- **Home language.** Drawn conditional on the coarse race group and CTIP1
  status, citywide.
- **English proficiency.** Drawn conditional on the home language, citywide.
- **Special education status.** A Bernoulli draw at the CTIP1-specific rate.
- **Missing demographics.** In the source extract, ethnicity, language,
  proficiency, special-education status, and enrolment are missing *together*
  for applicants who never enrolled in the district. One area-level rate
  reproduces that pattern.

Because the layers are independent, an unusual synthetic combination is a
sampling artifact rather than a signal that some real applicant had that
combination.

## Mechanism 5: ranked lists rebuilt, never copied

No real ranked list is released, and no synthetic list is a copy, truncation, or
permutation of one. Lists are constructed position by position:

- **Length** comes from the attendance area's length histogram (14 bins, noised
  and suppressed, smoothed to citywide), tilted by the same kind of
  within-area CTIP1 effect — CTIP1 applicants file markedly shorter lists —
  with the exact length drawn uniformly inside the chosen bin.
- **Position 1** comes from the attendance area's noised, suppressed rank-1
  counts, smoothed toward a *distance-localized* citywide prior
  `citywide(j) × exp(-β · miles)`. Areas whose cells survived suppression keep
  their real pattern; areas whose cells did not fall back to schools near the
  synthetic household rather than to the city at large.
- **Positions 2 and beyond** come from the **citywide** popularity of each
  school times a distance kernel, sampled without replacement. Per-area tails
  are made of one- and two-applicant cells and are never used. The decay is
  fitted, by bisection, so that the mean home-to-school distance at each list
  position matches the single aggregate moment released for that position.
- **Program types** are drawn from the citywide
  `P(program type | home-language group)` table, restricted to the pathways
  each school offers, with an availability correction fitted so the overall
  type shares match. Pathways come from the published programs table, plus any
  program type that at least `min_cell` applicants ranked at that school
  (checked on a noised count), so special programs behave as the simulator
  expects.
- **Priorities.** Sibling and attendance-area pre-K priorities are drawn at
  per-area rates, and citywide pre-K and current-language-pathway priorities at
  citywide rates. They are then forced into the list, which is how real lists
  behave (99% of applicants with a sibling rank that sibling's school, 92% of
  them first).
- **Same-school pairs.** A quarter of real applicants rank two programs at one
  school, usually an immersion pathway plus general education, and 7% of all
  choices are such a repeat. These are added as a final pass at the released
  citywide rate, and the program-type weights are re-fitted around them so the
  overall type shares stay on target.
- **`r1_cohortstring`** is fully determined by those priority flags and is
  recomputed, not copied.

## Mechanism 6: identifiers and outcomes regenerated

- `studentno` is a fresh sequential integer from 1,000,000. The source
  identifiers (of the form `2324-8880xxxxx`) do not appear anywhere in the
  release, and there is no crosswalk.
- All lottery numbers (`r1_randomnumber`,
  `r1_designation_randomnumber`) are fresh uniform draws.
- Round-1 outcomes (`r1_idschool`, `r1_programcode`, `r1_rank`,
  `r1_distance`) are produced by **running deferred acceptance** on the
  synthetic lists, priorities, and the real program capacities, with a single
  fresh lottery. They are produced by the synthetic match, not taken from the
  district's assignment.
- `final_school` / `enrolled_idschool` are drawn from the round-1 outcome plus
  the citywide "stayed at the round-1 school" rate.

## What is in the release that is not synthetic

Four inputs are real. They are school- or geography-level tables with no
applicant rows. They are listed here so a reader can remove them if
a particular data agreement requires it:

| File | What it is | Why it is safe |
| --- | --- | --- |
| `Cleaned/schools_rehauled_2324.csv` | 72 schools: name, coordinates, ZIP, category, grade span, capacity floor, GreatSchools rating, CA Dashboard colors | School-level public facts; no applicant data. The outcome columns are not present. |
| `programs_without_specialprogs_2324.csv` | 129 programs: school, pathway, capacity | Published program offerings and seat counts. The outcome columns (`r1_assigned`, `r1_first_choice`) are **recomputed from the synthetic cohort**, so no real assignment counts are released. (`r1_noenroll` is not shipped.) |
| `reference/block_reference_2324.csv` | 7,319 census blocks: block/block group/tract ids, ZIP, attendance area, 2010 Census population, TIGER internal point, land area | Census products and SFUSD attendance-area boundaries. Contains no student counts and no CTIP flag. The ZIP column is applicant-derived: each block where applicants lived gets its most common applicant ZIP, and other blocks take the ZIP of the nearest observed block. ZIP boundaries are public, but which blocks were observed is not. |
| `reference/ctip_by_tract_2324.csv` | One row per census tract with binary `ctip1` | Tract-level CTIP1 collapsed from the SFUSD block workbook (constant within tract). Stage 2 joins block → tract → CTIP1. |

`zones/concept1zones.csv` is generated, not copied: the status-quo zone map is
one zone per attendance area, which is fully determined by the list of
attendance-area school ids.

## What fidelity was given up

These are the deliberate costs of the choices above. All are quantified in
[FIDELITY.md](FIDELITY.md).

1. **Within-block-group socio-economic variation is synthetic.** The
   block-level spread of `freelunch_prob` is recovered in distribution; which
   specific block is high or low within a block group is noise. Analyses that
   need true block-level attribute geography will not reproduce.
2. **The race-to-poverty gradient is attenuated.** Race is drawn from
   attendance-area distributions rather than block-level ones, and attributes
   are coarsened, so the synthetic gap in mean block free-lunch probability
   between AALPI and other applicants is 0.12 against 0.18 in the source —
   roughly two-thirds of the real gradient. Absolute segregation levels on this
   dataset are compressed; use it for policy comparisons, not for quoting
   district segregation magnitudes.
3. **Rare categories are placed citywide.** Pacific Islander, American
   Indian, and rare home languages are not localized. Analyses restricted to a
   small demographic group in a specific area are not supported.
4. **Lists match marginals, a distance profile, and same-school pairs.**
   Other higher-order co-occurrence (for example two specific language programs
   at different schools) is not modeled. A choice model fit here can recover
   school and distance effects; idiosyncratic substitution patterns will not.
   Same-school repeats are always placed adjacently (69% of real repeats sit
   that way).
5. **First choices lean slightly more local than reality** (28.6% versus 27%
   for the applicant's own attendance-area school), from localizing the rank-1
   fallback prior.
6. **Rounds 2 and 4 are not modeled.** The `r2_*` columns are present and empty;
   the `r4_*` columns are dropped. The source cohort had round-2 lists for 24%
   of applicants. All committed configs for this year run with `r1-only: true`.
7. **Round-1 outcomes are from synthetic DA, not the district round.**
   Deferred acceptance on synthetic lists gives a slightly better rank
   distribution than the real round (71.5% versus 64% of listed applicants
   offered their first choice). Offers land on the applicant's own list at
   about the same rate (92.7% versus 93%).
8. **No choice-model utility matrix is shipped.** Configs with
   `utility-model.enable: true` need an `estimates_*.csv` keyed by
   `studentno`, estimated for the synthetic cohort with the SFUSD-Choice code.
   Configs with `utility-model.enable: false` (ranked lists in the dataset) run
   as-is.

## Real statistics quoted in the documentation

These are real-cohort figures published without noise, outside the priors file
and the ledger. Each is a rounded, cohort-wide aggregate:

- The **Source (coarsened)** column of [FIDELITY.md](FIDELITY.md): applicant
  count rounded to 10, shares to 2 decimals, distances to 2 decimals.
- Figures in this document: the counts of occupied and single-applicant census
  blocks (Mechanism 2), the sibling-ranking rates and same-school-pair rates
  (Mechanism 5), the free-lunch gradient and own-area first-choice share, the
  round-2 share, and the round-1 comparison rates ("What fidelity was given
  up").

## Residual risk

- A cell that survives suppression has a *noisy* count of at least five; its
  true count can be as low as one or two. It is still an area-level fact — for
  example that a few people in that area ranked a particular school first —
  but in a thin area it can concern very few families.
- The Laplace noise protects counts only while the stage-1 seed stays secret.
  If it leaks, the noise can be replayed and subtracted, and the priors revert
  to exact (still suppressed and coarsened) aggregates.
- Someone who already holds confidential data could match a synthetic record’s
  block group to real block-group attributes; that does not recover an
  individual applicant, because the rest of the synthetic record was not drawn
  from that block group’s real applicants.
- A released row is a draw from aggregates, so it is not evidence that a
  particular child applied.

## Reproducing

```bash
# Stage 2 only; runs from a public clone.
uv run python scripts/generators/generate_synthetic_dataset.py \
    --data-dir data/synthetic_2324 --year 2324
```

```bash
# Stage 1; requires access to the confidential SFUSD data tree.
# Needs the custodians' private noise seed; see the script's --help for the
# exact inputs that recreate the committed priors.
uv run python scripts/generators/extract_synthetic_priors.py \
    --sfusd-root <SFUSD_DATA_PATH> \
    --student-csv <SFUSD_DATA_PATH>/Data/Cleaned/r1_filter_student_without_specialprogs_2324.csv \
    --reuse-block-reference data/synthetic_2324/reference/block_reference_2324.csv \
    --profile joint_frl_eth --variant joint_v4_blend1 \
    --seed-file <private seed file> \
    --out-dir data/synthetic_2324 --year 2324
```

Privacy parameters live in the constants block at the top of
`extract_synthetic_priors.py` and are echoed into `meta` in the priors file:
`laplace_epsilon_per_family`, `min_cell`, `min_rate_denominator`,
`prior_floor`, `tilt_cap`, `min_blockgroup_blocks`,
`min_blockgroup_students`, `attribute_decimals`.
