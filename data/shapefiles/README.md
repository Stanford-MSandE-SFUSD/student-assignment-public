# Public geography for paper figures

## `sfusd_blockgroups_2010_clipped.csv`

Shoreline-clipped **Census 2010 block-group** polygons for San Francisco County
(FIPS `06075`), used as the basemap for paper **Figure 2** zone maps
(`scripts/analysis/plot_zone_maps.py`).

| | |
|---|---|
| Rows | 579 block groups |
| Id column | `block_geoid` (11-digit FIPS, no leading state zero — e.g. `60750262005`) |
| Geometry | WKT in `geometry` (EPSG:4326) |
| Other columns | Census 2010 block attributes carried through from the dissolve (`aland10`, `awater10`, `geoid10`, …) |

**This file contains no student or district microdata.** It is derived only from
public census / city open-data geometry.

### Why a clipped file?

Raw TIGER / Bay-area block-group shapefiles include large water polygons in the
Bay and can omit or distort **Treasure Island / Yerba Buena**. Zone choropleths
then look like they fill the ocean and miss TI. This CSV is the land-masked
geometry used for paper-style maps.

### Public source inputs

1. **Census 2010 blocks** for San Francisco (TIGER / local public mirror) —
   dissolved to block groups after clipping.
2. **Census 2020 blocks clipped to the shoreline** for San Francisco
   ([DataSF](https://data.sfgov.org/) dataset
   *“Census 2020 Blocks for San Francisco Clipped to the Shoreline”*) —
   used only as a **land mask**, not as the zone geounit layer.

Zone membership CSVs under `data/zones/` are separate public FIPS lists; they
are not inputs to this geometry file.

---

## `sfusd_blocks_2010_centroids.csv`

Block **centroids** (lat/lon) for shoreline-clipped Census 2010 SF blocks.
Used by Figure 3 path (2) (`scripts/analysis/compute_fig3.py`) for zone
diameters and the spatial segregation index curve — **no distance pickle**.

| | |
|---|---|
| Rows | ~7.3k blocks |
| Columns | `geoid` (15-digit), `block_group` (12-digit), `lat`, `lon` |
| CRS | WGS84 degrees (EPSG:4326) |

Derived from the same clipped 2010 block geometry as the BG layer above
(internal point / `intpt*` fields). No student microdata.
