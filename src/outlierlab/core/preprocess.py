from __future__ import annotations

import pandas as pd

POLICIES = ("interpolate", "drop", "gaps")


def handle_missing(series: pd.Series, policy: str = "interpolate") -> pd.Series:
    """Apply the user's missing-value choice to one column."""
    if policy == "interpolate":
        # "time" respects uneven gaps; needs a DatetimeIndex (load_csv gives one)
        return series.interpolate(method="time", limit_direction="both")
    if policy == "drop":
        return series.dropna()
    if policy == "gaps":
        return series
    raise ValueError(f"Unknown policy {policy!r}, expected one of {POLICIES}")


def missing_summary(series: pd.Series) -> dict:
    n = int(series.isna().sum())
    return {"missing": n, "percent": round(100 * n / max(len(series), 1), 1)}
