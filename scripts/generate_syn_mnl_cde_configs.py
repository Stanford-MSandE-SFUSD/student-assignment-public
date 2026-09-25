"""Generate Track A mnl_cde Table 1 + SI configs (no ``_joint`` in names).

Writes under ``local-data/`` in this checkout (gitignored). Pack:
``data/synthetic_2324/``; estimates: ``local-data/estimates_syn/mnl_cde/``.

Usage::

    uv run python scripts/generate_syn_mnl_cde_configs.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
LD = REPO / "local-data"
SYN = REPO / "data" / "synthetic_2324"
EST = LD / "estimates_syn" / "mnl_cde"
ZONES = REPO / "data" / "zones" / "table1"

T14 = str(EST / "estimates_t14_2223_k1_prog_gesplit_2324.csv")
T17 = str(EST / "estimates_t17_2223_k1_prog_gesplit_2324.csv")
T141718 = str(EST / "estimates_t14_1718_k1_prog_gesplit_2324.csv")
NO_EST = str(LD / "no-estimates.csv")

TABLE1_SUB = [
    "status_quo",
    "13-0.25-2500_BG+no_reserves",
    "13-0.25-2500_BG+reserves_05frl",
    "6-0.10-1430_BG+no_reserves",
    "6-0.10-1430_BG+reserves_05frl",
    "distance_05_1_2+reserves_05frl",
    "status_quo+reserves_05frl",
]

TABLE1_LABELS = [
    ("Status Quo", "status_quo"),
    ("Small Zones", "13-0.25-2500_BG+no_reserves"),
    ("Small+Reserves", "13-0.25-2500_BG+reserves_05frl"),
    ("Medium Zones", "6-0.10-1430_BG+no_reserves"),
    ("Medium+Reserves", "6-0.10-1430_BG+reserves_05frl"),
    ("Dist Priority+Reserves", "distance_05_1_2+reserves_05frl"),
    ("Status Quo+Reserves", "status_quo+reserves_05frl"),
]


def _zone_files() -> dict[str, str]:
    con1 = ZONES / "concept1zones.csv"
    if not con1.exists():
        con1 = SYN / "zones" / "concept1zones.csv"
    return {
        "Con1": str(con1),
        "13-0.25-2500_BG": str(ZONES / "13-0.25-2500_BG.csv"),
        "6-0.10-1430_BG": str(ZONES / "6-0.10-1430_BG.csv"),
        "10-0.15-2250_BG": str(ZONES / "10-0.15-2250_BG.csv"),
    }


def _paths(run_tag: str, estimate: str) -> dict:
    run_root = LD / "local-runs" / run_tag
    return {
        "sfusd": str(SYN) + "/",
        "student-data": str(SYN / "student_2324_synthetic.csv"),
        "program-data": str(SYN / "programs_without_specialprogs_2324.csv"),
        "school-data": str(SYN / "Cleaned" / "schools_rehauled_2324.csv"),
        "student-save": str(LD / "Precomputed" / run_tag) + "/",
        "assignment-folder": str(run_root) + "/",
        "estimate-path": estimate,
        "zone-files": _zone_files(),
    }


def _sim(
    run_tag: str,
    estimate: str,
    list_length,
    subconfigs: list[str],
    enable: bool = True,
) -> dict:
    return {
        "desig_after_mainround": False,
        "grade": "KG",
        "year": 23,
        "r1-only": True,
        "random-seed": 2023,
        "remove-special-lps": True,
        "save-assignment": True,
        "save-preference-matrix": False,
        "iterations": {"start": 0, "end": 25},
        "rounds-merged-options": [0],
        "utility-model": {
            "enable": enable,
            "designate-lp-for-all": False,
            "list-length": list_length,
            "save-path": str(LD / "local-runs" / run_tag / "utility_matrix.csv"),
        },
        "paths": _paths(run_tag, estimate),
        "subconfigs": subconfigs,
    }


def _analysis(
    metric_tag: str, run_tag: str, labels_folders: list[tuple[str, str]]
) -> dict:
    prog = str(SYN / "programs_without_specialprogs_2324.csv")
    stu = str(SYN / "student_2324_synthetic.csv")
    runs = []
    for label, folder in labels_folders:
        runs.append(
            {
                "label": label,
                "folder": str(LD / "local-runs" / run_tag / folder),
                "year": 23,
                "program_data": prog,
                "student_data": stu,
            }
        )
    return {
        "output_dir": str(LD / "metrics" / metric_tag),
        "schools_data": str(SYN / "Cleaned" / "schools_rehauled_2324.csv"),
        "runs": runs,
    }


def dump(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(obj, fh, sort_keys=False, default_flow_style=False)


def main() -> None:
    for p in (
        SYN / "student_2324_synthetic.csv",
        EST / "estimates_t14_2223_k1_prog_gesplit_2324.csv",
        ZONES / "13-0.25-2500_BG.csv",
    ):
        if not p.exists():
            raise FileNotFoundError(
                f"Missing {p}. Generate estimates via "
                "scripts/generate_syn_estimates_cde.py and ensure "
                "data/zones/table1/ exists."
            )

    no_est = Path(NO_EST)
    if not no_est.exists():
        no_est.parent.mkdir(parents=True, exist_ok=True)
        no_est.write_text("studentno\n", encoding="utf-8")

    jobs: list[tuple[str, str]] = []

    # --- Table 1 ---
    dump(
        LD / "syn_mnl_cde_table1.yaml",
        _sim("smpc_t1", T14, "0.8*round(real_length)", TABLE1_SUB),
    )
    dump(
        LD / "syn_mnl_cde_table1_analysis.yaml",
        _analysis("syn_mnl_cde_table1", "smpc_t1", TABLE1_LABELS),
    )
    jobs.append(("syn_mnl_cde_table1.yaml", "syn_mnl_cde_table1_analysis.yaml"))

    # --- SI Step 3 ---
    specs = [
        ("smpc_llr", "syn_mnl_cde_llreal", T14, "real_length", TABLE1_SUB, TABLE1_LABELS),
        ("smpc_ll10", "syn_mnl_cde_ll10", T14, "10", TABLE1_SUB, TABLE1_LABELS),
        (
            "smpc_mb",
            "syn_mnl_cde_model_b",
            T17,
            "0.8*round(real_length)",
            TABLE1_SUB,
            TABLE1_LABELS,
        ),
        (
            "smpc_yr",
            "syn_mnl_cde_years_1718_2324",
            T141718,
            "0.8*round(real_length)",
            TABLE1_SUB,
            TABLE1_LABELS,
        ),
    ]
    for run_tag, metric_tag, est, ll, subs, labels in specs:
        dump(LD / f"{metric_tag}.yaml", _sim(run_tag, est, ll, subs))
        dump(LD / f"{metric_tag}_analysis.yaml", _analysis(metric_tag, run_tag, labels))
        jobs.append((f"{metric_tag}.yaml", f"{metric_tag}_analysis.yaml"))

    res_subs = [
        "13-0.25-2500_BG+reserves_06frl",
        "13-0.25-2500_BG+reserves",
        "6-0.10-1430_BG+reserves_06frl",
        "6-0.10-1430_BG+reserves",
        "distance_05_1_2+reserves_06frl",
        "distance_05_1_2+reserves",
    ]
    res_labels = [
        ("Small+Res A", "13-0.25-2500_BG+reserves_06frl"),
        ("Small+Res B", "13-0.25-2500_BG+reserves"),
        ("Medium+Res A", "6-0.10-1430_BG+reserves_06frl"),
        ("Medium+Res B", "6-0.10-1430_BG+reserves"),
        ("Dist+Res A", "distance_05_1_2+reserves_06frl"),
        ("Dist+Res B", "distance_05_1_2+reserves"),
    ]
    dump(
        LD / "syn_mnl_cde_reserves_ab.yaml",
        _sim("smpc_res", T14, "0.8*round(real_length)", res_subs),
    )
    dump(
        LD / "syn_mnl_cde_reserves_ab_analysis.yaml",
        _analysis("syn_mnl_cde_reserves_ab", "smpc_res", res_labels),
    )
    jobs.append(("syn_mnl_cde_reserves_ab.yaml", "syn_mnl_cde_reserves_ab_analysis.yaml"))

    dist_subs = [
        "distance_05_1+reserves_05frl",
        "distance_05_1+reserves_06frl",
        "distance_05_1+reserves",
        "distance_075_2+reserves_05frl",
        "distance_075_2+reserves_06frl",
        "distance_075_2+reserves",
    ]
    dist_labels = [
        ("Dist A+Res", "distance_05_1+reserves_05frl"),
        ("Dist A+Res A", "distance_05_1+reserves_06frl"),
        ("Dist A+Res B", "distance_05_1+reserves"),
        ("Dist B+Res", "distance_075_2+reserves_05frl"),
        ("Dist B+Res A", "distance_075_2+reserves_06frl"),
        ("Dist B+Res B", "distance_075_2+reserves"),
    ]
    dump(
        LD / "syn_mnl_cde_dist_ab.yaml",
        _sim("smpc_dist", T14, "0.8*round(real_length)", dist_subs),
    )
    dump(
        LD / "syn_mnl_cde_dist_ab_analysis.yaml",
        _analysis("syn_mnl_cde_dist_ab", "smpc_dist", dist_labels),
    )
    jobs.append(("syn_mnl_cde_dist_ab.yaml", "syn_mnl_cde_dist_ab_analysis.yaml"))

    listlen = [
        ("real_prefs", False, "real_length", NO_EST),
        ("actual", True, "real_length", T14),
        ("0p8", True, "0.8*round(real_length)", T14),
        ("0p7", True, "0.7*round(real_length)", T14),
        ("0p6", True, "0.6*round(real_length)", T14),
        ("ll7", True, "7", T14),
        ("ll10", True, "10", T14),
    ]
    ll_dir = LD / "syn_mnl_cde_listlen_sq"
    ll_labels: list[tuple[str, str]] = []
    label_map = {
        "real_prefs": "Real preferences",
        "actual": "Actual length",
        "0p8": "80%",
        "0p7": "70%",
        "0p6": "60%",
        "ll7": "7",
        "ll10": "10",
    }
    for key, enable, ll, est in listlen:
        run_tag = f"smpc_llsq/{key}"
        dump(
            ll_dir / f"{key}.yaml",
            _sim(run_tag, est, ll, ["status_quo"], enable=enable),
        )
        ll_labels.append((label_map[key], f"{key}/status_quo"))

    dump(
        LD / "syn_mnl_cde_listlen_sq_analysis.yaml",
        _analysis("syn_mnl_cde_listlen_sq", "smpc_llsq", ll_labels),
    )

    manifest = LD / "_syn_mnl_cde_jobs.txt"
    lines = ["# Table 1 + SI jobs (relative to local-data/)", *[f"{a}\t{b}" for a, b in jobs]]
    lines.append("LISTLEN")
    for key, _, _, _ in listlen:
        lines.append(f"syn_mnl_cde_listlen_sq/{key}.yaml")
    lines.append("syn_mnl_cde_listlen_sq_analysis.yaml")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote configs under {LD}")
    print(f"Manifest: {manifest}")
    print("Table 1: syn_mnl_cde_table1.yaml")
    for a, b in jobs[1:]:
        print(f"  SI {a} -> {b}")
    print("  SI listlen -> syn_mnl_cde_listlen_sq/")


if __name__ == "__main__":
    main()
