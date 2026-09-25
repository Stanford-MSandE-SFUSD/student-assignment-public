# Main-text figures — reproduction map


| Figure                     | LaTeX label   | In this public repo                                                          |
| -------------------------- | ------------- | ---------------------------------------------------------------------------- |
| **Fig. 2** zone maps       | `fig:zones`   | **Reproducible** — public CSVs + script below                                |
| **Fig. 3** spatial indices | `fig:indices` | **Reproducible** — path 1 replot (committed CSVs); path 2 optional recompute |


**Table 1 (policy metrics):** [README Paper quickstart](../README.md#paper-quickstart),
[PIPELINE.md](PIPELINE.md). **SI figures:** [SI_APPENDIX.md](SI_APPENDIX.md).

---

## Figure 2 — `fig:zones` (Small / Medium zone maps)

Three selected zone maps (block-group FIPS lists + shoreline-clipped BG
basemap). **No student microdata.**


| Panel | Paper label                  | Zone id           | CSV                                                                                 |
| ----- | ---------------------------- | ----------------- | ----------------------------------------------------------------------------------- |
| (a)   | Small Zones Map 1 (13 zones) | `13-0.25-2500_BG` | `[data/zones/table1/13-0.25-2500_BG.csv](../data/zones/table1/13-0.25-2500_BG.csv)` |
| (b)   | Small Zones Map 2 (10 zones) | `10-0.15-2250_BG` | `[data/zones/table1/10-0.15-2250_BG.csv](../data/zones/table1/10-0.15-2250_BG.csv)` |
| (c)   | Medium Zones (6 zones)       | `6-0.10-1430_BG`  | `[data/zones/table1/6-0.10-1430_BG.csv](../data/zones/table1/6-0.10-1430_BG.csv)`   |


```bash
uv run python scripts/analysis/plot_zone_maps.py
```

Defaults to the three Table 1 BG maps and
`[data/shapefiles/sfusd_blockgroups_2010_clipped.csv](../data/shapefiles/sfusd_blockgroups_2010_clipped.csv)`
(see `[data/shapefiles/README.md](../data/shapefiles/README.md)`). Keeps BG
edges (matches PNAS). Writes `*_clean.png` and `*_labeled.png` under
`local-data/figures/fig2_zones/`.

Optional: `--shapefile` / `--geoid-col` for a raw TIGER BG layer instead of the
clipped CSV (add `--drop-outliers` in that case). Zone keys:
`[data/zones/table1/README.md](../data/zones/table1/README.md)`.

---

## Figure 3 — `fig:indices` (spatial segregation indices)

Zone-map points vs a spatial segregation benchmark for FRL eligibility
(`freelunch_prob`):


| Panel | Vertical axis                        | Spatial curve                          | Reported fit |
| ----- | ------------------------------------ | -------------------------------------- | ------------ |
| (a)   | Student-weighted mean zone deviation | Mean local dissimilarity at radius *r* | WMAE ≈ 0.022 |
| (b)   | Max zone deviation                   | Quantile curve q(r)=1-(r/R)^2          | WMAE ≈ 0.038 |


### Public replot (path 1 — no microdata)

Committed scatter + curve values under
`[data/figures/fig3/](../data/figures/fig3/)`
(see that folder’s [README](../data/figures/fig3/README.md)). 

```bash
uv run python scripts/analysis/plot_fig3.py
```

Writes `fig3_{mean,quantile}.png` to `local-data/figures/fig3/` (gitignored).

Highlighted points: Status Quo, Small 1, Small 2, Medium.

### Regenerating the values (path 2)

Same CSV schema from student microdata + public block centroids + zone CSVs
under `[data/zones/](../data/zones/)` (`table1/` and `fig3/`; script searches
recursively).

```bash
uv run python scripts/analysis/compute_fig3.py \
  --students data/synthetic_2324/student_2324_synthetic.csv \
  --out-dir local-data/figures/fig3_synthetic

uv run python scripts/analysis/plot_fig3.py \
  --data-dir local-data/figures/fig3_synthetic \
  --out-dir local-data/figures/fig3_synthetic
```


| Input / choice    | Detail                                                                                  |
| ----------------- | --------------------------------------------------------------------------------------- |
| Centroids         | `[sfusd_blocks_2010_centroids.csv](../data/shapefiles/sfusd_blocks_2010_centroids.csv)` |
| Zone diameters    | On-the-fly WGS84 geodesic (half → map radius); same metric as the private s01 matrix    |
| Local index       | EPSG:3857 neighborhoods (matches the paper notebook)                                    |
| District radius R | Hard-coded paper value ≈ 4.898 mi (`--district-rad`))                                   |


**Synthetic** path-2 values will not match path 1 (different FRL geography).
Path 2 with a **Track B** (DUA) filtered KG file can match path 1 closely:
quantile highlights align well; mean-panel zone radii may differ slightly from
the private distance-matrix export.

Do not confuse with the SI **assignment** Pareto frontier
(`scripts/analysis/plot_simulation_frontier.py`).

---

## Related docs


| Doc                                                           | Role                               |
| ------------------------------------------------------------- | ---------------------------------- |
| [README Paper quickstart](../README.md#paper-quickstart)      | Table 1 DA + metrics               |
| [SI_APPENDIX.md](SI_APPENDIX.md)                              | SI figures/tables; zone CSV layout |
| [ZONE_SETUP.md](ZONE_SETUP.md)                                | `table1/` vs `fig3/` zone folders  |
| [data/zones/table1/README.md](../data/zones/table1/README.md) | Fig. 2 / Table 1 map keys          |
| [data/shapefiles/README.md](../data/shapefiles/README.md)     | Fig. 2 basemap + Fig. 3 centroids  |
| [data/figures/fig3/README.md](../data/figures/fig3/README.md) | Fig. 3 plotted values              |


