"""Run + analyze Track A mnl_cde Table 1 (resume/skip).

Configs from ``scripts/generate_syn_mnl_cde_configs.py``:
  local-data/syn_mnl_cde_table1.yaml
  local-data/syn_mnl_cde_table1_analysis.yaml
Run tag: smpc_t1. Metric tag: syn_mnl_cde_table1.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LD = REPO / "local-data"
LOG = LD / "_syn_mnl_cde_table1_batch.log"
METRICS = LD / "metrics"

SIM = LD / "syn_mnl_cde_table1.yaml"
ANALYSIS = LD / "syn_mnl_cde_table1_analysis.yaml"
METRIC_TAG = "syn_mnl_cde_table1"


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
        LOG.write_text("Table 1 mnl_cde batch start\n", encoding="utf-8")
    else:
        log("\n--- Resume / continue Table 1 batch ---\n")

    if not SIM.exists():
        raise SystemExit(
            f"Missing config: {SIM}\n"
            "Run: uv run python scripts/generate_syn_mnl_cde_configs.py"
        )
    if done(METRIC_TAG):
        log(f"SKIP (metrics exist): {METRIC_TAG}")
        log("TABLE 1 mnl_cde COMPLETE")
        return

    run(["uv", "run", "python", "run_custom_config.py", "--config-path", str(SIM)])
    run(
        [
            "uv",
            "run",
            "python",
            "scripts/analysis/analyze_trends.py",
            "--config",
            str(ANALYSIS),
        ]
    )
    if not done(METRIC_TAG):
        raise SystemExit(
            f"Missing metrics_comparison.xlsx after analyze: {METRIC_TAG}"
        )
    log("TABLE 1 mnl_cde COMPLETE")


if __name__ == "__main__":
    main()
