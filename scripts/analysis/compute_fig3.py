"""Compute Figure 3 plotted values from students + public block centroids (path 2).

Builds the same CSV schema as ``data/figures/fig3/`` (path 1), but from
synthetic or other student microdata. Values will **not** match the paper.

Requires:
  - student CSV with ``census_block``, ``freelunch_prob`` (optional ``grade``)
  - ``data/shapefiles/sfusd_blocks_2010_centroids.csv``
  - zone CSVs under ``data/zones/`` (``*_BG.csv``, ``*_B.csv``)

Example (local synthetic pack)::

    uv run python scripts/analysis/compute_fig3.py \\
      --students local-data/synthetic_2324/student_2324_synthetic.csv \\
      --out-dir local-data/figures/fig3_synthetic

Then::

    uv run python scripts/analysis/plot_fig3.py \\
      --data-dir local-data/figures/fig3_synthetic
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Geod, Transformer
from scipy.spatial import cKDTree

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CENTROIDS = _PROJECT_ROOT / "data" / "shapefiles" / "sfusd_blocks_2010_centroids.csv"
DEFAULT_ZONES = _PROJECT_ROOT / "data" / "zones"
DEFAULT_OUT = _PROJECT_ROOT / "local-data" / "figures" / "fig3_synthetic"

FEATURE = "freelunch_prob"
WEIGHT_COL = "nstudents"
RADII = np.arange(0.2, 3.5, 0.1)
MAX_R_FILTER = 4.0
METERS_PER_MILE = 1609.34
# Paper Fig. 3 panel (b): half of district diameter from block–block distance
# matrix (99.5/99.5 quantile). Do not re-estimate from centroids — that
# understates R (~3.5 mi) and pulls the quantile curve down.
PAPER_DISTRICT_RAD_MILES = 4.89809563015615

# Same ellipsoid as s01 ``geodesic_distance_matrix_df_from_df`` / block2block pickle.
_GEOD = Geod(ellps="WGS84")

# Exact map stems to highlight (table1 short names + status quo).
HIGHLIGHT_STEMS: dict[str, str] = {
    "aa_B": "Status Quo",
    "13-0.25-2500_BG": "Small 1",
    "10-0.15-2250_BG": "Small 2",
    "6-0.10-1430_BG": "Medium",
}


def normalize_geoid(value: object) -> str:
    """Digits only, strip leading zeros (CSV / float / 15-digit GEOID safe)."""
    s = str(value).strip()
    # pandas often writes integer GEOIDs as ``6075….0``; stripping non-digits
    # would otherwise append a trailing zero from the fractional part.
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".", 1)[0]
    digits = re.sub(r"\D", "", s)
    return digits.lstrip("0") or "0"


def project_web_mercator_meters(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """EPSG:4326 → EPSG:3857 meters (matches s03 / paper local-index code)."""
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    x, y = transformer.transform(lon, lat)
    return np.column_stack((np.asarray(x, dtype=float), np.asarray(y, dtype=float)))


def load_centroids(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    need = {"geoid", "lat", "lon"}
    if not need.issubset(df.columns):
        raise SystemExit(f"{path} needs columns {need}; has {list(df.columns)}")
    out = pd.DataFrame(
        {
            "geoid": df["geoid"].map(normalize_geoid),
            "lat": pd.to_numeric(df["lat"], errors="coerce"),
            "lon": pd.to_numeric(df["lon"], errors="coerce"),
        }
    )
    if "block_group" in df.columns:
        out["block_group"] = df["block_group"].map(normalize_geoid)
    else:
        # 15-digit GEOID → first 12 digits → normalize
        raw = df["geoid"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(15)
        out["block_group"] = raw.str[:12].map(normalize_geoid)
    out = out.dropna(subset=["lat", "lon"]).drop_duplicates("geoid").set_index("geoid")
    return out


def build_block_data(students_path: Path, centroids: pd.DataFrame) -> pd.DataFrame:
    # Read block ids as string to avoid float precision / ``.0`` artifacts.
    stud = pd.read_csv(students_path, dtype={"census_block": str}, low_memory=False)
    if "grade" in stud.columns:
        stud = stud.loc[stud["grade"].astype(str).str.upper().eq("KG")].copy()
    if "census_block" not in stud.columns or FEATURE not in stud.columns:
        raise SystemExit(f"{students_path} needs census_block and {FEATURE}")

    stud = stud.dropna(subset=["census_block", FEATURE]).copy()
    stud["_block"] = stud["census_block"].map(normalize_geoid)

    frl = stud.groupby("_block")[FEATURE].mean()
    nstu = stud.groupby("_block").size().astype(int)

    block = centroids.copy()
    block[FEATURE] = frl.reindex(block.index)
    block[WEIGHT_COL] = nstu.reindex(block.index).fillna(0).astype(int)
    # Keep blocks with students for weighting; lat/lon for all for diameter lookups
    n_pos = int((block[WEIGHT_COL] > 0).sum())
    logger.info(
        "block_data: %d blocks in centroids, %d with students, %d with FRL",
        len(block),
        n_pos,
        int(block[FEATURE].notna().sum()),
    )
    return block


def load_zone_lists(zones_dir: Path) -> dict[str, list[list[str]]]:
    """Load ``*_BG.csv`` / ``*_B.csv`` under zones_dir (recursive)."""
    zone_lists: dict[str, list[list[str]]] = {}
    for path in sorted(Path(zones_dir).rglob("*.csv")):
        stem = path.stem
        if not (stem.endswith("_BG") or stem.endswith("_B")):
            continue
        with path.open(newline="", encoding="utf-8") as f:
            rows = [[normalize_geoid(c) for c in row if str(c).strip()] for row in csv.reader(f)]
        rows = [r for r in rows if r]
        if not rows:
            continue
        # Prefer unique stems; nested duplicates overwrite with later path — OK
        zone_lists[stem] = rows
    logger.info("Loaded %d zone maps from %s", len(zone_lists), zones_dir)
    return zone_lists


def highlight_label(map_name: str) -> str | None:
    return HIGHLIGHT_STEMS.get(map_name)


def zone_diameter_miles(
    unit_ids: list[str],
    unit_col: str | None,
    block_data: pd.DataFrame,
) -> float:
    """Max pairwise WGS84 geodesic distance (miles) among blocks in the zone.

    Same metric as s01 ``geodesic_distance_matrix_df_from_df`` /
    ``Geod(ellps='WGS84')`` (then / 1609.34). Computed on the fly for the
    zone's points only — no city-wide precomputed matrix.
    """
    if unit_col == "block_group":
        mask = block_data["block_group"].isin(unit_ids)
        pts = block_data.loc[mask, ["lat", "lon"]].dropna()
    else:
        geoids = [g for g in unit_ids if g in block_data.index]
        pts = block_data.loc[geoids, ["lat", "lon"]].dropna()

    if len(pts) < 2:
        return float("nan")
    lats = pts["lat"].to_numpy(dtype=float)
    lons = pts["lon"].to_numpy(dtype=float)
    n = len(lats)
    max_m = 0.0
    # Vectorized inv per origin (same pattern as s01); faster than pdist+Python metric.
    for i in range(n):
        _, _, dist_m = _GEOD.inv(np.full(n, lons[i]), np.full(n, lats[i]), lons, lats)
        max_m = max(max_m, float(np.max(dist_m)))
    return max_m / METERS_PER_MILE


def compute_zone_map_rows(
    block_data: pd.DataFrame,
    zone_lists: dict[str, list[list[str]]],
    z_stat: str,
) -> pd.DataFrame:
    """One (radius, zone_deviation) point per zone map."""
    occupied = block_data.loc[block_data[WEIGHT_COL] > 0].dropna(subset=[FEATURE])
    if occupied.empty:
        raise SystemExit("No blocks with students and FRL")

    v = occupied[FEATURE].astype(float)
    w = occupied[WEIGHT_COL].astype(float)
    global_mean = float(np.dot(w, v) / w.sum())

    # Precompute unit means at block and block-group level
    block_means = pd.DataFrame(
        {"unit_mean": v, "unit_size": w},
        index=occupied.index,
    )
    bg_num = (v * w).groupby(occupied["block_group"]).sum()
    bg_den = w.groupby(occupied["block_group"]).sum()
    bg_means = pd.DataFrame({"unit_mean": bg_num / bg_den, "unit_size": bg_den})

    rows = []
    t0 = time.time()
    for i, (map_name, zones) in enumerate(zone_lists.items()):
        unit = "block_group" if map_name.endswith("_BG") else None
        unit_stats = bg_means if unit == "block_group" else block_means

        zone_ds = []
        zone_diams = []
        for unit_ids in zones:
            subset = unit_stats.loc[unit_stats.index.intersection(unit_ids)]
            if subset.empty:
                continue
            tw = float(subset["unit_size"].sum())
            if tw <= 0:
                continue
            subset_mean = float((subset["unit_mean"] * subset["unit_size"]).sum() / tw)
            d_s = abs(subset_mean - global_mean)
            diam = zone_diameter_miles(unit_ids, unit, block_data)
            if diam != diam:
                continue
            zone_ds.append(d_s)
            zone_diams.append(diam)

        if not zone_ds:
            continue

        zd = np.asarray(zone_ds, dtype=float)
        zr = np.asarray(zone_diams, dtype=float) / 2.0
        if z_stat == "max":
            j = int(np.nanargmax(zd))
            total_d = float(zd[j])
            mean_r = float(zr[j])
        else:  # mean_equal
            total_d = float(np.nanmean(zd))
            mean_r = float(np.nanmean(zr))

        if mean_r != mean_r or total_d != total_d or mean_r > MAX_R_FILTER:
            continue

        label = highlight_label(map_name)
        rows.append(
            {
                "radius": mean_r,
                "zone_deviation": total_d,
                "highlight": label is not None,
                "label": label or map_name,
            }
        )
        if (i + 1) % 50 == 0:
            logger.info("  maps %d/%d (%.1fs)", i + 1, len(zone_lists), time.time() - t0)

    logger.info("Summarized %d maps in %.1fs (z_stat=%s)", len(rows), time.time() - t0, z_stat)
    return pd.DataFrame(rows)


def estimate_district_radius_miles(block_data: pd.DataFrame) -> float:
    """Geodesic centroid fallback (prefer PAPER_DISTRICT_RAD_MILES)."""
    occ = block_data.loc[block_data[WEIGHT_COL] > 0, ["lat", "lon"]].dropna()
    if len(occ) < 2:
        return float("nan")
    coords = occ.to_numpy(dtype=float)
    # Vectorized Geod (same as s01) — faster than pdist custom metric at city scale.
    n = len(coords)
    dists = []
    lats, lons = coords[:, 0], coords[:, 1]
    for i in range(n):
        _, _, dist_m = _GEOD.inv(np.full(n, lons[i]), np.full(n, lats[i]), lons, lats)
        dists.append(dist_m)
    all_d = np.concatenate(dists) / METERS_PER_MILE
    diam = float(np.nanpercentile(all_d, 99.5))
    return diam / 2.0


def compute_local_index(block_data: pd.DataFrame, radius_miles: float) -> np.ndarray:
    """Per-block |local weighted mean FRL − global| (s03 / export recipe).

    Neighborhoods use Web Mercator meters and ``r * 1609.34``, matching the
    private notebook. Zone diameters use WGS84 geodesic miles (same as s01).
    """
    need = [FEATURE, "lat", "lon", WEIGHT_COL]
    df = block_data.dropna(subset=need).copy()
    # Keep zero-weight rows out of the neighbor set for means, but match export
    # by requiring positive weight for focal blocks that contribute to the curve.
    df = df.loc[df[WEIGHT_COL].astype(float) > 0]
    if df.empty:
        return np.array([])

    values = df[FEATURE].astype(float).to_numpy()
    weights = df[WEIGHT_COL].astype(float).to_numpy()
    coords = project_web_mercator_meters(df["lat"].to_numpy(), df["lon"].to_numpy())
    n = len(values)

    w_tot = float(np.nansum(weights))
    if w_tot <= 0:
        return np.full(n, np.nan)
    mu = float(np.nansum(weights * values) / w_tot)

    tree = cKDTree(coords)
    r_meters = float(radius_miles) * METERS_PER_MILE
    local_d = np.full(n, np.nan)
    for i in range(n):
        idx = tree.query_ball_point(coords[i], r=r_meters)
        if not idx:
            continue
        idx = np.asarray(idx, dtype=int)
        w_n, v_n = weights[idx], values[idx]
        ok = np.isfinite(w_n) & np.isfinite(v_n) & (w_n > 0)
        if not np.any(ok):
            continue
        w_n, v_n = w_n[ok], v_n[ok]
        loc_mean = float(np.dot(w_n, v_n) / np.sum(w_n))
        local_d[i] = abs(loc_mean - mu)
    return local_d


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    m = np.isfinite(v) & np.isfinite(w) & (w > 0)
    if not np.any(m):
        return float("nan")
    return float(np.dot(w[m], v[m]) / np.sum(w[m]))


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """Linear interpolation on the weighted CDF (matches paper export helper)."""
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    m = np.isfinite(v) & np.isfinite(w) & (w > 0)
    v, w = v[m], w[m]
    if v.size == 0:
        return float("nan")
    order = np.argsort(v)
    v, w = v[order], w[order]
    cw = np.cumsum(w)
    cut = float(np.clip(q, 0.0, 1.0)) * float(cw[-1])
    k = int(np.searchsorted(cw, cut, side="left"))
    if k <= 0:
        return float(v[0])
    if k >= len(v):
        return float(v[-1])
    c0, c1 = float(cw[k - 1]), float(cw[k])
    if c1 <= c0:
        return float(v[k])
    alpha = (cut - c0) / (c1 - c0)
    return float((1.0 - alpha) * v[k - 1] + alpha * v[k])


def build_curve(
    block_data: pd.DataFrame,
    r_stat: str,
    district_rad: float | None,
    radii: np.ndarray = RADII,
) -> pd.DataFrame:
    df = block_data.dropna(subset=[FEATURE, "lat", "lon", WEIGHT_COL])
    df = df.loc[df[WEIGHT_COL].astype(float) > 0]
    weights = df[WEIGHT_COL].astype(float).to_numpy()
    rows = []
    t0 = time.time()
    for r in radii:
        local_d = compute_local_index(block_data, float(r))
        if r_stat == "mean":
            y = _weighted_mean(local_d, weights)
        elif r_stat == "quantile_square":
            if district_rad is None or not np.isfinite(district_rad) or district_rad <= 0:
                raise ValueError("district_rad required for quantile_square")
            q = max(0.0, 1.0 - (float(r) / float(district_rad)) ** 2)
            y = _weighted_quantile(local_d, weights, q)
        else:
            raise ValueError(r_stat)
        rows.append({"radius": float(r), "spatial_segregation_index": y})
    logger.info("Curve %s done in %.1fs", r_stat, time.time() - t0)
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--students", type=Path, required=True, help="Student CSV (synthetic or authorized).")
    p.add_argument("--centroids", type=Path, default=DEFAULT_CENTROIDS)
    p.add_argument("--zones-dir", type=Path, default=DEFAULT_ZONES)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--district-rad",
        type=float,
        default=PAPER_DISTRICT_RAD_MILES,
        help=(
            f"District radius R (miles) for quantile curve q(r)=1-(r/R)^2. "
            f"Default {PAPER_DISTRICT_RAD_MILES} (paper / path-1 value)."
        ),
    )
    p.add_argument(
        "--estimate-district-rad",
        action="store_true",
        help="Override --district-rad with centroid pairwise 99.5th-pct / 2 (not recommended).",
    )
    p.add_argument("--skip-curve", action="store_true", help="Only compute map scatter points.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    centroids = load_centroids(args.centroids)
    block_data = build_block_data(args.students, centroids)
    zone_lists = load_zone_lists(args.zones_dir)

    mean_maps = compute_zone_map_rows(block_data, zone_lists, z_stat="mean_equal")
    quant_maps = compute_zone_map_rows(block_data, zone_lists, z_stat="max")
    mean_maps.to_csv(args.out_dir / "fig3_mean_maps.csv", index=False)
    quant_maps.to_csv(args.out_dir / "fig3_quantile_maps.csv", index=False)
    logger.info(
        "Wrote maps: mean=%d (highlight=%d), quantile=%d (highlight=%d)",
        len(mean_maps),
        int(mean_maps["highlight"].sum()),
        len(quant_maps),
        int(quant_maps["highlight"].sum()),
    )

    if args.skip_curve:
        mean_curve = pd.DataFrame(columns=["radius", "spatial_segregation_index"])
        quant_curve = pd.DataFrame(columns=["radius", "spatial_segregation_index"])
        district_rad = float("nan")
    else:
        if args.estimate_district_rad:
            district_rad = estimate_district_radius_miles(block_data)
            logger.info("Estimated district_rad ≈ %.4f miles (centroid fallback)", district_rad)
        else:
            district_rad = float(args.district_rad)
            logger.info("Using district_rad = %.6f miles", district_rad)
        mean_curve = build_curve(block_data, "mean", district_rad=None)
        quant_curve = build_curve(block_data, "quantile_square", district_rad=district_rad)

    mean_curve.to_csv(args.out_dir / "fig3_mean_curve.csv", index=False)
    quant_curve.to_csv(args.out_dir / "fig3_quantile_curve.csv", index=False)

    meta = {
        "feature": FEATURE,
        "weight_col": WEIGHT_COL,
        "district_rad": district_rad,
        "district_rad_source": (
            "centroid_estimate" if args.estimate_district_rad else "paper_default_or_flag"
        ),
        "local_index_crs": "EPSG:3857",
        "source": "synthetic_or_custom",
        "students": str(args.students),
        "centroids": str(args.centroids),
        "note": "Path 2 recompute — values are not expected to match paper path-1 CSVs.",
        "panels": {
            "mean": {
                "title": "Weighted Mean Spatial Deviation vs Zone Deviation",
                "curve_legend": r"Weighted mean spatial deviation, $\bar{D}(r)$",
                "maps_csv": "fig3_mean_maps.csv",
                "curve_csv": "fig3_mean_curve.csv",
                "outfile": "fig3_mean.png",
            },
            "quantile": {
                "title": "Quantile Spatial Deviation vs Max Zone Deviation",
                "curve_legend": r"Quantile spatial deviation, $\bar{D}^{q(r)}(r)$",
                "maps_csv": "fig3_quantile_maps.csv",
                "curve_csv": "fig3_quantile_curve.csv",
                "outfile": "fig3_quantile.png",
            },
        },
    }
    import json

    (args.out_dir / "fig3_metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote outputs under %s", args.out_dir)


if __name__ == "__main__":
    main()
