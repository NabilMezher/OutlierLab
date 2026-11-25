from __future__ import annotations

import random

import numpy as np


def set_global_seed(seed: int) -> np.random.Generator:
    """Seed Python's random module and NumPy, and return a seeded Generator."""
    random.seed(seed)
    np.random.seed(seed & 0xFFFFFFFF)
    return np.random.default_rng(seed)