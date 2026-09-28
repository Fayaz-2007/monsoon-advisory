"""Targets and fold-aware climatology.

Week window: for issue date t and lead week k the target covers days
``t + 7(k-1) + 1 … t + 7k`` (lead 1 = t+1 … t+7). A week with any missing day has no target.

``FoldClimatology`` holds every quantity estimated from "normal" rainfall — tercile
thresholds, climatological frequencies and the normals used for anomaly features. It is
always fitted on the training years of one fold, never on the year being predicted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ml.config import CFG
from pipeline.utils import doy366

TERCILE_NAMES = ("below", "normal", "above")


# ---------------------------------------------------------------------------
# Week windows and forward-looking weekly stats
# ---------------------------------------------------------------------------


def week_window(issue_date: pd.Timestamp | str, lead: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(first day, last day) of lead week ``lead`` for ``issue_date`` (both inclusive)."""
    t = pd.Timestamp(issue_date).normalize()
    start = t + pd.Timedelta(days=7 * (lead - 1) + 1)
    return start, start + pd.Timedelta(days=6)


def week_start_offset(lead: int) -> pd.Timedelta:
    return pd.Timedelta(days=7 * (lead - 1) + 1)


def forward_week_stats(rain: pd.DataFrame, heavy_mm: float = CFG.heavy_day_mm,
                       dry_mm: float = CFG.dry_day_mm) -> dict[str, pd.DataFrame]:
    """For a wide daily frame (continuous dates × regions) return, indexed by the week's
    FIRST day d: 7-day total over d…d+6, heavy flag (any day ≥ heavy_mm) and dry flag
    (all days < dry_mm). NaN when any of the 7 days is missing."""
    rain = rain.asfreq("D")
    total = rain.rolling(7, min_periods=7).sum().shift(-6)
    wmax = rain.rolling(7, min_periods=7).max().shift(-6)
    heavy = (wmax >= heavy_mm).astype(float).where(wmax.notna())
    dry = (wmax < dry_mm).astype(float).where(wmax.notna())
    return {"total": total, "heavy": heavy, "dry": dry}


def build_targets(rain: pd.DataFrame, issue: pd.DataFrame, leads: Iterable[int] = CFG.leads,
                  ) -> pd.DataFrame:
    """Add per-lead target columns to an issue frame (region_id, issue_date, ...):
    ``total_l{k}``, ``heavy_l{k}``, ``dry_l{k}`` (NaN when the week is incomplete)."""
    stats = forward_week_stats(rain)
    out = issue.copy()
    cols = {rid: i for i, rid in enumerate(rain.columns)}
    ridx = out["region_id"].map(cols).to_numpy()
    for k in leads:
        ws = pd.DatetimeIndex(out["issue_date"]) + week_start_offset(k)
        for name, frame in stats.items():
            arr = frame.to_numpy()
            pos = frame.index.get_indexer(ws)
            vals = np.full(len(out), np.nan)
            ok = pos >= 0
            vals[ok] = arr[pos[ok], ridx[ok]]
            out[f"{name}_l{k}"] = vals
    return out


def tercile_class(total: np.ndarray, t33: np.ndarray, t67: np.ndarray) -> np.ndarray:
    """0 = below (< p33), 1 = normal, 2 = above (> p67); NaN where total or thresholds are NaN.

    Strict inequalities: when many weeks are exactly 0 mm (p33 = 0), a dry week counts as
    'normal', which is what it climatologically is."""
    out = np.where(total < t33, 0.0, np.where(total > t67, 2.0, 1.0))
    return np.where(np.isnan(total) | np.isnan(t33) | np.isnan(t67), np.nan, out)


# ---------------------------------------------------------------------------
# Season-to-date rainfall (value known at issue date t: rain from season start to t-1)
# ---------------------------------------------------------------------------


def season_start(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Jun 1 for Jan–Sep issue dates (SW monsoon), Oct 1 for Oct–Dec (NE monsoon)."""
    month = np.where(dates.month >= 10, 10, 6)
    return pd.to_datetime(pd.DataFrame({"year": dates.year, "month": month, "day": 1}))


def season_to_date(rain: pd.DataFrame, issue_dates: pd.DatetimeIndex) -> np.ndarray:
    """[n_issue_dates, n_regions] rain summed over season_start(t) … t-1 (0 on the first day).
    NaN if any day in that span is missing or t is before Jun 1."""
    rain = rain.asfreq("D")
    csum = rain.fillna(0.0).cumsum()
    cnan = rain.isna().astype(float).cumsum()
    t = pd.DatetimeIndex(issue_dates)
    s = pd.DatetimeIndex(season_start(t))
    end_pos = csum.index.get_indexer(t - pd.Timedelta(days=1))
    start_pos = csum.index.get_indexer(s - pd.Timedelta(days=1))
    c, n = csum.to_numpy(), cnan.to_numpy()
    out = np.full((len(t), rain.shape[1]), np.nan)
    ok = (end_pos >= 0) & (start_pos >= 0) & (t.month >= 6)
    val = c[end_pos[ok]] - c[start_pos[ok]]
    bad = (n[end_pos[ok]] - n[start_pos[ok]]) > 0
    out[ok] = np.where(bad, np.nan, val)
    return out


# ---------------------------------------------------------------------------
# Fold climatology
# ---------------------------------------------------------------------------

CLIM_WEEK_FIELDS = ("mean", "p10", "p33", "p50", "p67", "p90",
                    "f_below", "f_normal", "f_above", "f_heavy", "f_dry")
CLIM_TRAIL_FIELDS = ("n7", "n30", "n90", "std")


def window_mask(doys: np.ndarray, half_window: int) -> np.ndarray:
    """[367, n_days] bool, row d (1..366) True where a day's doy is within ±half_window
    (circular 366-day year). Row 0 is unused."""
    targets = np.arange(0, 367)[:, None]
    diff = np.abs(targets - doys[None, :])
    circ = np.minimum(diff, 366 - diff)
    mask = circ <= half_window
    mask[0] = False
    return mask


def _pooled_mean(mask: np.ndarray, values: np.ndarray) -> np.ndarray:
    valid = ~np.isnan(values)
    m = mask.astype(np.float64)
    num = m @ np.where(valid, values, 0.0)
    den = m @ valid.astype(np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


@dataclass
class FoldClimatology:
    """Arrays shaped [n_regions, 367], indexed by region position and doy (1..366)."""

    region_ids: np.ndarray
    train_years: tuple[int, ...]
    arrays: dict[str, np.ndarray]

    @classmethod
    def fit(cls, rain: pd.DataFrame, train_years: Iterable[int],
            half_window: int = CFG.clim_half_window) -> FoldClimatology:
        """Fit on ``rain`` (wide daily, FINAL data only) restricted to ``train_years``.

        Weekly quantities pool all 7-day windows whose first day falls within ±half_window
        days of the target week's first day and that lie entirely inside training years
        (a window starting Dec 28 of the last training year would otherwise reach into
        January of the test year). Trailing normals pool the
        trailing 7/30/90-day sums the same way; the season-to-date normal is the mean for
        the exact issue day of year.
        """
        years = tuple(sorted(int(y) for y in train_years))
        rain = rain.asfreq("D")
        idx = rain.index
        in_train = np.isin(idx.year, years)
        doys = doy366(idx)
        mask = window_mask(doys[in_train], half_window)
        week_in_train = in_train & np.isin((idx + pd.Timedelta(days=6)).year, years)
        wmask = window_mask(doys[week_in_train], half_window)

        wk = forward_week_stats(rain)
        total = wk["total"].to_numpy()[week_in_train]
        arrays: dict[str, np.ndarray] = {}
        arrays["mean"] = _pooled_mean(wmask, total).T
        arrays["f_heavy"] = _pooled_mean(wmask, wk["heavy"].to_numpy()[week_in_train]).T
        arrays["f_dry"] = _pooled_mean(wmask, wk["dry"].to_numpy()[week_in_train]).T

        n_reg = rain.shape[1]
        pct = {k: np.full((367, n_reg), np.nan) for k in ("p10", "p33", "p50", "p67", "p90")}
        freq = {k: np.full((367, n_reg), np.nan) for k in ("f_below", "f_normal", "f_above")}
        for d in range(1, 367):
            pool = total[wmask[d]]
            if pool.size == 0:
                continue
            with np.errstate(all="ignore"):
                q = np.nanpercentile(pool, [10, 100 / 3, 50, 200 / 3, 90], axis=0)
            for name, row in zip(("p10", "p33", "p50", "p67", "p90"), q, strict=True):
                pct[name][d] = row
            valid = ~np.isnan(pool)
            nvalid = valid.sum(axis=0).astype(float)
            with np.errstate(all="ignore"):
                below = ((pool < q[1]) & valid).sum(axis=0) / nvalid
                above = ((pool > q[3]) & valid).sum(axis=0) / nvalid
            freq["f_below"][d], freq["f_above"][d] = below, above
            freq["f_normal"][d] = 1.0 - below - above
        for name, a in {**pct, **freq}.items():
            arrays[name] = a.T

        for w in (7, 30, 90):
            trail = rain.rolling(w, min_periods=w).sum().to_numpy()[in_train]
            arrays[f"n{w}"] = _pooled_mean(mask, trail).T

        # Season-to-date normal, by exact issue doy (Jun–Dec issue dates only).
        issue_days = idx[in_train & (idx.month >= CFG.issue_start_month)]
        std = season_to_date(rain, issue_days)
        std_norm = np.full((367, n_reg), np.nan)
        dd = doy366(issue_days)
        for d in np.unique(dd):
            with np.errstate(all="ignore"):
                std_norm[d] = np.nanmean(std[dd == d], axis=0)
        arrays["std"] = std_norm.T

        full = rain[in_train]
        per_year = full.groupby(full.index.year).sum(min_count=360)
        arrays["annual"] = per_year.mean(axis=0).to_numpy()
        return cls(np.asarray(rain.columns, dtype=np.int64), years, arrays)

    # -- lookups ---------------------------------------------------------
    def region_pos(self, region_ids: np.ndarray) -> np.ndarray:
        lookup = {int(r): i for i, r in enumerate(self.region_ids)}
        pos = np.array([lookup.get(int(r), -1) for r in region_ids])
        if (pos < 0).any():
            raise KeyError(f"regions not in climatology: {sorted(set(region_ids[pos < 0]))}")
        return pos

    def at(self, name: str, rpos: np.ndarray, doy: np.ndarray) -> np.ndarray:
        return self.arrays[name][rpos, doy]

    # -- persistence -----------------------------------------------------
    def save(self, path: Path) -> None:
        np.savez_compressed(path, region_ids=self.region_ids,
                            train_years=np.asarray(self.train_years), **self.arrays)

    @classmethod
    def load(cls, path: Path) -> FoldClimatology:
        z = np.load(path)
        arrays = {k: z[k] for k in z.files if k not in ("region_ids", "train_years")}
        return cls(z["region_ids"], tuple(int(y) for y in z["train_years"]), arrays)
