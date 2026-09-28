"""No look-ahead: features for issue date t must not change when anything unknown on t changes.

1. Every features_daily row dated ≥ t is scrambled.
2. Every ONI/DMI month not yet published on t (per the publication rule) is scrambled —
   this catches leaks like Segment 1's ``oni_lag30``, whose value sits at a date < t but is
   not yet public on t.
"""

import numpy as np
import pandas as pd
import pytest

from ml.config import CFG
from ml.features import BASE_FEATURES, STATE_COLS, build_issue_frame, publication_date

ISSUE_DATES = pd.to_datetime(["2021-06-01", "2021-07-09", "2021-07-10", "2021-10-01",
                              "2021-12-31"])


def _daily(seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-10-01", "2022-02-28", freq="D")
    frames = []
    for rid in (1, 2):
        n = len(dates)
        d = pd.DataFrame({"region_id": rid, "date": dates, "rain_mm": rng.gamma(0.7, 8, n)})
        for c in STATE_COLS:
            d[c] = rng.normal(size=n)
        d["mjo_phase"] = rng.integers(1, 9, n).astype(float)
        d["mjo_source"] = np.where(rng.random(n) > 0.5, "rmm", "romi")
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def _monthly(seed=0):
    rng = np.random.default_rng(seed)
    months = pd.period_range("2019-01", "2022-12", freq="M")
    return pd.DataFrame({"oni": rng.normal(size=len(months)), "dmi": rng.normal(size=len(months))},
                        index=months)


META = pd.DataFrame({"region_id": [1, 2], "lat": [11.0, 12.5], "lon": [78.0, 79.5]})


@pytest.mark.parametrize("t", ISSUE_DATES)
def test_future_daily_rows_do_not_change_features(t):
    daily, monthly = _daily(), _monthly()
    base = build_issue_frame(daily, monthly, META, pd.DatetimeIndex([t]))

    scrambled = daily.copy()
    fut = scrambled["date"] >= t
    rng = np.random.default_rng(99)
    for c in ["rain_mm", *STATE_COLS]:
        scrambled.loc[fut, c] = rng.normal(50, 30, fut.sum())
    scrambled.loc[fut, "mjo_source"] = "romi"
    again = build_issue_frame(scrambled, monthly, META, pd.DatetimeIndex([t]))
    pd.testing.assert_frame_equal(base[BASE_FEATURES], again[BASE_FEATURES])


@pytest.mark.parametrize("t", ISSUE_DATES)
def test_unpublished_index_months_do_not_change_features(t):
    daily, monthly = _daily(), _monthly()
    base = build_issue_frame(daily, monthly, META, pd.DatetimeIndex([t]))

    scrambled = monthly.copy()
    for col, lag in (("oni", CFG.oni_lag), ("dmi", CFG.dmi_lag)):
        unpublished = [m for m in scrambled.index if publication_date(m, lag) > t]
        assert unpublished, "test needs at least one unpublished month"
        scrambled.loc[unpublished, col] = 999.0
    again = build_issue_frame(daily, scrambled, META, pd.DatetimeIndex([t]))
    pd.testing.assert_frame_equal(base[BASE_FEATURES], again[BASE_FEATURES])


def test_published_months_are_used():
    """Sanity check the other direction: the latest PUBLISHED month does feed the feature."""
    t = pd.Timestamp("2021-07-10")          # day ≥ 10 → ONI of May (m−2); DMI of March (m−4)
    daily, monthly = _daily(), _monthly()
    f = build_issue_frame(daily, monthly, META, pd.DatetimeIndex([t]))
    assert f["oni_pub"].iloc[0] == monthly.loc[pd.Period("2021-05", "M"), "oni"]
    assert f["dmi_pub"].iloc[0] == monthly.loc[pd.Period("2021-03", "M"), "dmi"]
    t9 = pd.Timestamp("2021-07-09")         # day < 10 → ONI of April (m−3)
    f9 = build_issue_frame(daily, monthly, META, pd.DatetimeIndex([t9]))
    assert f9["oni_pub"].iloc[0] == monthly.loc[pd.Period("2021-04", "M"), "oni"]


def test_rain_state_is_from_previous_day():
    daily, monthly = _daily(), _monthly()
    t = pd.Timestamp("2021-08-15")
    f = build_issue_frame(daily, monthly, META, pd.DatetimeIndex([t]))
    prev = daily[(daily["region_id"] == 1) & (daily["date"] == t - pd.Timedelta(days=1))]
    assert f.loc[f["region_id"] == 1, "rain_sum_7d"].iloc[0] == prev["rain_sum_7d"].iloc[0]
    r = daily[daily["region_id"] == 1].set_index("date")["rain_mm"]
    assert np.isclose(f.loc[f["region_id"] == 1, "rain_sum_90d"].iloc[0],
                      r.loc[t - pd.Timedelta(days=90): t - pd.Timedelta(days=1)].sum())
    assert np.isclose(f.loc[f["region_id"] == 1, "season_to_date_mm"].iloc[0],
                      r.loc["2021-06-01": t - pd.Timedelta(days=1)].sum())
