# SI Appendix — reproduction map

Maps **Supplementary Information (SI)** robustness checks to code and configs in
this repo and
[SFUSD-Choice-public](https://github.com/Stanford-MSandE-SFUSD/SFUSD-Choice-public).

**Main-text Table 1:** README [Paper quickstart](../README.md#paper-quickstart)
and [`configs/paper/table1_config.yaml`](../configs/paper/table1_config.yaml)
(seven-policy column ↔ subconfig map is there).  
**Main-text figures:** [PAPER_FIGURES.md](PAPER_FIGURES.md).  
**Metric key ↔ paper row names:** [PAPER_METRICS.md](PAPER_METRICS.md).

Coefficient files (`weights.csv`) may be shared. Student-level `estimates_*.csv`
belong under local / synthetic paths, not public git.

---

## Choice models (A / B / C)

Stems live under Choice-public
`local_outputs/models/<stem>/` (`weights.csv`; regenerate `estimates_*.csv`
per track).

| Paper | Internal id | Stem (train 2022–23 → simulate 2023–24) | Role |
| --- | --- | --- | --- |
| **Model A** | **t14** | `t14_2223_k1_prog_gesplit` | Main text (Table 1) |
| **Model B** | **t17** | `t17_2223_k1_prog_gesplit` | SI — policy × model |
| **Model C** | **t9** | `t9_2223_k1_prog_gesplit` | SI — policy × model |

Main Table 1 settings: **2023–24** KG R1, 25 iterations,
`list-length: 0.8*round(real_length)`.

---

## Zones (paper Small / Medium)

| Paper | Zone id (config / backend) | CSV under `data/zones/table1/` |
| --- | --- | --- |
| **Small Zones (a)** — main-text Small | `13-0.25-2500_BG` | `13-0.25-2500_BG.csv` |
| Small Zones (b) — additional small | `10-0.15-2250_BG` | `10-0.15-2250_BG.csv` |
| **Medium Zones (c)** — main-text Medium | `6-0.10-1430_BG` | `6-0.10-1430_BG.csv` |

Policy subconfigs use these ids (e.g. `13-0.25-2500_BG+no_reserves`,
`6-0.10-1430_BG+reserves_05frl`). Older `small_zones+*` / `medium_zones+*`
YAMLs live under
[`configs/policy_configs/_legacy/`](../configs/policy_configs/_legacy/).

---

## Reserves

| Paper | Definition | Config family |
| --- | --- | --- |
| **Main text** | FRL **>50% / ≤50%** | `*_05frl` (`percentile:50`, `[0.5, 0.5]`) |
| **Reserves A** (SI) | FRL **>60% / ≤60%** | `*_06frl` (`percentile:60`, `[0.6, 0.4]`) |
| **Reserves B** (SI) | Income **95,292** | bare `*+reserves` (`median_hh_income`, `[95292]`, `[0.57, 0.43]`) |

---

## Distance priorities

| Paper | Bands | Config |
| --- | --- | --- |
| **Main** Dist Priority | 0–0.5, 0.5–1, 1–2, 2+ | `distance_05_1_2+reserves_05frl` (`thresholds: [0.5, 1, 2]`) |
| **Dist A** (SI) | 0–0.5, 0.5–1, 1+ | `distance_05_1+reserves_05frl` (`thresholds: [0.5, 1]`) |
| **Dist B** (SI) | 0–0.75, 0.75–2, 2+ | `distance_075_2+reserves_05frl` (`thresholds: [0.75, 2]`) |

---

## Status Quo (Table 1)

`status_quo` — counterfactual DA under status-quo priorities (utilities on);
the Table 1 baseline column.

---

## Zone map CSVs (geography)

```
data/zones/
├── table1/          # Table 1 DA policies + Con1 for Dist Priority
└── fig3/            # Figure 3 zone-cloud geography
    ├── Small*__….csv
    ├── Medium*__….csv
    └── Zones_*__….csv
```

| Path / pattern | Role |
| --- | --- |
| `table1/` | Paper DA keys — see [`data/zones/table1/README.md`](../data/zones/table1/README.md) |
| `fig3/` | Figure 3 path 2 cloud (`compute_fig3.py`); optional frontier / labeled-zone plots |

---

## SI figures (this public repo)

| SI item | Primary code / config | Notes |
| --- | --- | --- |
| Zone frontier (diversity vs proximity) | `scripts/analysis/plot_simulation_frontier.py`, `configs/custom_configs/simulation_frontier.yaml` | Background = many zone **sims**; geography maps under `data/zones/fig3/` |
| Choice-model first-choice validation | **SFUSD-Choice-public** | See that repo’s `docs/SI_APPENDIX.md` |

---

## SI tables

Track A runs this ladder on the synthetic pack (`run_syn_mnl_cde_step3.py` —
[PIPELINE.md](PIPELINE.md) § A1) for **comparable takeaways**. Track B uses
DUA microdata when paper-faithful cells are required. Many YAMLs under
`configs/robustness/` still point at Track B path tokens until you retarget
them or use the synthetic emitters.

| SI item | Primary code / config | Notes |
| --- | --- | --- |
| MNL coeffs Models A/B/C | Choice `weights.csv` for **t14 / t17 / t9** | Share weights; keep student-level estimates local |
| List-length sensitivity (Status Quo) | Override `utility-model.list-length`; `analyze_trends.py` | real / 80% / 70% / 60% / 7 / 10 |
| Policy × years | Model A; alternate train/test `estimate-path` | `configs/robustness/years_analysis/`, `years_cross_analysis/` |
| Policy × Model B / C | Same seven policies; **t17** / **t9** estimates | |
| Model A + actual length / length 10 | Override `list-length` | |
| Popularity-adjusted lists | `run_augmented_da.py`, `list_augmentation.py` | |
| Reserves A vs B | `*_06frl` vs bare `*+reserves` | |
| Dist A vs B | `distance_05_1+reserves_05frl` vs `distance_075_2+reserves_05frl` | |
| Theil decomp (zoned vs citywide) | Evaluator Theil metrics; named maps under `data/zones/fig3/` | |

---

## Useful commands

```bash
uv run python scripts/analysis/analyze_trends.py --config <analysis.yaml>

uv run python scripts/analysis/plot_simulation_frontier.py \
    --config configs/custom_configs/simulation_frontier.yaml

uv run python run_augmented_da.py --config-path <yaml>
```

---

## Related docs

| Doc | Role |
| --- | --- |
| [PAPER_METRICS.md](PAPER_METRICS.md) | Paper table rows ↔ code metric keys |
| [PAPER_FIGURES.md](PAPER_FIGURES.md) | Main-text figures |
| [PIPELINE.md](PIPELINE.md) | Clone → first simulation |
| [DATA_SETUP.md](DATA_SETUP.md) | Paths and placeholder tokens |
| [CONFIG_OPTIONS.md](CONFIG_OPTIONS.md) | Full config reference |
| [ZONE_SETUP.md](ZONE_SETUP.md) | Zone CSV setup for simulation |
