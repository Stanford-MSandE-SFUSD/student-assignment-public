"""Replot paper Figure 3 from committed CSVs (no microdata).

Reads scatter + curve values under ``data/figures/fig3/`` and writes the two
PNAS panels.

Example::

    uv run python scripts/analysis/plot_fig3.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = _PROJECT_ROOT / "data" / "figures" / "fig3"
DEFAULT_OUT = _PROJECT_ROOT / "local-data" / "figures" / "fig3"

PANELS = {
    "mean": {
        "maps": "fig3_mean_maps.csv",
        "curve": "fig3_mean_curve.csv",
        "title": "Weighted Mean Spatial Deviation vs Zone Deviation",
        "y_label": "Deviation (FRL)",
        "curve_legend": r"Weighted mean spatial deviation, $\bar{D}(r)$",
        "outfile": "fig3_mean.png",
    },
    "quantile": {
        "maps": "fig3_quantile_maps.csv",
        "curve": "fig3_quantile_curve.csv",
        "title": "Quantile Spatial Deviation vs Max Zone Deviation",
        "y_label": "Deviation (FRL)",
        "curve_legend": r"Quantile spatial deviation, $\bar{D}^{q(r)}(r)$",
        "outfile": "fig3_quantile.png",
    },
}


def legend_handles(curve_legend: str):
    return [
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor="steelblue",
            markeredgecolor="black",
            markersize=15,
            label="Policies compared",
        ),
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor="#777777",
            alpha=0.4,
            markersize=10,
            label="Other zone maps",
        ),
        Line2D(
            [0],
            [0],
            color="#444444",
            ls=":",
            lw=4,
            alpha=0.5,
            label=curve_legend,
        ),
    ]


def plot_panel(
    maps_df: pd.DataFrame,
    curve_df: pd.DataFrame,
    *,
    title: str,
    y_label: str,
    curve_legend: str,
    out_path: Path,
) -> None:
    plt.rcParams.update({"font.size": 20})
    fig, ax = plt.subplots(figsize=(18, 13))

    bg = maps_df.loc[~maps_df["highlight"].astype(bool)]
    fg = maps_df.loc[maps_df["highlight"].astype(bool)]

    if not bg.empty:
        ax.scatter(
            bg["radius"],
            bg["zone_deviation"],
            c="#777777",
            alpha=0.5,
            edgecolors="none",
            s=120,
            zorder=2,
        )

    if not curve_df.empty:
        ax.plot(
            curve_df["radius"],
            curve_df["spatial_segregation_index"],
            color="#444444",
            ls=":",
            lw=4,
            alpha=0.5,
            zorder=1,
        )

    if not fg.empty:
        ax.scatter(
            fg["radius"],
            fg["zone_deviation"],
            c="steelblue",
            edgecolors="black",
            linewidth=2.5,
            s=450,
            zorder=6,
        )
        for _, row in fg.iterrows():
            ax.text(
                row["radius"] + 0.05,
                row["zone_deviation"] + 0.005,
                str(row["label"]),
                fontsize=20,
                fontweight="bold",
                color="black",
                zorder=10,
            )

    ax.set_title(title, fontsize=26, pad=30)
    ax.set_xlabel("Radius $r$ (miles)", fontsize=22)
    ax.set_ylabel(y_label, fontsize=22)
    ax.grid(True, ls=":", alpha=0.15)
    ax.legend(
        handles=legend_handles(curve_legend),
        loc="upper right",
        bbox_to_anchor=(0.985, 0.975),
        fontsize=22,
        frameon=True,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white", pad_inches=0.2)
    plt.close(fig)
    plt.rcParams.update({"font.size": 10})
    print(f"Wrote {out_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    meta_path = args.data_dir / "fig3_metadata.json"
    meta_panels: dict = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta_panels = meta.get("panels") or {}

    for key, cfg in PANELS.items():
        override = meta_panels.get(key) or {}
        maps_path = args.data_dir / cfg["maps"]
        curve_path = args.data_dir / cfg["curve"]
        if not maps_path.exists():
            raise SystemExit(f"Missing {maps_path}")

        maps_df = pd.read_csv(maps_path)
        curve_df = pd.read_csv(curve_path) if curve_path.exists() else pd.DataFrame()
        if maps_df["highlight"].dtype == object:
            maps_df["highlight"] = (
                maps_df["highlight"].astype(str).str.lower().isin(["true", "1", "yes"])
            )

        plot_panel(
            maps_df,
            curve_df,
            title=override.get("title", cfg["title"]),
            y_label=cfg["y_label"],
            curve_legend=override.get("curve_legend", cfg["curve_legend"]),
            out_path=args.out_dir / override.get("outfile", cfg["outfile"]),
        )


if __name__ == "__main__":
    main()
