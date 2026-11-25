import pandas as pd
import pytest

from outlierlab.io.loader import DataError, load_csv, sampling_interval


def write(tmp_path, text):
    p = tmp_path / "data.csv"
    p.write_text(text)
    return p


def test_loads_time_index_and_numeric_columns(tmp_path):
    p = write(
        tmp_path,
        "timestamp,temp,label\n2026-03-02 00:10,40.3,ok\n2026-03-02 00:00,40.1,ok\n",
    )
    df = load_csv(p)
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.is_monotonic_increasing  # sorted
    assert list(df.columns) == ["temp"]  # text column dropped


def test_no_numeric_column_raises(tmp_path):
    p = write(tmp_path, "timestamp,label\n2026-03-02 00:00,a\n2026-03-02 00:10,b\n")
    with pytest.raises(DataError):
        load_csv(p)


def test_bad_dates_raise(tmp_path):
    p = write(
        tmp_path,
        "timestamp,temp\n2026-03-02 00:00,1\nnot a date,2\n2026-03-02 00:20,3\n",
    )
    with pytest.raises(DataError, match="not dates"):
        load_csv(p, time_col="timestamp")


def test_interval_regular_and_irregular():
    idx = pd.date_range("2026-03-02", periods=5, freq="10min")
    assert sampling_interval(idx) == (pd.Timedelta("10min"), True)
    assert sampling_interval(idx.delete(2))[1] is False
