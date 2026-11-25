import random

import numpy as np

from outlierlab.core.seeding import set_global_seed


def test_set_global_seed_is_reproducible():
    g1 = set_global_seed(42)
    py1 = [random.random() for _ in range(3)]
    np1 = np.random.rand(3)
    gen1 = g1.random(3)

    g2 = set_global_seed(42)
    py2 = [random.random() for _ in range(3)]
    np2 = np.random.rand(3)
    gen2 = g2.random(3)

    assert py1 == py2
    assert np.allclose(np1, np2)
    assert np.allclose(gen1, gen2)


def test_different_seeds_produce_different_values():
    g1 = set_global_seed(1)
    v1 = g1.random(5)
    g2 = set_global_seed(2)
    v2 = g2.random(5)
    assert not np.allclose(v1, v2)