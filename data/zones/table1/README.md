# Table 1 zone maps

Geography only (Census block-group FIPS or attendance-area ids) — **no student
microdata**. Used by
[`configs/paper/table1_config.yaml`](../../../configs/paper/table1_config.yaml).

| File | Config key (`zone-files` / `policies:`) | Role |
|------|----------------------------------------|------|
| `13-0.25-2500_BG.csv` | `13-0.25-2500_BG` | Small Zones (paper map **a**) |
| `6-0.10-1430_BG.csv` | `6-0.10-1430_BG` | Medium Zones (paper map **c**) |
| `10-0.15-2250_BG.csv` | `10-0.15-2250_BG` | Additional small (paper map **b** / SI) |
| `concept1zones.csv` | `Con1` | SFUSD **Concept 1** attendance-area map — Dist Priority column (distance bands under status-quo-style geography, not the Small/Medium BG maps) |

Other zone CSVs for main-text `fig:indices` and Theil-H / labeled maps live in
the parent folder [`data/zones/`](../). See [docs/SI_APPENDIX.md](../../../docs/SI_APPENDIX.md).
