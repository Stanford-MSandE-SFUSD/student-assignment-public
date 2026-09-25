# Legacy small/medium zone policy configs

These YAMLs target older zone map keys (`18zone_2`, `6zone-1`) from earlier
paper drafts. They are **not** the main-text Small / Medium maps.

For Table 1 / SI robustness, use:

| Paper role | Policy subconfig |
| --- | --- |
| Small Zones | `13-0.25-2500_BG+no_reserves` |
| Small + Reserves (main FRL) | `13-0.25-2500_BG+reserves_05frl` |
| Medium Zones | `6-0.10-1430_BG+no_reserves` |
| Medium + Reserves (main FRL) | `6-0.10-1430_BG+reserves_05frl` |

Zone CSVs: `data/zones/table1/`. See `docs/SI_APPENDIX.md` and
`configs/paper/table1_config.yaml`.

To load one of these legacy files deliberately, pass the subconfig name with
the folder prefix (loader path is `policy_configs/{name}.yaml`):

```text
_legacy/small_zones+no_reserves
```
