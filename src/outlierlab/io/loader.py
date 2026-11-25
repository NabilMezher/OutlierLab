from __future__ import annotations

from pathlib import Path

import pandas as pd


class DataError(ValueError):
    """A file that cannot be used as a time series. The GUI shows str(exc)."""


def guess_time_column(df: pd.DataFrame) -> str:
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):  # text columns only
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.notna().mean() > 0.9:
                return col
    raise DataError("No date or time column found. Choose one by hand.")


def load_csv(path: str | Path, time_col: str | None = None) -> pd.DataFrame:
    """Read a CSV into a DataFrame indexed by time, sorted, numeric columns only."""
    path = Path(path)
    try:
        df = pd.read_csv(path)
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise DataError(f"Could not read {path.name}: {exc}") from exc
    if df.empty:
        raise DataError(f"{path.name} has no rows.")

    time_col = time_col or guess_time_column(df)
    times = pd.to_datetime(df[time_col], errors="coerce")
    if times.isna().any():
        raise DataError(
            f"{int(times.isna().sum())} rows in '{time_col}' are not dates."
        )

    df = df.drop(columns=time_col).set_index(times).sort_index()
    df.index.name = time_col
    numeric = df.select_dtypes("number")
    if numeric.empty:
        raise DataError("No numeric column to analyse.")
    return numeric


def sampling_interval(index: pd.DatetimeIndex) -> tuple[pd.Timedelta, bool]:
    """Median step between rows, and whether every step is within 1% of it."""
    if len(index) < 2:
        raise DataError("Need at least two rows.")
    steps = pd.Series(index).diff().dropna()
    median = steps.median()
    regular = bool(((steps - median).abs() <= median * 0.01).all())
    return median, regular
