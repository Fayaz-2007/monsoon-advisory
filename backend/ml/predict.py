"""Real-time forecasts from the latest trained model → ``forecasts`` table."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.confidence import confidence_level
from ml.config import CFG
from ml.data import DAILY_COLS, load_monthly_indices, load_region_meta
from ml.features import FOLD_FEATURES, assemble, build_issue_frame
from ml.models import QUANTILE_KEYS, predict, sort_quantiles
from ml.schema import FORECAST_COLS, upsert_forecasts
from ml.train import latest_trained, load_models
from ml.validate import season_col
from pipeline import load_features

HISTORY_DAYS = 120  # covers the 90-day sums; season-to-date loads from May 31 anyway


def default_issue_date() -> pd.Timestamp:
    """Day after the last day with rainfall for every active region."""
    from pipeline.db import read_df
    d = read_df("SELECT min(last) AS d FROM (SELECT region_id, max(date) AS last FROM rainfall_daily "
                "rd JOIN regions r ON r.id = rd.region_id WHERE r.active GROUP BY region_id) x")["d"].iloc[0]
    return pd.Timestamp(d) + pd.Timedelta(days=1)


def make_forecasts(issue_date: pd.Timestamp | str, model_version: str | None = None) -> pd.DataFrame:
    t = pd.Timestamp(issue_date).normalize()
    if not (CFG.issue_start_month <= t.month <= CFG.issue_end_month):
        raise ValueError(f"Issue date {t.date()} is outside the modelled season "
                         f"(Jun 1 – Dec 31); models were trained only for those issue dates.")
    mv = model_version or latest_trained()
    meta, boosters, cals, clim = load_models(mv)

    start = min(t - pd.Timedelta(days=HISTORY_DAYS), pd.Timestamp(t.year, 6, 1) - pd.Timedelta(days=1))
    daily = load_features(start=start.date(), end=(t - pd.Timedelta(days=1)).date())[DAILY_COLS]
    regions = load_region_meta()
    prev = daily[daily["date"] == t - pd.Timedelta(days=1)]
    missing = set(regions["region_id"]) - set(prev.loc[prev["rain_mm"].notna(), "region_id"])
    if missing:
        last = daily["date"].max()
        raise RuntimeError(
            f"features_daily has no rainfall for {t.date() - pd.Timedelta(days=1)} in {len(missing)} "
            f"region(s) (latest date loaded: {None if pd.isna(last) else last.date()}). "
            "Run the Segment 1 daily update first: python -m pipeline.run --stage daily")

    issue = build_issue_frame(daily, load_monthly_indices(), regions, pd.DatetimeIndex([t]))
    feats = meta["features"]
    extra = set(feats) - set(issue.columns) - set(FOLD_FEATURES)
    if extra:
        raise RuntimeError(f"Model {mv} expects features that are not available now: {sorted(extra)}")

    season = season_col(pd.Series([t]))[0]
    parts = []
    for lead in CFG.leads:
        frame = assemble(issue, clim, lead)
        c = cals[lead]
        pt = c["tercile"].transform(predict("tercile", boosters[("tercile", lead)], frame, feats))
        q = {k: predict(k, boosters[(k, lead)], frame, feats) for k in QUANTILE_KEYS}
        q10, q50, q90 = sort_quantiles(q["q10"], q["q50"], q["q90"])
        out = pd.DataFrame({
            "region_id": frame["region_id"].to_numpy(),
            "issue_date": t.date(),
            "lead_week": lead,
            "week_start": frame["week_start"].dt.date.to_numpy(),
            "week_end": frame["week_end"].dt.date.to_numpy(),
            "p_below": pt[:, 0], "p_normal": pt[:, 1], "p_above": pt[:, 2],
            "q10_mm": q10, "q50_mm": q50, "q90_mm": q90,
            "p_heavy": c["heavy_day"].transform(predict("heavy_day", boosters[("heavy_day", lead)], frame, feats)),
            "p_dry_week": c["dry_week"].transform(predict("dry_week", boosters[("dry_week", lead)], frame, feats)),
        })
        skill_low = meta["rpss_ci_low"].get(f"{lead}|{season}", np.nan)
        out["confidence"] = confidence_level(skill_low, pt.max(axis=1))
        parts.append(out)
    fc = pd.concat(parts, ignore_index=True)

    # Round for storage; p_normal absorbs the rounding so the three still sum to 1.
    for col in ("p_below", "p_above", "p_heavy", "p_dry_week"):
        fc[col] = fc[col].round(4)
    fc["p_normal"] = (1.0 - fc["p_below"] - fc["p_above"]).round(4)
    for col in ("q10_mm", "q50_mm", "q90_mm"):
        fc[col] = fc[col].round(2)
    fc["model_version"] = mv
    return fc[FORECAST_COLS]


def run_predict(issue_date: pd.Timestamp | str | None, model_version: str | None = None
                ) -> tuple[pd.DataFrame, int]:
    t = pd.Timestamp(issue_date) if issue_date is not None else default_issue_date()
    fc = make_forecasts(t, model_version)
    return fc, upsert_forecasts(fc)
