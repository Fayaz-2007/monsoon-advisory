"""Week-window construction and weekly targets."""

import numpy as np
import pandas as pd

from ml.targets import build_targets, forward_week_stats, week_window


def _rain(values, start="2020-06-01", region=1):
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.DataFrame({region: np.asarray(values, dtype=float)}, index=idx)


def test_week_window_leads():
    t = pd.Timestamp("2026-09-28")
    assert week_window(t, 1) == (pd.Timestamp("2026-09-29"), pd.Timestamp("2026-10-05"))
    assert week_window(t, 2) == (pd.Timestamp("2026-10-06"), pd.Timestamp("2026-10-12"))
    assert week_window(t, 4) == (pd.Timestamp("2026-10-20"), pd.Timestamp("2026-10-26"))


def test_weekly_total_heavy_and_dry_flags():
    # day i has i mm, except one heavy day on day 10
    vals = np.arange(40, dtype=float)
    vals[10] = 70.0
    rain = _rain(vals)
    issue = pd.DataFrame({"region_id": [1], "issue_date": [pd.Timestamp("2020-06-01")]})
    out = build_targets(rain, issue, leads=(1, 2))
    # lead 1 = Jun 2..Jun 8 = days 1..7
    assert out["total_l1"].iloc[0] == sum(range(1, 8))
    assert out["heavy_l1"].iloc[0] == 0 and out["dry_l1"].iloc[0] == 0
    # lead 2 = days 8..14, contains the 70 mm day
    assert out["total_l2"].iloc[0] == sum(range(8, 15)) - 10 + 70
    assert out["heavy_l2"].iloc[0] == 1


def test_dry_week_needs_all_days_below_threshold():
    rain = _rain([0, 1, 2, 2.4, 0, 0, 0, 0, 2.5, 0, 0, 0, 0, 0, 0, 0])
    stats = forward_week_stats(rain)
    assert stats["dry"].iloc[0, 0] == 1.0         # days 0..6 all < 2.5
    assert stats["dry"].iloc[2, 0] == 0.0         # days 2..8 include 2.5 mm


def test_incomplete_week_has_no_target():
    vals = np.ones(20)
    vals[5] = np.nan
    stats = forward_week_stats(_rain(vals))
    assert np.isnan(stats["total"].iloc[0, 0])     # window 0..6 contains the gap
    assert stats["total"].iloc[6, 0] == 7.0        # window 6..12 is complete
    assert np.isnan(stats["total"].iloc[-1, 0])    # runs past the end of data
