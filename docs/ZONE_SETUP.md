# Zone setup

How to register zone geography CSVs so the assignment simulator can use them.

Paper Table 1 maps are already in-repo under
[`data/zones/table1/`](../data/zones/table1/). Additional CSVs live under
[`data/zones/`](../data/zones/). To use a zone map in a simulation:

1. **Register** the zone file in the path configuration
2. **Create** a policy configuration referencing the zone
3. **Run** the simulation

If you have zone `.pkl`s from an external optimizer, see
`scripts/generators/generate_zone_from_pickle.py`.

## Step-by-Step Guide

### Step 1: Register the Zone File

Add your zone file to `configs/local_path_config.yaml` (or your personal `configs/<your-username>.config.yaml`):

```yaml
paths:
  # ... existing paths ...
  zone-files:
    # ... existing zones ...
    # Paper Table 1 Medium Zones (file is in the repo):
    6-0.10-1430_BG: data/zones/table1/6-0.10-1430_BG.csv
```

Or use the other Table 1 maps under `data/zones/table1/`
(`13-0.25-2500_BG.csv`, `10-0.15-2250_BG.csv`, `concept1zones.csv`).

### Step 2: Create/Update Policy Config

Either use the template at `configs/policy_configs/custom_zones+reserves.yaml` or create your own:

```yaml
# configs/policy_configs/my_custom_zones.yaml
assignment-algorithm: DA
ctip-options:
- 1

restrict-zone: true
guard-rails: 1

reserve-settings:
  column: median_hh_income
  thresholds: [95292]
  lower_disadvantaged: true
  citywide_only: false
  reserve_fraction: [0.57, 0.43]

policies:
- 6-0.10-1430_BG  # Must match the key in zone-files

zone-building-blocks: block_group  # Must match the CSV's geounit type
designate: true
ties-options:
- MTB
```

### Step 3: Update Base Config

Ensure your `configs/base_config.yaml` references your policy config:

```yaml
subconfigs:
  - my_custom_zones  # Points to my_custom_zones.yaml in policy_configs/
```

Or point a custom runner YAML's `subconfigs:` / policy list at the same name.

### Step 4: Run the Simulation

```bash
cd /path/to/student-assignment
uv run python run_custom_config.py --config-path <your-config>.yaml
```

## Zone File Format

The CSV format expected by the simulation:
- **One row per zone**
- **Comma-separated geounit IDs** in each row
- No header row

Example (3 zones with block groups):
```csv
60750101001,60750101002,60750102003
60750201001,60750201002
60750301001,60750301002,60750301003
```

## Building Blocks

The `zone-building-blocks` setting must match the geounit type in the CSV:

| Building Block | Description | Geounit IDs |
|----------------|-------------|-------------|
| `block_group` | Census block groups | 12-digit FIPS codes |
| `block` | Census blocks | 15-digit FIPS codes |
| `attendance_area` | School attendance areas | 3-digit school IDs |

## Troubleshooting

### "Zone file not found"
- Ensure the path in `zone-files` is correct (relative to working directory or absolute)
- Check that the zone key in `policies` matches the key in `zone-files`

### "Geounit not found in zone"
- Ensure `zone-building-blocks` matches the CSV (block group vs block vs attendance area)
- Verify that student data uses the same geounit type
