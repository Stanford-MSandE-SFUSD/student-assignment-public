# How the synthetic 2324 dataset was anonymized

This document is the disclosure record for `data/synthetic_2324/`. It states
what real information the released files do and do not contain, the mechanisms
used to protect it, and the fidelity that was deliberately given up.

The design rule throughout was **anonymity first**: wherever a choice existed
between matching the source data more closely and reducing what the release
reveals about an individual applicant, the release was chosen. The measurable
consequences are listed in "What fidelity was given up" below and quantified in
[FIDELITY.md](FIDELITY.md).

## The short version

No record in the released dataset is derived from, or corresponds to, any real
applicant. The generator never sees a student record. It is handed two
committed artifacts — a file of **aggregate statistics** and a file of **public
geography** — and samples an entirely new cohort from them.

Three properties follow:

1. **There is no record-level linkage.** Synthetic applicant *i* is not a
   perturbation, swap, or reweighting of any real applicant. Every synthetic
   attribute is an independent draw, so the released dataset contains no row
   whose combination of location, demographics, priorities, and ranked list
   traces back to one household.
2. **Every household location is synthesized from public data only.** No real
   coordinate, and no real census block occupancy, enters the release.
3. **Every real statistic that does inform the release is an aggregate**, and
   each one passed through noise addition, small-cell suppression, and/or
   geographic coarsening before being written to disk. Those statistics are
   committed in full as `priors/synthetic_priors_2324.json`, so the entire
   disclosure surface of this release is a single auditable 230 KB file.

## The two-stage pipeline

| Stage | Script | Reads | Writes |
| --- | --- | --- | --- |
| 1. Extract | `scripts/generators/extract_synthetic_priors.py` | confidential `student_2324.csv`, SFUSD block database, public census block shapefile | `priors/synthetic_priors_2324.json`, `reference/block_reference_2324.csv` |
| 2. Generate | `scripts/generators/generate_synthetic_dataset.py` | the two stage-1 outputs, plus the school and program tables | `student_2324_synthetic.csv`, `programs_without_specialprogs_2324.csv`, `zones/concept1zones.csv` |

Stage 1 requires data access and cannot be re-run from a public clone. Stage 2
can: it is a deterministic function of its committed inputs and a seed, so any
reader can reproduce the dataset bit-for-bit, or draw a different cohort with a
different seed.

The split is the point. Because stage 2 is pure post-processing of stage 1's
output, any disclosure risk in the released records is bounded by the risk in
`synthetic_priors_2324.json` — which is 42 aggregate statistic families, all
listed under `meta.query_families` in that file.

## Mechanism 1: noise and suppression on every count

Every count-based statistic in the priors file was produced by:

1. **Laplace noise.** Each cell of each histogram gets independent
   `Laplace(1/ε)` noise with `ε = 0.5`, i.e. noise of scale 2 applicants. One
   applicant can move one cell of one histogram by 1, so the sensitivity is 1.
2. **Small-cell suppression.** A cell whose *noisy* count falls below
   `min_cell = 5` is dropped entirely. Because suppression is applied to the
   noisy count, whether a true count of 5 survives is itself random.
3. **Smoothing toward a coarser parent.** What survives is blended with a
   parent distribution (citywide, or the next-coarser stratum), which is given
   exactly the mass that suppression removed plus a `prior_floor = 2`
   applicant-equivalents. A thin attendance area therefore degrades gracefully
   to the city pattern instead of being reconstructed from a handful of
   applicants, while a relationship the data genuinely pins down is not blurred
   for the sake of it.
4. **Floors on both tails of a rate.** A conditional rate is reported only if
   its denominator clears `min_rate_denominator = 20` and both its numerator
   and its complement clear `min_cell = 5`. Otherwise it falls back to its
   parent. This is why, for example, the language-designation request rate is
   reported for Spanish and Cantonese/Mandarin speakers but falls back to the
   citywide rate for Japanese and Korean speakers. For per-area rates the
   fallback is the pooled rate over the *suppressed* areas, not the overall
   citywide rate: for a rare priority the areas that clear the floor are
   exactly the high ones, so using the overall rate for the rest would inflate
   the total.

### On the composed epsilon

Query labels in the priors file have the form `family | stratum`. Queries in
one family run on **disjoint** subsets of applicants — one attendance area, one
ethnic group, one list-length bin — so they compose in parallel and cost the
family one ε. Across the 42 families, sequential composition gives a composed
**ε = 21.0** for the 497 individual histograms.

Be clear about what that number is and is not. It is honest bookkeeping: the
pipeline really is a Laplace mechanism applied 42 times, and ε = 21.0 is the
correct basic-composition total. It is **not** a tight or strong formal
guarantee, and this release should not be described as "differentially private
with ε = 21" as if that alone bounded the risk. Two caveats:

- Two releases are **not** Laplace-protected at all and are excluded from the
  ε accounting (they are listed under `meta.non_laplace_releases`): the
  block-group attribute means and the within-block-group residual quantiles.
  These are protected by geographic coarsening instead — see Mechanism 3.
- The operative protections are structural: no record-level carry-through,
  public-only geography, small-cell suppression, and coarsening. The noise is a
  safeguard layered on top of those, not a substitute for them.

## Mechanism 2: locations synthesized from public geography

Applicant coordinates are the most re-identifying field in the source data, and
they are the field this release treats most conservatively. In the source
cohort, 2,271 distinct census blocks are occupied and **1,248 of them hold
exactly one applicant** — a block identifier is close to a household
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
population counts, and SFUSD's published elementary attendance-area boundaries.
The weights come from where *children* live per the decennial census, not from
where *applicants* live. Consequently the released coordinates reveal the
residential shape of the city — which is already public — and nothing about any
applicant's address. A synthetic household can sit on a block that no real
applicant lived on, and frequently does.

`census_block`, `census_blockgroup`, `census_tract`, and `zipcode` are the
identifiers of the *drawn* block, which is why the dataset still works with the
block-group-level zone files in `data/zones/`.

## Mechanism 3: socio-economic attributes coarsened to block groups

`freelunch_prob`, `FRL Score`, `AALPI Score`, `Academic Score`, and `HOCidx1`
arrive in the source data as one value per census block. Given the one-applicant
blocks above, a per-block free-lunch probability of 0.0 or 1.0 can disclose a
single family's circumstances, so per-block values are not released.

This is the answer to "should FRL match at the block level or the attendance
area level?": **neither — it matches at the census block group level.**

- Each attribute is averaged over the blocks of its **census block group**, the
  standard census disclosure-avoidance unit and already the native resolution
  of `N'hood SES Score` and `median_hh_income`.
- A block group must contain at least 3 distinct observed blocks **and** at
  least 5 applicants to get its own value; otherwise it falls back to its
  tract, then to the citywide mean.
- Values are rounded to 3 decimals.

Coarsening to block groups retains about two thirds of the block-level variance
(67% for free-lunch probability, 70% for the AALPI score, 82% for the home
opportunity index) and, importantly, nearly all of the *between-neighbourhood*
variation that the segregation metrics depend on — because those metrics average
over students drawn from many block groups.

To avoid releasing a dataset whose attributes are visibly over-smoothed, the
citywide **quantiles of the within-block-group residual** are also released (one
shape per attribute, pooled over ~2,300 blocks). Each synthetic block draws one
residual from that shape and keeps it, so the attribute remains a property of
the block, varies between neighbouring blocks the way real data does, and
recovers the real marginal spread. The residual a synthetic block receives is
pure noise and carries no information about that block.

`ctip1` is the published SFUSD CTIP 2013 block designation, taken directly.

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
  rather than by area, precisely because there are too few of them to place
  geographically without pointing at individuals.
- **Home language.** Drawn conditional on the coarse race group and CTIP1
  status, citywide.
- **English proficiency.** Drawn conditional on the home language, citywide.
- **Special education status.** A Bernoulli draw at the CTIP1-specific rate.
- **Missing demographics.** In the source extract, ethnicity, language,
  proficiency, special-education status, and enrolment are missing *together*
  for applicants who never enrolled in the district. One area-level rate
  reproduces that pattern.

Because the layers are independent, an unusual synthetic combination is an
artifact of the sampler, not evidence that a real applicant had it.

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
  each school actually runs, with an availability correction fitted so the
  overall type shares match. School × pathway existence is a published fact
  (the district's enrollment guide), not applicant information.
- **Priorities.** Sibling, pre-K, and language-pathway priorities are drawn at
  area-level rates and then forced into the list, which is how real lists
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
  fresh lottery. They are an emergent property of the synthetic cohort, not a
  copy of the district's assignment.
- `final_school` / `enrolled_idschool` are drawn from the round-1 outcome plus
  the citywide "stayed at the round-1 school" rate.

## What is in the release that is not synthetic

Three inputs are real, and all three are school- or geography-level facts with
no applicant-level content. They are listed here so a reader can remove them if
a particular data agreement requires it:

| File | What it is | Why it is safe |
| --- | --- | --- |
| `Cleaned/schools_rehauled_2324.csv` | 72 schools: name, coordinates, ZIP, category, grade span, capacity floor, GreatSchools rating, CA Dashboard colors | School-level public facts; no applicant data. The outcome columns are not present. |
| `programs_without_specialprogs_2324.csv` | 129 programs: school, pathway, capacity | Published program offerings and seat counts. The three outcome columns (`r1_assigned`, `r1_noenroll`, `r1_first_choice`) are **recomputed from the synthetic cohort**, so no real assignment counts are released. |
| `reference/block_reference_2324.csv` | 7,319 census blocks: block/block group/tract ids, ZIP, attendance area, CTIP 2013 designation, 2010 Census population, TIGER internal point, land area | Census products and published SFUSD boundary and CTIP designations. Contains no student counts of any kind. |

`zones/concept1zones.csv` is generated, not copied: the status-quo zone map is
one zone per attendance area, which is fully determined by the list of
attendance-area school ids.

## What fidelity was given up

These are the deliberate costs of the choices above. All are quantified in
[FIDELITY.md](FIDELITY.md).

1. **Within-block-group socio-economic variation is synthetic.** The
   block-level spread of `freelunch_prob`, `AALPI Score`, `Academic Score`, and
   `HOCidx1` is recovered in distribution but not in place: which specific block
   is high or low within a block group is noise. Analyses that depend on
   block-level (as opposed to block-group-level) attribute geography will not
   reproduce.
2. **The race-to-poverty gradient is attenuated.** Because race is drawn from
   attendance-area distributions rather than block-level ones, and because
   attributes are coarsened, the synthetic gap in mean block free-lunch
   probability between AALPI and other applicants is 0.15 against 0.19 in the
   source — roughly 80% of the real gradient. Segregation levels in
   the synthetic data are real but somewhat compressed; **do not read absolute
   segregation magnitudes off this dataset.** Policy *comparisons*, which is
   what the simulator is for, are much less affected.
3. **Rare categories are citywide, not local.** Pacific Islander, American
   Indian, and rare home languages are distributed citywide. Any analysis
   restricted to a small demographic group in a specific area is meaningless
   here.
4. **Lists reproduce marginals, a distance profile and same-school pairs, not
   other higher-order structure.** Which schools co-occur on a list beyond the
   distance, popularity and same-school effects — a preference for two specific
   language programs at *different* schools, say — is not modeled. A choice
   model estimated on this dataset will recover school and distance effects but
   not idiosyncratic substitution patterns. Same-school repeats are always
   placed adjacently, where 69% of the real ones sit.
5. **First choices lean slightly more local than reality** (28.6% versus 26.7%
   for the applicant's own attendance-area school), a side effect of localizing
   the rank-1 fallback prior.
6. **Rounds 2 and 4 are not modeled.** The `r2_*` columns are present and empty;
   the `r4_*` columns are dropped. The source cohort had round-2 lists for 24%
   of applicants. All committed configs for this year run with `r1-only: true`.
7. **Round-1 outcomes are internally consistent but not the district's.**
   Deferred acceptance on synthetic lists gives a slightly better rank
   distribution than the real round (68.9% versus 64.5% of listed applicants
   offered their first choice) and places 8.8% of applicants off their own list
   against 6.8% in reality.
8. **No choice-model utility matrix is shipped.** Configs with
   `utility-model.enable: true` need an `estimates_*.csv` keyed by
   `studentno`, which must be estimated for the synthetic cohort with the
   SFUSD-Choice code. Configs with `utility-model.enable: false` (which use the
   ranked lists in the dataset) run as-is.

## Residual risk

The honest statement of what remains:

- A statistic that survived suppression in a small attendance area still says
  something, in aggregate, about that area — for example that at least a few
  applicants in a 15-applicant area ranked a particular school first. That is
  an area-level fact about a group of at least five (noisy) applicants, not an
  individual one, and it is the intended granularity of the release.
- An adversary holding the confidential data could link a synthetic record's
  block group back to real block-group attributes. That linkage yields no
  individual information, because the synthetic record's other fields were not
  drawn from that block group's real applicants.
- Membership inference against the released records is not meaningful: the
  records are draws from released aggregates, so nothing in a record is
  evidence about whether a particular child applied.

## Reproducing

```bash
# Stage 2 only; runs from a public clone.
uv run python scripts/generators/generate_synthetic_dataset.py \
    --data-dir data/synthetic_2324 --year 2324
```

```bash
# Stage 1; requires access to the confidential SFUSD data tree.
uv run python scripts/generators/extract_synthetic_priors.py \
    --sfusd-root /share/data/school_choice \
    --out-dir data/synthetic_2324 --year 2324
```

Privacy parameters live in the constants block at the top of
`extract_synthetic_priors.py` and are echoed into `meta` in the priors file:
`laplace_epsilon_per_family`, `min_cell`, `min_rate_denominator`,
`prior_floor`, `tilt_cap`, `min_blockgroup_blocks`,
`min_blockgroup_students`, `attribute_decimals`.
