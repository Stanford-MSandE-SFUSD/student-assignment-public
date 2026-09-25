"""Sequentially run + analyze Track A mnl_cde Step-3 SI tables (resume/skip).

Configs from ``scripts/generate_syn_mnl_cde_configs.py`` (no ``_joint`` names).
Run tags: smpc_llr / smpc_ll10 / smpc_mb / smpc_res / smpc_dist / smpc_yr /
smpc_llsq/*.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LD = REPO / "local-data"
LOG = LD / "_syn_mnl_cde_step3_batch.log"
METRICS = LD / "metrics"

JOBS: list[tuple[Path, Path, str]] = [
    (
        LD / "syn_mnl_cde_llreal.yaml",
        LD / "syn_mnl_cde_llreal_analysis.yaml",
        "syn_mnl_cde_llreal",
    ),
    (
        LD / "syn_mnl_cde_ll10.yaml",
        LD / "syn_mnl_cde_ll10_analysis.yaml",
        "syn_mnl_cde_ll10",
    ),
    (
        LD / "syn_mnl_cde_model_b.yaml",
        LD / "syn_mnl_cde_model_b_analysis.yaml",
        "syn_mnl_cde_model_b",
    ),
    (
        LD / "syn_mnl_cde_reserves_ab.yaml",
        LD / "syn_mnl_cde_reserves_ab_analysis.yaml",
        "syn_mnl_cde_reserves_ab",
    ),
    (
        LD / "syn_mnl_cde_dist_ab.yaml",
        LD / "syn_mnl_cde_dist_ab_analysis.yaml",
        "syn_mnl_cde_dist_ab",
    ),
    (
        LD / "syn_mnl_cde_years_1718_2324.yaml",
        LD / "syn_mnl_cde_years_1718_2324_analysis.yaml",
        "syn_mnl_cde_years_1718_2324",
    ),
]

LISTLEN_KEYS = ["real_prefs", "actual", "0p8", "0p7", "0p6", "ll7", "ll10"]
LISTLEN_METRIC = "syn_mnl_cde_listlen_sq"


def log(msg: str) -> None:
    print(msg, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def done(metric_tag: str) -> bool:
    return (METRICS / metric_tag / "metrics_comparison.xlsx").exists()


def run(cmd: list[str]) -> None:
    line = " ".join(cmd)
    log(f"\n>>> {line}")
    with LOG.open("a", encoding="utf-8") as fh:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO),
            stdout=fh,
            stderr=subprocess.STDOUT,
            text=True,
        )
    if proc.returncode != 0:
        raise SystemExit(f"FAILED ({proc.returncode}): {line}")
    log("OK")


def main() -> None:
    if not LOG.exists():
        LOG.write_text("Step 3 mnl_cde batch start\n", encoding="utf-8")
    else:
        log("\n--- Resume / continue Step 3 batch ---\n")

    for sim, analysis, metric_tag in JOBS:
        if not sim.exists():
            raise SystemExit(
                f"Missing config: {sim}\n"
                "Run: uv run python scripts/generate_syn_mnl_cde_configs.py"
            )
        if done(metric_tag):
            log(f"SKIP (metrics exist): {metric_tag}")
            continue
        run(["uv", "run", "python", "run_custom_config.py", "--config-path", str(sim)])
        run(
            [
                "uv",
                "run",
                "python",
                "scripts/analysis/analyze_trends.py",
                "--config",
                str(analysis),
            ]
        )
        if not done(metric_tag):
            raise SystemExit(
                f"Missing metrics_comparison.xlsx after analyze: {metric_tag}"
            )

    if done(LISTLEN_METRIC):
        log(f"SKIP (metrics exist): {LISTLEN_METRIC}")
    else:
        for key in LISTLEN_KEYS:
            sim = LD / "syn_mnl_cde_listlen_sq" / f"{key}.yaml"
            out_dir = LD / "local-runs" / "smpc_llsq" / key / "status_quo"
            has_assign = out_dir.exists() and any(out_dir.rglob("assignment*.csv"))
            if has_assign:
                log(f"SKIP listlen sim (assignments exist): {key}")
            else:
                if not sim.exists():
                    raise SystemExit(f"Missing config: {sim}")
                run(
                    [
                        "uv",
                        "run",
                        "python",
                        "run_custom_config.py",
                        "--config-path",
                        str(sim),
                    ]
                )
        run(
            [
                "uv",
                "run",
                "python",
                "scripts/analysis/analyze_trends.py",
                "--config",
                str(LD / "syn_mnl_cde_listlen_sq_analysis.yaml"),
            ]
        )
        if not done(LISTLEN_METRIC):
            raise SystemExit(
                f"Missing metrics_comparison.xlsx after analyze: {LISTLEN_METRIC}"
            )

    log("ALL STEP 3 mnl_cde JOBS COMPLETE")


if __name__ == "__main__":
    main()
