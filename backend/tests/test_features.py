from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.transform.climatology import compute_climatology, window_mask
from pipeline.transform.features import (
    FEATURE_COLS,
    compute_region_features,
    consecutive_dry_days,
    rolling_sum,
    season_flag,
    wet_day_count,
)
from pipeline.utils import doy366


def _series(values: list[float], start: str = "2020-06-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"),
                     dtype=float)


def test_rolling_sum_requires_full_window():
    s = _series([1, 2, 3, 4, 5])
    out = rolling_sum(s, 3)
    assert out.isna().tolist() == [True, True, False, False, False]
    assert out.iloc[2:].tolist() == [6, 9, 12]


def test_rolling_sum_null_when_window_has_missing_day():
    s = _series([1, np.nan, 3, 4, 5, 6])
    out = rolling_sum(s, 3)
    assert out.isna().tolist() == [True, True, True, True, False, False]
    assert out.iloc[5] == 15


def test_consecutive_dry_days_basic():
    s = _series([0, 1.0, 2.4, 2.5, 0, 0, 10, 0])
    out = consecutive_dry_days(s, 2.5)
    assert out.tolist() == [1, 2, 3, 0, 1, 2, 0, 1]


def test_consecutive_dry_days_seed_and_missing():
    s = _series([0, 0, np.nan, 0, 5])
    out = consecutive_dry_days(s, 2.5, initial=40)
    assert out.iloc[0] == 41 and out.iloc[1] == 42
    assert np.isnan(out.iloc[2])      # missing day → NULL
    assert out.iloc[3] == 1           # count restarts after a gap
    assert out.iloc[4] == 0


def test_wet_day_count():
    s = _series([0, 3, 5, 0, 2.5, 1, 9, 0])
    out = wet_day_count(s, 7, 2.5)
    assert out.iloc[:6].isna().all()
    assert out.iloc[6] == 4  # 3, 5, 2.5, 9
    assert out.iloc[7] == 4  # window drops the leading 0, adds a dry 0


def test_season_flag_normal_and_wrapping():
    d = pd.DatetimeIndex(["2020-05-31", "2020-06-01", "2020-12-31", "2021-01-15"])
    assert season_flag(d, 6, 12).tolist() == [False, True, True, False]
    assert season_flag(d, 10, 1).tolist() == [False, False, True, True]


def test_doy366_aligns_leap_and_non_leap_years():
    d = pd.DatetimeIndex(["2020-02-29", "2020-03-01", "2021-03-01", "2021-12-31", "2020-12-31"])
    assert doy366(d).tolist() == [60, 61, 61, 366, 366]


def test_window_mask_is_circular():
    m = window_mask(np.array([1, 366, 200]), half_window=2)
    assert m[0, 0] and m[0, 1] and not m[0, 2]       # doy 1 pools doy 366
    assert m[365, 0] and m[365, 1]


def test_compute_climatology_constant_series():
    idx = pd.date_range("1991-01-01", "1993-12-31", freq="D")
    wide = pd.DataFrame({7: np.full(len(idx), 2.0)}, index=idx)
    clim = compute_climatology(wide, half_window=15)
    assert len(clim) == 366
    assert clim["rain_mean"].to_numpy() == pytest.approx(2.0)
    assert clim["rain_p90"].to_numpy() == pytest.approx(2.0)
    assert clim["clim_sum_7d"].to_numpy() == pytest.approx(14.0)
    assert clim["clim_sum_30d"].to_numpy() == pytest.approx(60.0)
    assert (clim["n_years"] == 3).all()


def test_compute_region_features_end_to_end():
    dates = pd.date_range("2020-05-01", "2020-07-31", freq="D")
    rain = pd.Series(np.where(dates.day % 5 == 0, 10.0, 0.0), index=dates)
    clim = pd.DataFrame({"clim_sum_7d": 10.0, "clim_sum_30d": 40.0}, index=range(1, 367))
    ind_dates = pd.date_range("2020-03-01", "2020-07-31", freq="D")
    indices = pd.DataFrame({"oni": np.where(ind_dates.month == 6, 0.5, -0.5),
                            "dmi": 0.1, "rmm1": 1.0, "rmm2": 0.0, "mjo_phase": 5,
                            "mjo_amplitude": 1.0, "mjo_source": "romi"}, index=ind_dates)
    f = compute_region_features(rain, clim, indices, None, dry_threshold=2.5, season=(6, 12))
    assert list(f.columns) == FEATURE_COLS
    row = f.loc["2020-07-10"]
    # Rain falls on days 5,10,15,…; last 7 days (Jul 4-10) contain Jul 5 and Jul 10.
    assert row["rain_sum_7d"] == 20 and row["anomaly_7d_mm"] == 10
    assert row["anomaly_7d_pct"] == pytest.approx(200.0)
    assert row["wet_days_last_7"] == 2 and row["max_1day_rain_last_7"] == 10
    assert row["consecutive_dry_days"] == 0
    assert f.loc["2020-07-09", "consecutive_dry_days"] == 4
    assert row["oni"] == -0.5 and row["oni_lag30"] == 0.5  # Jun 10 value
    assert bool(row["is_monsoon_season"]) and not bool(f.loc["2020-05-31", "is_monsoon_season"])
    assert np.isnan(row["tcwv"])  # no ERA5 → NULL
    assert np.isnan(f.loc["2020-05-29", "rain_sum_30d"])  # window not yet complete
    assert f["doy_sin"].between(-1, 1).all()


def test_normalize_name_ignores_case_spaces_and_diacritics():
    from pipeline.utils import normalize_name
    assert normalize_name("Tamil Nādu") == normalize_name("TAMIL NADU") == normalize_name("TamilNadu")
