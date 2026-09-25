# Figure 3 — plotted values (path 1)

Exported scatter + curve points for paper **Figure 3** (`fig:indices`).
**No student microdata.**

| File | Contents |
|------|----------|
| `fig3_mean_maps.csv` | Panel (a) points: `radius`, `zone_deviation`, `highlight`, `label` |
| `fig3_mean_curve.csv` | Panel (a) curve: `radius`, `spatial_segregation_index` |
| `fig3_quantile_maps.csv` | Panel (b) points |
| `fig3_quantile_curve.csv` | Panel (b) curve |
| `fig3_metadata.json` | Panel titles / legend strings |

```bash
uv run python scripts/analysis/plot_fig3.py
```

Writes `fig3_{mean,quantile}.png` to `local-data/figures/fig3/` (gitignored).

### Path 2 — recompute from students

Needs the synthetic pack at `data/synthetic_2324/` and zone CSVs under
`data/zones/` (`table1/` + `fig3/`).

```bash
uv run python scripts/analysis/compute_fig3.py \
  --students data/synthetic_2324/student_2324_synthetic.csv \
  --out-dir local-data/figures/fig3_synthetic

uv run python scripts/analysis/plot_fig3.py \
  --data-dir local-data/figures/fig3_synthetic \
  --out-dir local-data/figures/fig3_synthetic
```

Needs public block centroids
[`../shapefiles/sfusd_blocks_2010_centroids.csv`](../shapefiles/sfusd_blocks_2010_centroids.csv).

Path 2 computes zone radii from on-the-fly WGS84 geodesic diameters (no
distance pickle) and the local index in EPSG:3857. Quantile panel \(R\) defaults
to the paper value ≈ 4.898 mi (`--district-rad`; `--estimate-district-rad` only
for experiments). Synthetic / path-2 values are **not** expected to match the
committed path-1 CSVs.
