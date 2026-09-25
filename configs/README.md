# Setting Up Your Config File

Make configuration changes in your personal config file,
`<YOUR-COMPUTER-USERNAME>.config.yaml`.
If you do not see it under `configs/`, it is generated automatically the first
time you run an entry point (e.g.
`uv run python run_custom_config.py --config-path configs/paper/table1_config.yaml`).
**Do not** edit `base_config.yaml` for machine-specific paths.

That personal file holds local paths and non-policy options (e.g. whether to
use a utility model). It is **gitignored** so absolute paths into confidential
data are not committed — see [docs/DATA_SETUP.md](../docs/DATA_SETUP.md)
(`local-data/`).

To select which policies to run, list policy config **stems** under
`subconfigs:` (files in `configs/policy_configs/` without `.yaml`):

```yaml
subconfigs:
  - status_quo_real
  - 6-0.10-1430_BG+reserves_05frl
  - distance_05_1_2+reserves_05frl
```

Paper Table 1 wiring (paths + the seven policy names) lives in
[`configs/paper/table1_config.yaml`](paper/table1_config.yaml).

## Troubleshooting

The first time you generate your config, adjust filepaths in the personal
config. Path errors usually mean a key still points at a missing absolute path.

If you get schema validation errors, regenerate from the base config by
renaming or deleting `configs/<username>.config.yaml` (renaming is safer so you
can copy path overrides back).

## Generating New Policies

Copy an existing file under `configs/policy_configs/` and edit. A policy can
reference multiple zone keys (different home-based maps) while keeping other
settings (e.g. reserves) fixed. Register zone CSV paths under `paths.zone-files`
in your personal / path config, then list those keys under `policies:` in the
policy YAML — see [docs/ZONE_SETUP.md](../docs/ZONE_SETUP.md).
