"""Generate MNL estimates for Track A synthetic 2324 using public CDE composition.

PUBLIC-SAFE — uses ``enrolled_cde_composition.csv`` (CDE), not confidential
enrolled. Needs an SFUSD-Choice-public checkout with calibrated weights under
``local_outputs/models/``; set ``SFUSD_CHOICE_PATH`` or place it as a sibling
of this repo named ``SFUSD-Choice-public``.

Usage (from this repo's root)::

    SFUSD_CHOICE_PATH=path/to/SFUSD-Choice-public \
        uv run python scripts/generate_syn_estimates_cde.py
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

import yaml

# This file's repo root (synthetic-2324-dataset-joint checkout)
ASSIGNMENT_PUBLIC = Path(__file__).resolve().parents[1]
# SFUSD-Choice-public checkout (calibrated MNL weights). Override with env.
CHOICE_ROOT = Path(
    __import__("os").environ.get(
        "SFUSD_CHOICE_PATH",
        str(ASSIGNMENT_PUBLIC.parent / "SFUSD-Choice-public"),
    )
)

sys.path.insert(0, str(CHOICE_ROOT))

from choice_model.config import Config  # noqa: E402
from choice_model.data import DataGenerator  # noqa: E402
from choice_model.model.calibrated_mnl_model import (  # noqa: E402
    CalibratedMNLModel,
)

logger = logging.getLogger(__name__)

SYN_DIR = ASSIGNMENT_PUBLIC / "data" / "synthetic_2324"
ENROLLED_PUB = SYN_DIR / "reference" / "enrolled_cde_composition.csv"
OUT_ESTIMATES = ASSIGNMENT_PUBLIC / "local-data" / "estimates_syn" / "mnl_cde"
MODELS_DIR = CHOICE_ROOT / "local_outputs" / "models"
COMPUTED_ROOT = ASSIGNMENT_PUBLIC / "local-data" / "syn2324_cde_choice_cache"

MODELS = [
    "t14_2223_k1_prog_gesplit",
    "t17_2223_k1_prog_gesplit",
    "t9_2223_k1_prog_gesplit",
    "t14_1718_k1_prog_gesplit",
]
SYN_SUFFIX = "_syn2324_cde"


def _syn_data_block() -> dict:
    return {
        2324: {
            "student_data_file": str(SYN_DIR / "student_2324_synthetic.csv"),
            "program_data_file": str(
                SYN_DIR / "programs_without_specialprogs_2324.csv"
            ),
            "school_data_file": str(
                SYN_DIR / "Cleaned" / "schools_rehauled_2324.csv"
            ),
            "enrolled_data_file": str(ENROLLED_PUB),
        }
    }


def _patch_config(src_config: Path, dest_config: Path, output_path: Path) -> None:
    with open(src_config, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    raw.setdefault("path", {})
    raw["path"]["output_path"] = str(output_path)
    raw["path"].setdefault(
        "student_data_file", "student_without_specialprogs_{year}.csv"
    )
    raw["path"].setdefault(
        "program_data_file", "programs_without_specialprogs_{year}.csv"
    )
    raw["path"].setdefault("school_data_file", "schools_rehauled_{year}.csv")
    raw["path"].setdefault("enrolled_data_file", "enrolled_{year}.csv")
    raw["path"].setdefault("distance_data_file", "distance_{year}.csv")
    raw["path"].setdefault("feature_data_file", "features_{year}.csv")
    raw["path"]["input_data_path"] = str(SYN_DIR)
    raw["data"] = _syn_data_block()
    raw.setdefault("test", {})["years"] = [2324]
    dest_config.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_config, "w", encoding="utf-8") as fh:
        yaml.safe_dump(raw, fh, sort_keys=False)


def _prepare_model_dir(base_name: str) -> Path:
    src = MODELS_DIR / base_name
    dest = COMPUTED_ROOT / "models" / f"{base_name}{SYN_SUFFIX}"
    if not (src / "weights.csv").exists():
        raise FileNotFoundError(src / "weights.csv")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "weights.csv", dest / "weights.csv")
    _patch_config(src / "config_used.yaml", dest / "config_used.yaml", COMPUTED_ROOT)
    return dest


def evaluate_one(base_name: str, force: bool = True) -> Path:
    model_dir = _prepare_model_dir(base_name)
    model_name = model_dir.name
    out_path = model_dir / "estimates_2324.csv"
    if out_path.exists() and not force:
        logger.info("%s: exists, skip", model_name)
        return out_path

    Config.instance = None
    config = Config(str(model_dir / "config_used.yaml"))
    test_data = DataGenerator(config, type="test")  # type: ignore[arg-type]
    model = CalibratedMNLModel(
        config,  # type: ignore[arg-type]
        test_data,
        model_path=model_name,
        load=True,
        use_vectorized=True,
    )
    estimates_df = model._compute_estimates(test_data)
    estimates_df.index.name = "studentno"
    estimates_df.to_csv(out_path)
    logger.info(
        "%s: %d x %d -> %s",
        model_name,
        len(estimates_df),
        estimates_df.shape[1],
        out_path,
    )
    return out_path


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    for p in (SYN_DIR / "student_2324_synthetic.csv", ENROLLED_PUB):
        if not p.exists():
            raise FileNotFoundError(p)
    COMPUTED_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_ESTIMATES.mkdir(parents=True, exist_ok=True)
    for base in MODELS:
        logger.info("=== %s ===", base)
        est = evaluate_one(base, force=True)
        dest = OUT_ESTIMATES / f"estimates_{base}_2324.csv"
        shutil.copy2(est, dest)
        logger.info("Copied -> %s", dest)
    logger.info("Done. Estimates in %s", OUT_ESTIMATES)


if __name__ == "__main__":
    main()
