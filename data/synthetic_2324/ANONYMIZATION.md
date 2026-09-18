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
applicant. The generator never sees a student record. It is handed three
committed artifacts — a file of **aggregate statistics**, a file of **public
geography**, and the **published choice model's coefficients** — and samples an
entirely new cohort from them. Household features come from the aggregates and
the geography; the ranked lists come from the model.

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
   disclosure surface of this release is a single auditable 200 KB file.

## The two-stage pipeline

| Stage | Script | Reads | Writes |
| --- | --- | --- | --- |
| 1. Extract | `scripts/generators/extract_synthetic_priors.py` | confidential `student_2324.csv`, SFUSD block database, public census block shapefile | `priors/synthetic_priors_2324.json`, `reference/block_reference_2324.csv` |
| 2. Generate | `scripts/generators/generate_synthetic_dataset.py` | the two stage-1 outputs, the published choice-model coefficients, and the school and program tables | `student_2324_synthetic.csv`, `choice_model/estimates_2324_synthetic.csv`, `programs_without_specialprogs_2324.csv`, `zones/concept1zones.csv` |

Stage 1 requires data access and cannot be re-run from a public clone. Stage 2
can: it is a deterministic function of its committed inputs and a seed, so any
reader can reproduce the dataset bit-for-bit, or draw a different cohort with a
different seed.

The split is the point. Because stage 2 is pure post-processing of stage 1's
output, any disclosure risk in the released records is bounded by the risk in
`synthetic_priors_2324.json` — which is 32 aggregate statistic families, all
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
family one ε. Across the 32 families, sequential composition gives a composed
**ε = 16.0** for the 408 individual histograms.

Be clear about what that number is and is not. It is honest bookkeeping: the
pipeline really is a Laplace mechanism applied 32 times, and ε = 16.0 is the
correct basic-composition total. It is **not** a tight or strong formal
guarantee, and this release should not be described as "differentially private
with ε = 16" as if that alone bounded the risk. Two caveats:

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

## Mechanism 5: ranked lists come from the public choice model

No real ranked list is released, and no synthetic list is a copy, truncation,
or permutation of one. More than that: **almost nothing about what applicants
rank is extracted from the confidential data at all.**

The lists are produced the way the choice model itself produces them. For each
synthetic household, `student_assignment/choice_model/exp8.py` evaluates the
published `exp8` MNL — 109 coefficients over eight feature groups, shipped in
`choice_model/weights_exp8.csv` — against that household's sampled features,
giving a utility for every program. A standard Gumbel shock is added to each
utility and the programs are sorted descending, which is exactly
`Metrics.get_preferences` in SFUSD-Choice-public and amounts to a
Plackett-Luce draw from the fitted model. Truncating that ranking at the
applicant's list length gives the list.

Everything about the *content* of a list is therefore a consequence of public
coefficients applied to synthetic features:

- which schools are ranked, and in what order;
- the mix of general-education and immersion programs;
- how far the ranked schools are from home;
- whether an applicant ranks two programs at the same school;
- whether they rank their own attendance-area school.

Each of those was previously a separately calibrated prior extracted from the
real lists. Ten query families disappeared with them, including the most
granular thing the file used to carry: `rank1_counts_by_aa`, a per-attendance-
area histogram over first-choice schools. Also gone are the citywide tail
popularity, the mean choice distance at each list position, the
program-type-by-home-language table, the same-school repeat rate, and the two
sibling-list-position rates.

Two list-level statistics are still needed, because the model does not supply
them:

- **Length.** The model ranks every program; it says nothing about how many a
  family writes down. Length comes from the attendance area's length histogram
  (14 bins, noised and suppressed, smoothed to citywide), tilted by the
  within-area CTIP1 effect.
- **Priorities.** Sibling, pre-K, and language-pathway priority *rates* are
  still area-level draws. Where the sibling's school is, though, now comes from
  the model too: a softmax over the same utilities with the sibling term itself
  switched off, on the reasoning that siblings attend schools their family
  would plausibly have chosen.

### The choice set is narrowed for generation

The model widens a student's choice set with the program types they were
*observed* to rank. That is reasonable when fitting a likelihood and circular
when generating preferences, so generation uses `ChoiceSetMode.FORWARD`, which
keeps only what home language entitles an applicant to rank. The estimation-time
rule is retained solely for the validation check below.

### The port is verified, not asserted

A re-implementation is only as good as its agreement with the original.
`scripts/generators/validate_choice_model_port.py` recomputes the model's own
released `estimates_2324.csv` for all 4,232 **real** kindergarten applicants
and diffs it cell by cell: maximum absolute difference **1.0e-10** across
380,736 finite cells. The 87 choice-set cells that differ are each shown to be
explained by a language program appearing in `r4_programs` in the current
extract, which the May 2024 extract behind the published matrix evidently
carried in an earlier round.

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
| `choice_model/weights_exp8.csv`, `config_exp8.yaml` | 109 MNL coefficients and their feature specification | The published choice model. Coefficients are estimated over the whole cohort; no individual is recoverable from them. |

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
4. **The lists are only as good as the choice model.** This is the central
   trade of the design, and it cuts three ways:
   * **First-choice demand across schools correlates 0.84** with the source,
     against 0.94 for the previous approach of calibrating directly to
     area-level first-choice tables. The published model's top-1 accuracy is
     about 0.44 and that ceiling propagates. Any-rank demand, which averages
     over the whole list, is far more robust at 0.97 — so school-level
     *capacity pressure* is well reproduced even where the specific
     first-choice ordering is not.
   * **Choices sit about 9% closer to home** than in reality at every list
     position. The model weights proximity more heavily than the observed
     lists do. The gradient with list position is right; the level is short.
   * **Siblings are followed too faithfully.** With a sibling coefficient of
     14.5 against a Gumbel(0,1) shock, an applicant with a sibling ranks that
     school first essentially always (1.00 here, 0.92 in the source).

   None of these is corrected. Correcting them would mean re-introducing
   fitted-to-the-real-lists adjustments, which is exactly what deriving
   preferences from a public model is meant to avoid. Anything sensitive to
   the *fine* structure of first choices should be read with this in mind.
5. **No model feature is endogenous, but the choice set was.** The `exp8`
   specification has no feature computed from the observed list, so nothing
   needed to be broken circularly. The choice set did: see "The choice set is
   narrowed for generation" above.
6. **Rounds 2 and 4 are not modeled.** The `r2_*` columns are present and empty;
   the `r4_*` columns are dropped. The source cohort had round-2 lists for 24%
   of applicants. All committed configs for this year run with `r1-only: true`.
7. **Round-1 outcomes are internally consistent but not the district's.**
   Deferred acceptance on synthetic lists gives a slightly better rank
   distribution than the real round (68.9% versus 64.5% of listed applicants
   offered their first choice) and places 8.8% of applicants off their own list
   against 6.8% in reality.
8. **The shipped utility matrix is the model's, for this cohort.**
   `choice_model/estimates_2324_synthetic.csv` makes
   `utility-model.enable: true` work from a fresh clone, which it previously
   did not. It is a deterministic function of the committed coefficients and
   the synthetic features, and the dataset's own lists are a Gumbel draw over
   it — so the two are consistent by construction rather than by coincidence.

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
# Verify the choice-model port still reproduces the published model.
# Requires access to the confidential data and the model's own output.
uv run python scripts/generators/validate_choice_model_port.py \
    --sfusd-root /share/data/school_choice \
    --weights  .../ChoiceModel_20240514/weights.csv \
    --estimates .../ChoiceModel_20240514/estimates_2324.csv
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
