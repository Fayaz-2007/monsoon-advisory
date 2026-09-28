"""Issue-date feature matrix. Every feature for issue date t is known on t.

Rules (see docs/contracts/segment2_output.md, "Features and lags"):

* Rainfall state comes from the ``features_daily`` row of **t−1** (its trailing windows end
  on t−1), plus 60/90-day sums and season-to-date totals computed from ``rain_mm`` ≤ t−1.
* MJO (RMM/ROMI) is taken at t−1.
* ONI/DMI are looked up by *valid month* from ``climate_indices_daily`` and only months
  already published on t are used (``CFG.oni_lag``/``CFG.dmi_lag``). Segment 1's ``oni``,
  ``oni_lag30``, ``dmi``, ``dmi_lag30`` columns are NOT used (they carry look-ahead).
* Anomalies and target-week climatology come from a :class:`FoldClimatology` fitted on
  training years only. Segment 1's ``anomaly_*`` columns are NOT used (1991–2020 base).

``build_issue_frame`` produces the fold-independent part; ``assemble`` adds the fold part
for one lead week.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.config import CFG, IndexLag
from ml.external import external_features
from ml.targets import FoldClimatology, season_to_date, tercile_class, week_start_offset
from pipeline.transform.features import doy_cyclic
from pipeline.utils import doy366

# Columns read from features_daily at t−1.
STATE_COLS = [
    "rain_sum_3d", "rain_sum_7d", "rain_sum_14d", "rain_sum_30d",
    "consecutive_dry_days", "wet_days_last_7", "wet_days_last_14", "max_1day_rain_last_7",
    "rmm1", "rmm2", "mjo_amplitude", "mjo_phase",
]
BASE_FEATURES = [
    *STATE_COLS, "mjo_is_romi",
    "rain_sum_60d", "rain_sum_90d", "season_to_date_mm",
    "doy_sin", "doy_cos", "lat", "lon",
    "oni_pub", "oni_pub_prev", "dmi_pub", "dmi_pub_prev",
]
FOLD_FEATURES = [
    "anom_7d_mm", "anom_30d_mm", "anom_90d_mm", "season_to_date_anom_mm",
    "clim_week_mean", "clim_week_p33", "clim_week_p67", "clim_heavy_freq", "clim_dry_freq",
    "clim_annual_mm",
]
CATEGORICAL = ["mjo_phase"]

# Human-readable lag description of every feature (model card + contract).
FEATURE_LAGS: dict[str, str] = {
    **{c: "features_daily at t−1 (trailing window ends t−1)" for c in STATE_COLS[:8]},
    "rmm1": "t−1", "rmm2": "t−1", "mjo_amplitude": "t−1", "mjo_phase": "t−1 (categorical)",
    "mjo_is_romi": "t−1 (1 = ROMI source, 0 = BoM RMM)",
    "rain_sum_60d": "rain_mm t−60 … t−1", "rain_sum_90d": "rain_mm t−90 … t−1",
    "season_to_date_mm": "rain_mm Jun 1 (or Oct 1) … t−1",
    "doy_sin": "calendar of t", "doy_cos": "calendar of t",
    "lat": "static (district centroid)", "lon": "static (district centroid)",
    "oni_pub": "ONI of month m−2 if day(t) ≥ 10, else m−3 (published day 10 of M+2)",
    "oni_pub_prev": "ONI one month before oni_pub",
    "dmi_pub": "DMI of month m−4 (observed PSL lag ~4 months)",
    "dmi_pub_prev": "DMI of month m−5",
    "anom_7d_mm": "rain_sum_7d(t−1) − fold normal", "anom_30d_mm": "rain_sum_30d(t−1) − fold normal",
    "anom_90d_mm": "rain_sum_90d(t−1) − fold normal",
    "season_to_date_anom_mm": "season_to_date_mm − fold normal for that issue day",
    "clim_week_mean": "fold climatology of the target week",
    "clim_week_p33": "fold tercile threshold (target week)",
    "clim_week_p67": "fold tercile threshold (target week)",
    "clim_heavy_freq": "fold climatological P(heavy day) for the target week",
    "clim_dry_freq": "fold climatological P(dry week) for the target week",
    "clim_annual_mm": "fold mean annual rainfall of the district",
}


# ---------------------------------------------------------------------------
# Monthly indices with publication delay
# ---------------------------------------------------------------------------


def monthly_indices(index_daily: pd.DataFrame) -> pd.DataFrame:
    """climate_indices_daily (date, oni, dmi) → one row per valid month (PeriodIndex)."""
    df = index_daily.copy()
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    return df.groupby("month")[["oni", "dmi"]].first()


def latest_published_month(dates: pd.DatetimeIndex, lag: IndexLag) -> pd.PeriodIndex:
    """Most recent valid month whose value is published on or before each date."""
    dates = pd.DatetimeIndex(dates)
    back = lag.delay_months + (dates.day < lag.pub_day).astype(int)
    months = dates.to_period("M")
    return pd.PeriodIndex([m - int(b) for m, b in zip(months, back, strict=True)], freq="M")


def publication_date(month: pd.Period, lag: IndexLag) -> pd.Timestamp:
    """Date on which the value for valid month ``month`` becomes usable."""
    return (month + lag.delay_months).start_time + pd.Timedelta(days=lag.pub_day - 1)


def _lookup(monthly: pd.DataFrame, col: str, months: pd.PeriodIndex) -> np.ndarray:
    s = monthly[col] if col in monthly else pd.Series(dtype=float)
    return s.reindex(months).to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# Issue frame (fold-independent)
# ---------------------------------------------------------------------------


def wide(daily: pd.DataFrame, col: str, region_ids: list[int], dates: pd.DatetimeIndex
         ) -> pd.DataFrame:
    w = daily.pivot(index="date", columns="region_id", values=col)
    return w.reindex(index=dates, columns=region_ids).astype(float)


def build_issue_frame(daily: pd.DataFrame, monthly: pd.DataFrame, meta: pd.DataFrame,
                      issue_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per (region, issue date) with the fold-independent features.

    Args:
        daily: features_daily rows (region_id, date, rain_mm, STATE_COLS, mjo_source).
        monthly: output of :func:`monthly_indices`.
        meta: region_id, lat, lon for every region to include.
        issue_dates: the issue dates t.
    """
    region_ids = [int(r) for r in meta["region_id"]]
    issue_dates = pd.DatetimeIndex(issue_dates)
    lo = min(daily["date"].min(), issue_dates.min() - pd.Timedelta(days=1))
    hi = max(daily["date"].max(), issue_dates.max())
    dates = pd.date_range(lo, hi, freq="D")
    prev = issue_dates - pd.Timedelta(days=1)

    n_t, n_r = len(issue_dates), len(region_ids)
    out = pd.DataFrame({
        "region_id": np.repeat(np.asarray(region_ids, dtype=np.int64), n_t),
        "issue_date": np.tile(issue_dates.to_numpy(), n_r),
    })

    def take(frame: pd.DataFrame, at: pd.DatetimeIndex) -> np.ndarray:
        # region-major ravel to match np.repeat(region_ids) / np.tile(issue_dates)
        return frame.reindex(at).to_numpy(dtype=float).T.ravel()

    for col in STATE_COLS:
        out[col] = take(wide(daily, col, region_ids, dates), prev)
    romi = daily.assign(_r=(daily["mjo_source"] == "romi").astype(float)
                        .where(daily["mjo_source"].notna()))
    out["mjo_is_romi"] = take(wide(romi, "_r", region_ids, dates), prev)

    rain = wide(daily, "rain_mm", region_ids, dates)
    for w in (60, 90):
        out[f"rain_sum_{w}d"] = take(rain.rolling(w, min_periods=w).sum(), prev)
    out["season_to_date_mm"] = season_to_date(rain, issue_dates).T.ravel()

    s, c = doy_cyclic(issue_dates)
    out["doy_sin"], out["doy_cos"] = np.tile(s, n_r), np.tile(c, n_r)
    geo = meta.set_index("region_id").loc[region_ids]
    out["lat"] = np.repeat(geo["lat"].to_numpy(dtype=float), n_t)
    out["lon"] = np.repeat(geo["lon"].to_numpy(dtype=float), n_t)

    oni_m = latest_published_month(issue_dates, CFG.oni_lag)
    dmi_m = latest_published_month(issue_dates, CFG.dmi_lag)
    out["oni_pub"] = np.tile(_lookup(monthly, "oni", oni_m), n_r)
    out["oni_pub_prev"] = np.tile(_lookup(monthly, "oni", oni_m - 1), n_r)
    out["dmi_pub"] = np.tile(_lookup(monthly, "dmi", dmi_m), n_r)
    out["dmi_pub_prev"] = np.tile(_lookup(monthly, "dmi", dmi_m - 1), n_r)

    ext = external_features(issue_dates, region_ids)
    if ext is not None and not ext.empty:
        out = out.merge(ext, on=["region_id", "issue_date"], how="left")
    return out


def external_columns(frame: pd.DataFrame) -> list[str]:
    """Columns added by the external-forecast hook (prefixed ``ext_``)."""
    return [c for c in frame.columns if c.startswith("ext_")]


# ---------------------------------------------------------------------------
# Fold-dependent part (per lead week)
# ---------------------------------------------------------------------------


def assemble(issue: pd.DataFrame, clim: FoldClimatology, lead: int) -> pd.DataFrame:
    """Add fold-climatology features, target-week metadata and (if present) the tercile
    label for ``lead``. Returns a new frame; the model inputs are :func:`feature_columns`."""
    out = issue.copy()
    t = pd.DatetimeIndex(out["issue_date"])
    ws = t + week_start_offset(lead)
    rpos = clim.region_pos(out["region_id"].to_numpy())
    wdoy, pdoy, tdoy = doy366(ws), doy366(t - pd.Timedelta(days=1)), doy366(t)

    out["week_start"] = ws
    out["week_end"] = ws + pd.Timedelta(days=6)
    out["anom_7d_mm"] = out["rain_sum_7d"] - clim.at("n7", rpos, pdoy)
    out["anom_30d_mm"] = out["rain_sum_30d"] - clim.at("n30", rpos, pdoy)
    out["anom_90d_mm"] = out["rain_sum_90d"] - clim.at("n90", rpos, pdoy)
    out["season_to_date_anom_mm"] = out["season_to_date_mm"] - clim.at("std", rpos, tdoy)
    out["clim_week_mean"] = clim.at("mean", rpos, wdoy)
    out["clim_week_p33"] = clim.at("p33", rpos, wdoy)
    out["clim_week_p67"] = clim.at("p67", rpos, wdoy)
    out["clim_heavy_freq"] = clim.at("f_heavy", rpos, wdoy)
    out["clim_dry_freq"] = clim.at("f_dry", rpos, wdoy)
    out["clim_annual_mm"] = clim.arrays["annual"][rpos]
    # Climatology-baseline quantities (not model inputs).
    for name in ("p10", "p50", "p90", "f_below", "f_normal", "f_above"):
        out[f"cb_{name}"] = clim.at(name, rpos, wdoy)

    if f"total_l{lead}" in out:
        out["y_total"] = out[f"total_l{lead}"]
        out["y_heavy"] = out[f"heavy_l{lead}"]
        out["y_dry"] = out[f"dry_l{lead}"]
        out["y_tercile"] = tercile_class(out["y_total"].to_numpy(),
                                         out["clim_week_p33"].to_numpy(),
                                         out["clim_week_p67"].to_numpy())
    return out


def feature_columns(frame: pd.DataFrame) -> list[str]:
    return [*BASE_FEATURES, *FOLD_FEATURES, *external_columns(frame)]
