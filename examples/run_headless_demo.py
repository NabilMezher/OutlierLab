"""Headless example: run OutlierLab changepoint and anomaly detectors without the GUI."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from outlierlab.core.registry import make_default_spec
from outlierlab.core.runner import TaskRunner
from outlierlab.core.seeding import set_global_seed


def make_demo_csv(path: Path, seed: int = 42) -> pd.DataFrame:
    rng = set_global_seed(seed)
    n = 600
    timestamps = pd.date_range("2026-03-02", periods=n, freq="10min")
    t = np.arange(n)
    temp = 62.0 + 1.2 * np.sin(2 * np.pi * (t - 30) / 144) + rng.normal(0, 0.35, n)
    temp[150:] += 3.0       # level shift
    temp[222] += 6.0        # spike
    temp[300:313] = 55.2    # dropout
    temp[400:] += rng.normal(0, 0.9, n - 400)
    temp[515] -= 5.5        # drop

    df = pd.DataFrame({"timestamp": timestamps, "bearing_temp_c": np.round(temp, 2)})
    df.to_csv(path, index=False)
    return df


def main() -> None:
    out_csv = Path(__file__).parent / "pump_sensor_demo.csv"
    df = make_demo_csv(out_csv, seed=42)

    specs = [
        make_default_spec("pelt"),
        make_default_spec("binseg"),
        make_default_spec("window"),
        make_default_spec("iforest"),
        make_default_spec("lof"),
    ]

    runner = TaskRunner()
    runner.start(specs, df["bearing_temp_c"], seed=42)
    runner.join(timeout=30)

    for key, res in runner.results.items():
        print(f"{key:10s} | {res.status:6s} | {res.runtime_s:.2f}s | alarms={res.alarms}")


if __name__ == "__main__":
    main()