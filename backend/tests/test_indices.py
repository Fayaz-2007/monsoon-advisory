from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline.sources.climate_indices import (
    combine_mjo,
    mjo_phase,
    parse_dmi,
    parse_oni,
    parse_rmm,
    parse_romi,
    to_daily,
)


def test_parse_oni_maps_season_to_centre_month(fixture_text):
    df = parse_oni(fixture_text("oni_sample.txt"))
    assert list(df["date"]) == [pd.Timestamp(1990, 12, 1), pd.Timestamp(1991, 1, 1),
                                pd.Timestamp(1991, 2, 1), pd.Timestamp(1991, 3, 1)]
    assert df["oni"].tolist() == [-0.10, 0.40, 0.30, 0.20]


def test_parse_dmi_skips_missing_and_footer(fixture_text):
    df = parse_dmi(fixture_text("dmi_sample.txt"))
    assert len(df) == 14  # 12 months of 1990 + 2 valid months of 1991
    assert df["date"].iloc[0] == pd.Timestamp(1990, 1, 1)
    assert df["date"].iloc[-1] == pd.Timestamp(1991, 2, 1)
    assert df["dmi"].iloc[-1] == pytest.approx(0.25)
    assert (df["dmi"] > -999).all()


def test_parse_rmm_handles_missing_and_scientific_notation(fixture_text):
    df = parse_rmm(fixture_text("rmm_sample.txt"))
    assert len(df) == 4
    missing = df[df["date"] == pd.Timestamp(1991, 1, 3)].iloc[0]
    assert np.isnan(missing["rmm1"]) and np.isnan(missing["mjo_phase"])
    last = df.iloc[-1]
    assert last["rmm1"] == pytest.approx(-0.00314564817)
    assert last["mjo_phase"] == 7


def test_mjo_phase_matches_bom_convention(fixture_text):
    df = parse_rmm(fixture_text("rmm_sample.txt")).dropna()
    np.testing.assert_array_equal(mjo_phase(df["rmm1"], df["rmm2"]), df["mjo_phase"])
    # Octant boundaries: phase 1 starts at -180°, phase 5 at 0°.
    assert mjo_phase(np.array([-1.0]), np.array([-0.01]))[0] == 1
    assert mjo_phase(np.array([1.0]), np.array([0.01]))[0] == 5


def test_parse_romi_maps_to_rmm_space(fixture_text):
    df = parse_romi(fixture_text("romi_sample.txt"))
    # (rmm1, rmm2) = (PC2, -PC1)
    assert df.loc[0, ["rmm1", "rmm2"]].tolist() == pytest.approx([0.0, -0.5])
    assert df["mjo_phase"].tolist() == [3, 5, 7]


def test_parse_romi_rotation():
    df = parse_romi("1991 1 1 0 0.0 1.0 1.0\n", rotation_deg=90)
    # (1, 0) rotated +90° -> (0, 1)
    assert df.loc[0, "rmm1"] == pytest.approx(0.0, abs=1e-12)
    assert df.loc[0, "rmm2"] == pytest.approx(1.0)


def test_combine_mjo_prefers_rmm_then_fills_with_romi(fixture_text):
    rmm = parse_rmm(fixture_text("rmm_sample.txt"))
    romi = parse_romi(fixture_text("romi_sample.txt"))
    out = combine_mjo(rmm, romi, "rmm_then_romi")
    by_date = out.set_index("date")["mjo_source"]
    assert by_date[pd.Timestamp(1991, 1, 4)] == "rmm"   # both present -> RMM wins
    assert by_date[pd.Timestamp(1991, 1, 5)] == "romi"  # only ROMI
    assert pd.Timestamp(1991, 1, 3) not in by_date.index  # RMM missing row dropped
    assert set(combine_mjo(rmm, romi, "romi_only")["mjo_source"]) == {"romi"}


def test_to_daily_forward_fills_monthly_and_limits(fixture_text):
    oni = parse_oni(fixture_text("oni_sample.txt"))
    dmi = parse_dmi(fixture_text("dmi_sample.txt"))
    mjo = combine_mjo(parse_rmm(fixture_text("rmm_sample.txt")),
                      parse_romi(fixture_text("romi_sample.txt")), "rmm_then_romi")
    daily = to_daily(oni, dmi, mjo, date(1991, 1, 1), date(1991, 12, 31),
                     monthly_ffill_days=10, daily_ffill_days=2)
    d = daily.set_index("date")
    # Every day of January carries January's ONI.
    assert (d.loc["1991-01-01":"1991-01-31", "oni"] == 0.40).all()
    # March is the last ONI month; ffill stops 10 days after 31 March.
    assert d.loc["1991-04-10", "oni"] == pytest.approx(0.20)
    assert pd.Timestamp("1991-04-11") not in d.index  # nothing left after ffill limit
    # MJO gap on 1991-01-03 is forward-filled from 01-02.
    assert d.loc["1991-01-03", "mjo_phase"] == 6
    # Trailing days with no index at all are trimmed.
    assert d.index.max() == pd.Timestamp(1991, 4, 10)
    assert str(daily["mjo_phase"].dtype) == "Int64"
