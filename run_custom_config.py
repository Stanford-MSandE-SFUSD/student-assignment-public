"""@author: Edouard Rabasse
@date: 01-09-2026
This script allows passing a custom configuration YAML file AND overriding specific variables.
The CLI is: python run_custom_config.py --config-path config.yaml --sample sample001 --frac frac0.40.

Parallelism: use --workers N to simulate N subconfigs concurrently (one process each).
Each worker gets its own Configerator singleton and numpy random state, so results
are identical to a sequential run (each subconfig resets np.random.seed internally).
"""

import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import click
import yaml

# Ensure we can import your project modules
sys.path.append(os.getcwd())

from student_assignment.configerator import Configerator
from student_assignment.market_generator.school_choice_market_generator import (
    MarketGenerator,
)


def resolve_variables(item, root_config):
    """Recursively replaces ${var} in strings using values from root_config."""
    if isinstance(item, dict):
        return {k: resolve_variables(v, root_config) for k, v in item.items()}
    elif isinstance(item, list):
        return [resolve_variables(v, root_config) for v in item]
    elif isinstance(item, str):
        pattern = re.compile(r"\$\{([^\}]+)\}")

        def replace(match):
            key = match.group(1)
            if key in root_config:
                return str(root_config[key])
            else:
                print(f"Warning: Could not resolve variable ${{{key}}}")
                return match.group(0)

        return pattern.sub(replace, item)
    else:
        return item


def _run_subconfig_worker(custom_config: dict, subconfig_name: str) -> None:
    """Run a single subconfig in an isolated worker process.

    Must be a top-level function to be picklable by ProcessPoolExecutor.
    Each worker process has its own Configerator singleton and numpy random
    state, so results are deterministic and independent of execution order.

    Args:
        custom_config: Fully resolved base configuration dict.
        subconfig_name: Name of the subconfig to run (maps to a file in
            SUBCONFIGS_DIR).
    """
    # Reset the singleton so this process starts from a clean slate.
    # Required when the parent process used fork and inherited an instance.
    Configerator.instance = None

    single_config = {**custom_config, "subconfigs": [subconfig_name]}

    c = Configerator()
    c._config = single_config
    c._original_config = single_config
    c.subconfigs = iter([subconfig_name])

    print(f"--> [Worker] Starting subconfig: {subconfig_name}")
    m = MarketGenerator()
    m.simulate()
    print(f"--> [Worker] Completed subconfig: {subconfig_name}")


@click.command()
@click.option(
    "--config-path",
    "--config_path",
    "config_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to the base configuration file.",
)
@click.option(
    "--sample",
    default=None,
    help="Override the sample variable (e.g., sample001)",
)
@click.option(
    "--frac", default=None, help="Override the frac variable (e.g., frac0.40)"
)
@click.option(
    "--workers",
    default=1,
    show_default=True,
    help="Number of parallel worker processes. Each subconfig runs in its own "
    "process. workers=1 is the original sequential behaviour.",
)
def generate(config_path, sample, frac, workers):
    print(f"--> Loading configuration from: {config_path}")

    # 1. Load the raw YAML
    with open(config_path) as f:
        raw_config = yaml.safe_load(f)

    # 2. APPLY OVERRIDES HERE
    if sample:
        print(f"--> Overriding sample: {sample}")
        raw_config["sample"] = sample
    if frac:
        print(f"--> Overriding frac: {frac}")
        raw_config["frac"] = frac

    # 3. Resolve variables using the updated raw_config
    print("--> Resolving ${variables}...")
    custom_config = resolve_variables(raw_config, raw_config)

    subconfigs_list = custom_config.get("subconfigs", [])

    # 4. Run simulations — sequentially or in parallel
    if workers == 1:
        print("--> Initializing Configerator...")
        c = Configerator()
        c._config = custom_config
        c._original_config = custom_config
        c.subconfigs = iter(subconfigs_list)

        print("--> Starting Simulation...")
        m = MarketGenerator()
        m.simulate()
    else:
        print(
            f"--> Starting parallel simulation: "
            f"{len(subconfigs_list)} subconfigs × {workers} workers..."
        )
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_run_subconfig_worker, custom_config, sub): sub
                for sub in subconfigs_list
            }
            failed = []
            for future in as_completed(futures):
                sub = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    print(f"--> [ERROR] Subconfig '{sub}' failed: {exc}")
                    failed.append(sub)

        if failed:
            raise RuntimeError(f"{len(failed)} subconfig(s) failed: {failed}")

    print("--> Simulation Complete.")


if __name__ == "__main__":
    generate()
