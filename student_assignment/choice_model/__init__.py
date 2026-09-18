"""Port of the public SFUSD-Choice MNL choice model (``exp8``).

Exposes :func:`compute_utilities`, which turns student/program/school tables
plus a coefficient table into the student x program utility matrix the
assignment simulator consumes as ``estimate-path``.
"""

from .exp8 import (
    EXP8_FEATURES,
    ChoiceSetMode,
    compute_utilities,
    geodesic_miles,
    load_weights,
)

__all__ = [
    "EXP8_FEATURES",
    "ChoiceSetMode",
    "compute_utilities",
    "geodesic_miles",
    "load_weights",
]
