# Zone setup

How zone geography CSVs are laid out and how to register one for simulation.

## Layout

```
data/zones/
├── table1/     # Main-text Table 1 DA maps (+ Con1 for Dist Priority)
└── fig3/       # Figure 3 zone-cloud geography (+ optional frontier maps)
```

| Folder | Use |
| --- | --- |
| [`table1/`](../data/zones/table1/) | Paper Table 1 — see that folder’s [README](../data/zones/table1/README.md). Already registered in [`configs/paper/table1_config.yaml`](../configs/paper/table1_config.yaml). |
| [`fig3/`](../data/zones/fig3/) | Geography for Figure 3 path 2 (`compute_fig3.py`) and optional frontier / labeled-zone plots. See that folder’s [README](../data/zones/fig3/README.md). |

Geography only (FIPS or attendance-area ids) — no student microdata.

**Table 1 users:** you can stop here. Open `table1_config.yaml`, set data paths, run.

---

## Register a custom zone (optional)

Needed only if you add a new map or use something under `fig3/` in a DA run.

### 1. Point `zone-files` at the CSV

In your run YAML (or `configs/<user>.config.yaml`):

```yaml
paths:
  zone-files:
    6-0.10-1430_BG: data/zones/table1/6-0.10-1430_BG.csv
    # example Fig 3 / frontier map:
    # my_frontier_map: data/zones/fig3/Zones_6__FRL_Dev_0.10__Objective_1430_BG.csv
```

Keys are arbitrary strings; each `policies:` entry must match a key.

### 2. Policy subconfig

Use an existing policy under `configs/policy_configs/`, or a small custom file:

```yaml
# configs/policy_configs/my_custom_zones.yaml
assignment-algorithm: DA
ctip-options: [1]
restrict-zone: true
guard-rails: 0
reserve-settings:
  column: freelunch_prob   # main-text style: see *_05frl policies
  percentile: 50
  reserve_fraction: [0.5, 0.5]
  lower_disadvantaged: false
  citywide_only: false
policies:
  - 6-0.10-1430_BG          # must match a zone-files key
zone-building-blocks: block_group
designate: true
ties-options: [MTB]
```

Main-text reserve / distance variants: [SI_APPENDIX.md](SI_APPENDIX.md).
Template also: `configs/policy_configs/custom_zones+reserves.yaml` (income-based reserves).

Put the policy **name** (filename without `.yaml`) in your run YAML’s
`subconfigs:` list — not necessarily in `base_config.yaml`.

### 3. Run

```bash
uv run python run_custom_config.py --config-path <your-config>.yaml
```

---

## CSV format

- One row per zone  
- Comma-separated geounit IDs in each row  
- No header  

```csv
60750101001,60750101002,60750102003
60750201001,60750201002
```

`zone-building-blocks` must match the IDs:


| Setting | Geounit IDs |
| --- | --- |
| `block_group` | 12-digit Census FIPS (most `*_BG.csv` files) |
| `block` | 15-digit Census FIPS (`*_B.csv`) |
| `attendance_area` | School attendance-area ids (e.g. Table 1 `concept1zones.csv` / `Con1`) |


---

## Troubleshooting

- **Zone file not found** — path under `zone-files` (cwd-relative or absolute); Table 1 files are under `data/zones/table1/`, Figure 3 / frontier maps under `data/zones/fig3/`.
- **Geounit not found in zone** — `zone-building-blocks` mismatches the CSV (e.g. `block_group` vs `attendance_area` for Con1).
- **Policy key error** — every `policies:` name must appear as a key in `zone-files`.

Advanced: build a CSV from an optimizer pickle with
`scripts/generators/generate_zone_from_pickle.py` (`--help`).
