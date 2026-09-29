"""Mock forecast generator invariants (pure; no database)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.mock.generator import FORECAST_COLS, confidence_level, generate, prob_total_at_least
from app.mock.scenarios import SCENARIOS, apply_scenario

NAMES = ["Chennai", "Cuddalore", "Nagapattinam", "Madurai", "Dindigul", "Theni", "Salem",
         "Coimbatore", "Tiruvannamalai", "Viluppuram", "Thanjavur", "Tirunelveli"]
LONLAT = [(80.24, 13.06), (79.45, 11.54), (79.76, 10.58), (78.01, 9.92), (77.82, 10.39),
          (77.44, 9.89), (78.22, 11.68), (76.98, 10.88), (79.17, 12.43), (79.52, 12.12),
          (79.24, 10.67), (77.60, 8.57)]
COASTAL = {"Chennai", "Cuddalore", "Nagapattinam", "Viluppuram", "Thanjavur", "Tirunelveli"}


@pytest.fixture
def regions() -> pd.DataFrame:
    return pd.DataFrame({
        "id": range(1, len(NAMES) + 1),
        "code": [f"tn/{n.lower()}" for n in NAMES],
        "name": NAMES,
        "lon": [p[0] for p in LONLAT],
        "lat": [p[1] for p in LONLAT],
        "coastal": [n in COASTAL for n in NAMES],
    })


def normals(n: int, mm: float = 30.0) -> np.ndarray:
    return np.full((n, 4), mm)


def test_schema_and_shape(regions):
    df = generate(regions, normals(len(regions)), date(2026, 9, 29))
    assert list(df.columns) == FORECAST_COLS
    assert len(df) == len(regions) * 4
    assert set(df["lead_week"]) == {1, 2, 3, 4}
    row = df[(df["region_id"] == 1) & (df["lead_week"] == 2)].iloc[0]
    assert row["week_start"] == date(2026, 10, 7) and row["week_end"] == date(2026, 10, 13)


@pytest.mark.parametrize("d", [date(2026, 6, 5), date(2026, 8, 14), date(2026, 9, 29),
                               date(2026, 11, 10), date(2026, 12, 30)])
def test_probabilities_valid_and_quantiles_ordered(regions, d):
    df = generate(regions, normals(len(regions)), d)
    p = df[["p_below", "p_normal", "p_above"]]
    assert np.allclose(p.sum(axis=1), 1.0, atol=1e-9)
    for col in ("p_below", "p_normal", "p_above", "p_heavy", "p_dry_week"):
        assert df[col].between(0.001, 0.999).all(), col
    assert (df["q10_mm"] <= df["q50_mm"]).all() and (df["q50_mm"] <= df["q90_mm"]).all()
    assert (df["q10_mm"] >= 0).all()


def test_deterministic_and_date_sensitive(regions):
    a = generate(regions, normals(len(regions)), date(2026, 9, 29), seed=42)
    b = generate(regions, normals(len(regions)), date(2026, 9, 29), seed=42)
    pd.testing.assert_frame_equal(a, b)
    c = generate(regions, normals(len(regions)), date(2026, 9, 30), seed=42)
    assert not np.allclose(a["p_above"], c["p_above"])
    d = generate(regions, normals(len(regions)), date(2026, 9, 29), seed=7)
    assert not np.allclose(a["p_above"], d["p_above"])


def test_neighbours_more_similar_than_distant(regions):
    # Averaged over many dates: |Δp_above| between Cuddalore–Viluppuram (~0.6°) is smaller
    # than between Chennai–Tirunelveli (~5°).
    near, far = [], []
    for k in range(40):
        df = generate(regions, normals(len(regions)), date(2026, 7, 1) + pd.Timedelta(days=k).to_pytimedelta())
        w1 = df[df["lead_week"] == 1].set_index("region_id")["p_above"]
        near.append(abs(w1[2] - w1[10]))
        far.append(abs(w1[1] - w1[12]))
    assert np.mean(near) < np.mean(far)


def test_ne_monsoon_wetter_on_coast(regions):
    coast, inland = [], []
    for k in range(30):
        df = generate(regions, normals(len(regions)), date(2026, 10, 15) + pd.Timedelta(days=k).to_pytimedelta())
        m = df.merge(regions, left_on="region_id", right_on="id")
        coast.append(m[m["coastal"]]["p_above"].mean())
        inland.append(m[~m["coastal"]]["p_above"].mean())
    assert np.mean(coast) > np.mean(inland) + 0.05


def test_confidence_mix_and_rule(regions):
    levels = set()
    for k in range(10):
        df = generate(regions, normals(len(regions)), date(2026, 10, 1) + pd.Timedelta(days=k).to_pytimedelta())
        levels |= set(df["confidence"])
    assert levels == {"High", "Medium", "Low"}
    assert confidence_level(0.12, 0.55) == "High"
    assert confidence_level(0.12, 0.40) == "Medium"
    assert confidence_level(0.05, 0.46) == "Medium"
    assert confidence_level(0.05, 0.40) == "Low"
    assert confidence_level(0.02, 0.90) == "Low"


def test_prob_total_at_least_monotonic():
    ps = [prob_total_at_least(t, 2.0, 20.0, 60.0) for t in (1, 5, 20, 40, 100)]
    assert all(a >= b for a, b in zip(ps, ps[1:]))
    assert abs(prob_total_at_least(20.0, 2.0, 20.0, 60.0) - 0.5) < 1e-9


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenarios_keep_invariants(regions, name):
    base = generate(regions, normals(len(regions)), date(2026, 9, 29))
    df = apply_scenario(base, regions, name)
    assert np.allclose(df[["p_below", "p_normal", "p_above"]].sum(axis=1), 1.0)
    assert (df["q10_mm"] <= df["q50_mm"]).all() and (df["q50_mm"] <= df["q90_mm"]).all()
    assert df[["p_heavy", "p_dry_week"]].stack().between(0.001, 0.999).all()


def test_scenario_targets(regions):
    base = generate(regions, normals(len(regions)), date(2026, 10, 20))
    surge = apply_scenario(base, regions, "ne_monsoon_surge")
    heavy = surge[(surge["lead_week"] == 1) & (surge["p_heavy"] >= 0.5)]["region_id"]
    assert set(heavy) == {1, 2, 3}  # Chennai, Cuddalore, Nagapattinam
    trap = apply_scenario(base, regions, "false_onset_trap")
    mdu = trap[trap["region_id"] == 4].set_index("lead_week")
    assert mdu.loc[1, "q50_mm"] >= 40 and mdu.loc[2, "p_dry_week"] >= 0.7
    calm = apply_scenario(base, regions, "normal_season")
    assert calm["p_heavy"].max() <= 0.12 and calm["p_dry_week"].max() <= 0.18
