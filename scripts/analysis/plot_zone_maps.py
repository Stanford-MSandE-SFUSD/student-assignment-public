"""Regenerate paper Figure 2 zone maps from zone CSVs + public BG geometry.

Reads zone CSVs (one row per zone, comma-separated census geounit FIPS) and
colors matching polygons from shoreline-clipped Census 2010 block groups
(default) or another BG/block shapefile. Writes ``*_clean.png`` panels in the
style of the private notebook helper ``save_zone_map`` (no title / legend).

No student microdata required.

Default (matches PNAS revision Figure 2 panels)::

    uv run python scripts/analysis/plot_zone_maps.py

Override with another public shapefile if needed::

    uv run python scripts/analysis/plot_zone_maps.py \\
        --shapefile path/to/Census_2010_SFBay_blockgroup.shp \\
        --geoid-col blkgrpid --county-fips 075 --drop-outliers

Public geometry (default file documented in ``data/shapefiles/README.md``):
  - ``data/shapefiles/sfusd_blockgroups_2010_clipped.csv`` (preferred)
  - Or TIGER / DataSF 2010 BG or block shapefiles via ``--shapefile``
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Paper Table 1 / Fig. 2 panels (relative to repo root).
DEFAULT_ZONES = [
    _PROJECT_ROOT / "data/zones/table1/13-0.25-2500_BG.csv",
    _PROJECT_ROOT / "data/zones/table1/10-0.15-2250_BG.csv",
    _PROJECT_ROOT / "data/zones/table1/6-0.10-1430_BG.csv",
]

DEFAULT_SHAPEFILE = (
    _PROJECT_ROOT / "data/shapefiles/sfusd_blockgroups_2010_clipped.csv"
)

# Outliers to drop only for *raw* Bay/TIGER BG shapefiles (water / far polys).
# Do not apply these to the shoreline-clipped CSV — it already removes water,
# and ids like 60750179021 are Treasure Island land that should stay.
RAW_SHAPEFILE_OUTLIER_GEOIDS = [
    "60759804011",
    "60759901000",
    "60750479012",
    "60750179021",
    "60759806001",
]


def normalize_geoid(value: object) -> str:
    """Digits only, strip leading zeros so CSV (11-digit) matches shp (12-digit)."""
    digits = re.sub(r"\D", "", str(value))
    return digits.lstrip("0") or "0"


def load_zone_csv(path: Path) -> list[list[str]]:
    """Return list of zones; each zone is a list of normalized geounit ids."""
    zones: list[list[str]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            ids = [normalize_geoid(cell) for cell in row if str(cell).strip()]
            if ids:
                zones.append(ids)
    if not zones:
        raise ValueError(f"No zones found in {path}")
    return zones


def load_geodata(
    shapefile: Path,
    geoid_col: str | None,
    county_fips: str | None,
    outlier_geoids: list[str],
) -> gpd.GeoDataFrame:
    shapefile = Path(shapefile)
    if shapefile.suffix.lower() == ".csv":
        # Committed clipped BG file stores polygons as WKT.
        df = pd.read_csv(shapefile)
        if "geometry" not in df.columns:
            raise ValueError(f"{shapefile} has no 'geometry' column (expected WKT)")
        gdf = gpd.GeoDataFrame(
            df,
            geometry=gpd.GeoSeries.from_wkt(df["geometry"]),
            crs="EPSG:4326",
        )
    else:
        gdf = gpd.read_file(shapefile)
        if gdf.crs is None:
            gdf = gdf.set_crs(epsg=4326)
        else:
            gdf = gdf.to_crs(epsg=4326)

    if county_fips:
        # Common TIGER / Bay-area BG column names.
        county_cols = [
            c
            for c in ("fipco", "COUNTYFP", "COUNTYFP10", "countyfp", "countyfp10")
            if c in gdf.columns
        ]
        if county_cols:
            col = county_cols[0]
            target = str(county_fips).zfill(3)

            def _county_code(val: object) -> str | None:
                """Return 3-digit county FIPS, or None if missing (keep row)."""
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return None
                # Handle float codes like 75.0 from CSV round-trips.
                try:
                    return str(int(float(val))).zfill(3)
                except (TypeError, ValueError):
                    digits = re.sub(r"\D", "", str(val))
                    return digits.zfill(3)[-3:] if digits else None

            codes = gdf[col].map(_county_code)
            gdf = gdf[codes.isna() | (codes == target)].copy()
            logger.info("Filtered to county FIPS %s via %s (%d polys)", county_fips, col, len(gdf))
        else:
            logger.warning("No county column found; skipping --county-fips filter")

    if geoid_col is None:
        candidates = [
            c
            for c in (
                "block_geoid",
                "blkgrpid",
                "GEOID",
                "GEOID10",
                "geoid10",
                "GEOID20",
                "tract_bloc",
            )
            if c in gdf.columns
        ]
        if not candidates and gdf.index.name:
            gdf = gdf.reset_index()
            candidates = [gdf.columns[0]]
        if not candidates:
            raise ValueError(
                f"Could not infer geoid column from {list(gdf.columns)}; pass --geoid-col"
            )
        geoid_col = candidates[0]
        logger.info("Using geoid column %s", geoid_col)

    gdf = gdf.copy()
    gdf["_geoid"] = gdf[geoid_col].map(normalize_geoid)
    # If shapefile is blocks (15-digit / long ids) and zones are BGs, also keep BG key.
    gdf["_geoid_bg"] = gdf["_geoid"].map(lambda x: x[:11] if len(x) > 11 else x)

    drop = {normalize_geoid(x) for x in outlier_geoids}
    before = len(gdf)
    gdf = gdf[~gdf["_geoid"].isin(drop) & ~gdf["_geoid_bg"].isin(drop)].copy()
    if len(gdf) < before:
        logger.info("Dropped %d outlier polygons", before - len(gdf))

    return gdf


def assign_zones(gdf: gpd.GeoDataFrame, zones: list[list[str]]) -> gpd.GeoDataFrame:
    """Map each polygon to a zone id (or -1 if unmatched)."""
    unit_to_zone: dict[str, int] = {}
    for zone_id, unit_ids in enumerate(zones):
        for uid in unit_ids:
            unit_to_zone[uid] = zone_id

    out = gdf.copy()
    # Prefer exact id match; fall back to BG prefix for block shapefiles.
    out["zone_id"] = out["_geoid"].map(unit_to_zone)
    missing = out["zone_id"].isna()
    if missing.any():
        out.loc[missing, "zone_id"] = out.loc[missing, "_geoid_bg"].map(unit_to_zone)
    out["zone_id"] = out["zone_id"].fillna(-1).astype(int)
    return out


def coverage_report(zones: list[list[str]], gdf: gpd.GeoDataFrame, label: str) -> None:
    all_ids = {uid for zone in zones for uid in zone}
    present = set(gdf["_geoid"]) | set(gdf["_geoid_bg"])
    hit = all_ids & present
    miss = all_ids - present
    in_map = (gdf["zone_id"] >= 0).sum()
    logger.info(
        "%s: %d zones, %d geounits in CSV, %d matched in shapefile, "
        "%d polygons colored, %d CSV ids missing from shapefile",
        label,
        len(zones),
        len(all_ids),
        len(hit),
        int(in_map),
        len(miss),
    )
    if miss and len(miss) <= 20:
        logger.warning("Missing geoids: %s", sorted(miss))
    elif miss:
        logger.warning("Missing geoids (first 20): %s ...", sorted(miss)[:20])


def plot_clean_map(
    gdf: gpd.GeoDataFrame,
    out_path: Path,
    *,
    cmap: str = "tab20",
    dpi: int = 200,
) -> Path:
    """Save a title-/legend-free choropleth (paper ``_clean`` style, BG edges kept)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plot_df = gdf.copy()
    fig, ax = plt.subplots(figsize=(12, 10))
    plot_df.plot(ax=ax, color="#f0f0f0", edgecolor="white", linewidth=0.3)
    filtered = plot_df[plot_df["zone_id"] >= 0]
    if not filtered.empty:
        filtered.plot(
            ax=ax,
            column="zone_id",
            categorical=True,
            cmap=cmap,
            edgecolor="black",
            linewidth=0.5,
            legend=False,
        )

    ax.set_axis_off()
    fig.subplots_adjust(left=0.02, right=0.98, top=0.98, bottom=0.02)
    fig.savefig(out_path, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    logger.info("Wrote %s", out_path)
    return out_path


def stem_for_zone_path(path: Path) -> str:
    # Keep paper-ish names: 13-0.25-2500_BG → same stem.
    return path.stem


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--shapefile",
        type=Path,
        default=DEFAULT_SHAPEFILE,
        help=(
            "BG/block geometry: WKT CSV, shapefile, or GeoJSON. "
            f"Default: {DEFAULT_SHAPEFILE.relative_to(_PROJECT_ROOT)}."
        ),
    )
    p.add_argument(
        "--geoid-col",
        default=None,
        help="Column with GEOID / blkgrpid (inferred if omitted).",
    )
    p.add_argument(
        "--county-fips",
        default="075",
        help="County FIPS filter (default 075 = San Francisco). Empty string to disable.",
    )
    p.add_argument(
        "--zones",
        type=Path,
        nargs="+",
        default=None,
        help="Zone CSV paths (default: three data/zones/table1 paper maps).",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=_PROJECT_ROOT / "local-data" / "figures" / "fig2_zones",
        help="Directory for PNG outputs.",
    )
    p.add_argument("--cmap", default="tab20")
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument(
        "--drop-outliers",
        action="store_true",
        help=(
            "Drop notebook outlier BG ids (water / far polys). Useful for raw "
            "TIGER/Bay shapefiles; not needed for the default clipped CSV "
            "(would remove Treasure Island)."
        ),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    zone_paths = args.zones or DEFAULT_ZONES
    county = args.county_fips.strip() or None
    outliers = RAW_SHAPEFILE_OUTLIER_GEOIDS if args.drop_outliers else []

    gdf = load_geodata(args.shapefile, args.geoid_col, county, outliers)

    for zpath in zone_paths:
        zpath = Path(zpath)
        zones = load_zone_csv(zpath)
        mapped = assign_zones(gdf, zones)
        coverage_report(zones, mapped, zpath.name)
        out = args.output_dir / f"{stem_for_zone_path(zpath)}_clean.png"
        plot_clean_map(
            mapped,
            out,
            cmap=args.cmap,
            dpi=args.dpi,
        )
        # Also write a labeled copy for debugging.
        fig, ax = plt.subplots(figsize=(12, 10))
        mapped.plot(ax=ax, color="#f0f0f0", edgecolor="white", linewidth=0.3)
        filt = mapped[mapped["zone_id"] >= 0]
        if not filt.empty:
            filt.plot(
                ax=ax,
                column="zone_id",
                categorical=True,
                cmap=args.cmap,
                edgecolor="black",
                linewidth=0.5,
                legend=True,
                legend_kwds={"title": "zone_id", "bbox_to_anchor": (1.02, 0.5), "loc": "center left"},
            )
        ax.set_axis_off()
        ax.set_title(zpath.name)
        labeled = args.output_dir / f"{stem_for_zone_path(zpath)}_labeled.png"
        fig.savefig(labeled, dpi=args.dpi, bbox_inches="tight")
        plt.close(fig)
        logger.info("Wrote %s", labeled)


if __name__ == "__main__":
    main()
