import pandas as pd
import pytest

from outlierlab.core.preprocess import handle_missing, missing_summary

IDX = pd.date_range("2026-03-02", periods=4, freq="10min")
S = pd.Series([1.0, None, None, 4.0], index=IDX)


def test_interpolate_fills_linearly():
    out = handle_missing(S, "interpolate")
    assert out.isna().sum() == 0
    assert out.iloc[1] == pytest.approx(2.0)


def test_drop_removes_rows():
    assert len(handle_missing(S, "drop")) == 2


def test_gaps_keeps_nan():
    assert handle_missing(S, "gaps").isna().sum() == 2


def test_unknown_policy():
    with pytest.raises(ValueError):
        handle_missing(S, "zero")


def test_summary():
    assert missing_summary(S) == {"missing": 2, "percent": 50.0}
