"""Hazard rules (pure; no database)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.hazards import rules as R

ISSUE = date(2026, 10, 10)  # inside the NE-monsoon onset season


def obs_series(values: list[float], end: date = ISSUE - timedelta(days=1)):
    start = end - timedelta(days=len(values) - 1)
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def week(k: int, **kw):
    base = dict(lead_week=k, week_start=ISSUE + timedelta(days=7 * (k - 1) + 1),
                week_end=ISSUE + timedelta(days=7 * k), p_below=0.33, p_normal=0.34,
                p_above=0.33, q10_mm=3.0, q50_mm=15.0, q90_mm=45.0, p_heavy=0.05,
                p_dry_week=0.15, confidence="Medium")
    base.update(kw)
    return base


def calm_fc():
    return [week(k) for k in range(1, 5)]


# ---------------- helpers ----------------

def test_find_onset_two_and_three_day_windows():
    assert R.find_onset(obs_series([0, 0, 12, 9, 0])) is not None           # 21 mm in 2 days
    three = R.find_onset(obs_series([0, 7, 7, 7, 0, 0]))                     # 21 mm in 3 days
    assert three and three["days"] == 3 and three["total_mm"] == 21.0
    assert R.find_onset(obs_series([5, 5, 5, 0, 5, 5])) is None              # never ≥ 20 in 2–3 d
    # a window never ends on a dry day, so a dry day after the rain does not shift the onset
    tail = R.find_onset(obs_series([0, 14, 12, 0, 0]))
    assert tail["days"] == 2 and tail["total_mm"] == 26.0


def test_trailing_dry_run_and_nan_breaks():
    assert R.trailing_dry_run(obs_series([10, 0, 1, 2.4])) == 3
    assert R.trailing_dry_run(obs_series([0, 0, float("nan"), 0])) == 1
    assert R.trailing_dry_run(obs_series([3.0])) == 0


def test_onset_season():
    assert R.is_onset_season(date(2026, 6, 10)) and R.is_onset_season(date(2026, 10, 1))
    assert not R.is_onset_season(date(2026, 8, 14)) and not R.is_onset_season(date(2026, 12, 20))


# ---------------- onset ----------------

def test_onset_observed_recent():
    obs = obs_series([0] * 20 + [15, 12] + [5] * 3)
    h = R.rule_onset(obs, calm_fc(), ISSUE, True)
    assert h and h.hazard_type == "onset" and h.lead_week == 0 and h.basis == "observed"
    assert "32.0 mm fell in 3 days" in h.why  # wettest window of the latest rain event


def test_onset_forecast_when_no_recent_onset():
    fc = [week(1, q10_mm=10, q50_mm=40, q90_mm=90)] + calm_fc()[1:]
    h = R.rule_onset(obs_series([0] * 30), fc, ISSUE, True)
    assert h and h.lead_week == 1 and h.probability >= 0.5 and "≥ 20 mm" in h.why


def test_onset_off_season_is_silent():
    fc = [week(1, q10_mm=10, q50_mm=40, q90_mm=90)] + calm_fc()[1:]
    assert R.rule_onset(obs_series([0] * 30), fc, ISSUE, False) is None


# ---------------- false onset ----------------

def test_false_onset_observed_ongoing():
    obs = obs_series([0] * 10 + [14, 12] + [0] * 9)       # onset then 9 dry days, still dry
    h = R.rule_false_onset(obs, calm_fc(), ISSUE, True)
    assert h and h.basis == "observed" and h.severity == "warning" and h.probability == 1.0
    assert "9 days" in h.why


def test_false_onset_observed_eases_to_watch_when_rain_returns():
    obs = obs_series([0] * 10 + [14, 12] + [0] * 9)
    fc = [week(1, q10_mm=10, q50_mm=40, q90_mm=90, p_dry_week=0.02)] +         [week(k, p_dry_week=0.1) for k in (2, 3, 4)]
    h = R.rule_false_onset(obs, fc, ISSUE, True)
    assert h.severity == "watch" and "Relief likely" in h.why
    fc[1]["p_dry_week"] = 0.8  # rain in week 1 but a dry week 2: still a trap
    assert R.rule_false_onset(obs, fc, ISSUE, True).severity == "warning"


def test_false_onset_forecast_after_forecast_onset():
    fc = [week(1, q10_mm=18, q50_mm=52, q90_mm=115, confidence="High"),
          week(2, p_dry_week=0.80, q50_mm=1.2, confidence="High"),
          week(3, p_dry_week=0.55), week(4, p_dry_week=0.25)]
    h = R.rule_false_onset(obs_series([0] * 30), fc, ISSUE, True)
    assert h and h.hazard_type == "false_onset" and h.lead_week == 2
    assert h.probability >= 0.8 and h.severity == "warning"
    assert "80%" in h.why


def test_false_onset_needs_a_clearly_dry_week():
    fc = [week(1, q10_mm=18, q50_mm=52, q90_mm=115)] + [week(k, p_dry_week=0.3) for k in (2, 3, 4)]
    assert R.rule_false_onset(obs_series([0] * 30), fc, ISSUE, True) is None


def test_low_confidence_softens_warning():
    fc = [week(1, q10_mm=18, q50_mm=52, q90_mm=115, confidence="Low"),
          week(2, p_dry_week=0.85, confidence="Low"), week(3), week(4)]
    h = R.rule_false_onset(obs_series([0] * 30), fc, ISSUE, True)
    assert h and h.severity == "watch"


# ---------------- dry spell ----------------

def test_dry_spell_7_day_forecast():
    fc = [week(1), week(2, p_dry_week=0.65, confidence="High"), week(3), week(4)]
    h = R.rule_dry_spell(obs_series([5] * 30), fc, ISSUE)
    assert h and h.subtype == "7d" and h.lead_week == 2 and h.severity == "warning"
    assert "65%" in h.why


def test_dry_spell_14_day_from_two_dry_weeks():
    fc = [week(1, p_dry_week=0.70), week(2, p_dry_week=0.62), week(3), week(4)]
    h = R.rule_dry_spell(obs_series([5] * 30), fc, ISSUE)
    assert h and h.subtype == "14d"
    assert h.probability == pytest.approx(0.70 * (0.62 + 0.3 * 0.38))


def test_dry_spell_observed_14_days():
    h = R.rule_dry_spell(obs_series([5] * 10 + [0] * 15), calm_fc(), ISSUE)
    assert h and h.basis == "observed" and h.subtype == "14d" and h.severity == "warning"


def test_dry_spell_observed_7_days_continuing():
    fc = [week(1, p_dry_week=0.6)] + calm_fc()[1:]
    h = R.rule_dry_spell(obs_series([5] * 10 + [0] * 8), fc, ISSUE)
    assert h and h.basis == "observed+forecast" and h.subtype == "14d"


def test_dry_spell_observed_7_days_ending_is_info():
    fc = [week(1, q10_mm=10, q50_mm=40, q90_mm=90)] + calm_fc()[1:]
    h = R.rule_dry_spell(obs_series([5] * 10 + [0] * 8), fc, ISSUE)
    assert h and h.severity == "info" and "Likely to end" in h.why


def test_no_dry_spell_when_calm():
    assert R.rule_dry_spell(obs_series([5] * 30), calm_fc(), ISSUE) is None


# ---------------- heavy rain ----------------

def test_heavy_rain_forecast_nearest_week():
    fc = [week(1, p_heavy=0.40), week(2), week(3), week(4, p_heavy=0.95, confidence="Low")]
    h = R.rule_heavy_rain(obs_series([5] * 30), fc, ISSUE)
    assert h and h.lead_week == 1 and h.severity == "watch"
    assert h.evidence["weeks_over_threshold"] == [1, 4]


def test_heavy_rain_warning_and_very_heavy():
    fc = [week(1, p_heavy=0.85, q90_mm=320, confidence="High")] + calm_fc()[1:]
    h = R.rule_heavy_rain(obs_series([5] * 30), fc, ISSUE)
    assert h.severity == "warning" and h.subtype == "very_heavy" and "64.5 mm" in h.why


def test_heavy_rain_observed():
    h = R.rule_heavy_rain(obs_series([5] * 28 + [80.0, 3.0]), calm_fc(), ISSUE)
    assert h and h.basis == "observed" and "80.0 mm" in h.why


# ---------------- active phase ----------------

def test_active_phase_forecast():
    fc = [week(1, p_above=0.6, p_dry_week=0.05), week(2, p_above=0.5, p_dry_week=0.05),
          week(3), week(4)]
    h = R.rule_active_phase(obs_series([5] * 30), fc, ISSUE, None, None)
    assert h and h.probability == 0.5 and h.basis == "forecast"


def test_active_phase_observed():
    h = R.rule_active_phase(obs_series([5] * 30), calm_fc(), ISSUE, 180.0, 5)
    assert h and h.basis == "observed" and "180%" in h.why
    assert R.rule_active_phase(obs_series([5] * 30), calm_fc(), ISSUE, 180.0, 2) is None


# ---------------- revival ----------------

def test_revival_after_forecast_dry_week():
    fc = [week(1, p_dry_week=0.7), week(2, p_dry_week=0.6),
          week(3, q10_mm=8, q50_mm=35, q90_mm=85, p_above=0.55), week(4)]
    h = R.rule_revival(obs_series([5] * 30), fc, ISSUE)
    assert h and h.lead_week == 3 and h.probability >= 0.5


def test_revival_after_observed_dry_run():
    fc = [week(1, q10_mm=8, q50_mm=35, q90_mm=85, p_above=0.5)] + calm_fc()[1:]
    h = R.rule_revival(obs_series([5] * 10 + [0] * 9), fc, ISSUE)
    assert h and h.lead_week == 1 and "9 observed dry days" in h.why


# ---------------- detect_all ----------------

def test_detect_all_ignores_stale_observations():
    stale = obs_series([0] * 20, end=ISSUE - timedelta(days=20))
    hz = R.detect_all(stale, calm_fc(), ISSUE)
    assert all(h.basis == "forecast" for h in hz)


def test_detect_all_false_onset_replaces_onset():
    fc = [week(1, q10_mm=18, q50_mm=52, q90_mm=115), week(2, p_dry_week=0.8), week(3), week(4)]
    types = [h.hazard_type for h in R.detect_all(obs_series([0] * 30), fc, ISSUE)]
    assert "false_onset" in types and "onset" not in types


def test_every_hazard_has_required_fields():
    fc = [week(1, q10_mm=18, q50_mm=52, q90_mm=115, p_heavy=0.5),
          week(2, p_dry_week=0.8), week(3, p_dry_week=0.6), week(4)]
    for h in R.detect_all(obs_series([0] * 30), fc, ISSUE):
        d = h.as_dict()
        assert d["hazard_type"] in R.HAZARD_TYPES
        assert 0 <= d["probability"] <= 1 and 0 <= d["lead_week"] <= 4
        assert d["confidence"] in ("High", "Medium", "Low") and d["why"]
