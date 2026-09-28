"""Rolling-origin hindcast, calibration and skill (the honest part).

1. For every year Y from ``first_oof_year`` to the last final year: fit the fold
   climatology on 1991…Y−1, train on 1991…Y−3, early-stop on Y−2…Y−1, predict Y
   (out-of-fold, "OOF").
2. For each scored test year Y ≥ ``first_test_year``: fit the isotonic calibrators on the
   OOF predictions of ``first_oof_year``…Y−1 only, then calibrate Y.
3. Score 2011… per target × lead × season against climatology (and persistence), with
   year-block bootstrap CIs. Test years are never used to choose anything.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml import baselines, metrics
from ml.calibration import BinaryCalibrator, MulticlassCalibrator
from ml.config import ARTIFACTS_DIR, CFG, SEASONS
from ml.data import Dataset
from ml.features import assemble, feature_columns
from ml.models import MODEL_KEYS, QUANTILE_KEYS, SPECS, fit, predict, sort_quantiles
from ml.targets import FoldClimatology

log = logging.getLogger(__name__)

KEEP = ["region_id", "issue_date", "year", "week_start", "y_total", "y_tercile", "y_heavy",
        "y_dry", "cb_f_below", "cb_f_normal", "cb_f_above", "cb_p10", "cb_p50", "cb_p90",
        "clim_heavy_freq", "clim_dry_freq", "clim_week_p33", "clim_week_p67",
        "rain_sum_7d", "max_1day_rain_last_7"]
SEASON_ALL = "ALL"


def new_model_version() -> str:
    return f"s2-lgbm-{datetime.now():%Y%m%d-%H%M}"


def season_col(issue_dates: pd.Series) -> np.ndarray:
    m = pd.DatetimeIndex(issue_dates).month
    return np.where(np.isin(m, SEASONS["SWM"]), "SWM", np.where(np.isin(m, SEASONS["NEM"]), "NEM", "OFF"))


# ---------------------------------------------------------------------------
# 1. Rolling-origin out-of-fold predictions
# ---------------------------------------------------------------------------


def rolling_oof(ds: Dataset, years: list[int], progress: Callable[[str], None]
                ) -> tuple[pd.DataFrame, dict[str, dict[int, list[int]]], dict[int, float]]:
    frames: list[pd.DataFrame] = []
    best_iters: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    fold_secs: dict[int, float] = {}
    for n, Y in enumerate(years, 1):
        t0 = time.perf_counter()
        progress(f"fold {n}/{len(years)}: test {Y} · climatology {CFG.first_year}-{Y - 1}")
        clim = FoldClimatology.fit(ds.rain, range(CFG.first_year, Y))
        sub = ds.issue[ds.issue["year"] <= Y]
        for lead in CFG.leads:
            frame = assemble(sub, clim, lead)
            frame = frame[frame["y_total"].notna()]
            feats = feature_columns(frame)
            yr = frame["year"]
            tr = frame[yr < Y - CFG.early_stop_years]
            va = frame[(yr >= Y - CFG.early_stop_years) & (yr < Y)]
            te = frame[yr == Y]
            out = te[KEEP].copy()
            out["lead"] = lead
            for key in MODEL_KEYS:
                progress(f"fold {n}/{len(years)}: test {Y} · lead {lead} · {key}")
                label = SPECS[key].label
                tr_k, va_k = tr[tr[label].notna()], va[va[label].notna()]
                booster, it = fit(key, tr_k[feats], tr_k, va_k[feats], va_k)
                best_iters[key][lead].append(it)
                pred = predict(key, booster, te, feats)
                if key == "tercile":
                    out[["raw_below", "raw_normal", "raw_above"]] = pred
                elif key in QUANTILE_KEYS:
                    out[key] = pred
                else:
                    out[f"raw_{key}"] = pred
            out["q10"], out["q50"], out["q90"] = sort_quantiles(
                out["q10"].to_numpy(), out["q50"].to_numpy(), out["q90"].to_numpy())
            frames.append(out)
        fold_secs[Y] = time.perf_counter() - t0
        log.info("fold %d done in %.0fs", Y, fold_secs[Y])
    oof = pd.concat(frames, ignore_index=True)
    oof["season"] = season_col(oof["issue_date"])
    return oof, {k: dict(v) for k, v in best_iters.items()}, fold_secs


# ---------------------------------------------------------------------------
# 2. Calibration (never sees the test year)
# ---------------------------------------------------------------------------

RAW_T = ["raw_below", "raw_normal", "raw_above"]
CAL_T = ["p_below", "p_normal", "p_above"]


def fit_calibrators(oof: pd.DataFrame) -> dict[int, dict[str, object]]:
    """Per lead: tercile + heavy_day + dry_week calibrators fitted on the given OOF rows."""
    cals: dict[int, dict[str, object]] = {}
    for lead, g in oof.groupby("lead"):
        cals[int(lead)] = {
            "tercile": MulticlassCalibrator().fit(g[RAW_T].to_numpy(), g["y_tercile"].to_numpy()),
            "heavy_day": BinaryCalibrator().fit(g["raw_heavy_day"].to_numpy(), g["y_heavy"].to_numpy()),
            "dry_week": BinaryCalibrator().fit(g["raw_dry_week"].to_numpy(), g["y_dry"].to_numpy()),
        }
    return cals


def apply_calibrators(frame: pd.DataFrame, cals: dict[int, dict[str, object]]) -> pd.DataFrame:
    out = frame.copy()
    for col in (*CAL_T, "p_heavy", "p_dry_week"):
        out[col] = np.nan
    for lead, idx in out.groupby("lead").groups.items():
        c = cals[int(lead)]
        g = out.loc[idx]
        out.loc[idx, CAL_T] = c["tercile"].transform(g[RAW_T].to_numpy())
        out.loc[idx, "p_heavy"] = c["heavy_day"].transform(g["raw_heavy_day"].to_numpy())
        out.loc[idx, "p_dry_week"] = c["dry_week"].transform(g["raw_dry_week"].to_numpy())
    return out


def calibrate_test_years(oof: pd.DataFrame, test_years: list[int]) -> pd.DataFrame:
    parts = []
    for Y in test_years:
        cals = fit_calibrators(oof[oof["year"] < Y])
        parts.append(apply_calibrators(oof[oof["year"] == Y], cals))
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------------------
# 3. Scores
# ---------------------------------------------------------------------------


def _row(target, lead, season, metric, model, value, lo=np.nan, hi=np.nan, n=0, ny=0) -> dict:
    return {"target": target, "lead_week": lead, "season": season, "metric": metric,
            "model": model, "value": value, "ci_low": lo, "ci_high": hi,
            "n_samples": int(n), "n_years": int(ny)}


def score_group(g: pd.DataFrame, lead: int, season: str, rng: np.random.Generator) -> list[dict]:
    rows: list[dict] = []
    yrs = g["year"].to_numpy()
    ny = len(np.unique(yrs))
    clim = baselines.climatology(g)
    pers = baselines.persistence(g)
    models = {
        "lgbm": {"tercile": g[CAL_T].to_numpy(), "heavy_day": g["p_heavy"].to_numpy(),
                 "dry_week": g["p_dry_week"].to_numpy(),
                 **{k: g[k].to_numpy() for k in QUANTILE_KEYS}},
        "lgbm_uncalibrated": {"tercile": g[RAW_T].to_numpy(),
                              "heavy_day": g["raw_heavy_day"].to_numpy(),
                              "dry_week": g["raw_dry_week"].to_numpy()},
        "persistence": pers,
    }

    # Terciles: RPS / RPSS
    yt = g["y_tercile"].to_numpy()
    ok = ~np.isnan(yt)
    rps_ref = np.full(len(g), np.nan)
    rps_ref[ok] = metrics.rps(clim["tercile"][ok], yt[ok])
    rows.append(_row("tercile", lead, season, "rps", "climatology", np.nanmean(rps_ref), n=ok.sum(), ny=ny))
    for name, fc in models.items():
        r = np.full(len(g), np.nan)
        okm = ok & ~np.isnan(fc["tercile"]).any(axis=1)
        r[okm] = metrics.rps(fc["tercile"][okm], yt[okm])
        rows.append(_row("tercile", lead, season, "rps", name, np.nanmean(r), n=okm.sum(), ny=ny))
        rows.append(_row("tercile", lead, season, "rpss", name,
                         *metrics.skill_score(r, rps_ref, yrs, rng), n=okm.sum(), ny=ny))

    # Binary: Brier / BSS / AUC
    for target, ycol in (("heavy_day", "y_heavy"), ("dry_week", "y_dry")):
        y = g[ycol].to_numpy(dtype=float)
        bs_ref = metrics.brier(clim[target], y)
        rows.append(_row(target, lead, season, "brier", "climatology", np.nanmean(bs_ref),
                         n=np.isfinite(bs_ref).sum(), ny=ny))
        rows.append(_row(target, lead, season, "base_rate", "observed", np.nanmean(y),
                         n=np.isfinite(y).sum(), ny=ny))
        for name, fc in models.items():
            bs = metrics.brier(fc[target], y)
            n = np.isfinite(bs).sum()
            rows.append(_row(target, lead, season, "brier", name, np.nanmean(bs), n=n, ny=ny))
            rows.append(_row(target, lead, season, "bss", name,
                             *metrics.skill_score(bs, bs_ref, yrs, rng), n=n, ny=ny))
            rows.append(_row(target, lead, season, "auc", name,
                             *metrics.auc_score(fc[target], y, yrs, rng), n=n, ny=ny))

    # Quantiles: pinball per level, approx CRPS, quantile skill score, 80% coverage
    y = g["y_total"].to_numpy(dtype=float)
    qs_ref = np.mean([metrics.pinball(clim[k], y, a) for k, a in QUANTILE_KEYS.items()], axis=0)
    rows.append(_row("weekly_total_mm", lead, season, "crps_approx", "climatology",
                     2 * np.nanmean(qs_ref), n=np.isfinite(qs_ref).sum(), ny=ny))
    for name in ("lgbm", "persistence"):
        fc = models[name]
        pins = {k: metrics.pinball(fc[k], y, a) for k, a in QUANTILE_KEYS.items()}
        qs = np.mean(list(pins.values()), axis=0)
        n = np.isfinite(qs).sum()
        for k, v in pins.items():
            rows.append(_row("weekly_total_mm", lead, season, f"pinball_{k}", name, np.nanmean(v), n=n, ny=ny))
        rows.append(_row("weekly_total_mm", lead, season, "crps_approx", name, 2 * np.nanmean(qs), n=n, ny=ny))
        rows.append(_row("weekly_total_mm", lead, season, "qss", name,
                         *metrics.skill_score(qs, qs_ref, yrs, rng), n=n, ny=ny))
        cov = ((y >= fc["q10"]) & (y <= fc["q90"])).astype(float)
        rows.append(_row("weekly_total_mm", lead, season, "coverage_80", name,
                         float(np.nanmean(np.where(np.isfinite(y), cov, np.nan))), n=n, ny=ny))
    return rows


def score(cal: pd.DataFrame, progress: Callable[[str], None]) -> pd.DataFrame:
    rng = np.random.default_rng(CFG.seed)
    rows: list[dict] = []
    for lead in CFG.leads:
        for season in ("SWM", "NEM", SEASON_ALL):
            progress(f"scoring lead {lead} · {season} (bootstrap {CFG.n_boot})")
            g = cal[cal["lead"] == lead]
            if season != SEASON_ALL:
                g = g[g["season"] == season]
            rows.extend(score_group(g, lead, season, rng))
    return pd.DataFrame(rows)


def reliability_plots(cal: pd.DataFrame, out_dir: Path) -> list[Path]:
    paths = []
    specs = [("p_below", "y_tercile", 0, "P(below normal)"),
             ("p_above", "y_tercile", 2, "P(above normal)"),
             ("p_heavy", "y_heavy", None, "P(heavy day ≥ 64.5 mm)"),
             ("p_dry_week", "y_dry", None, "P(dry week)")]
    for col, ycol, cls, title in specs:
        for lead in CFG.leads:
            g = cal[cal["lead"] == lead]
            curves = {}
            for season in ("SWM", "NEM"):
                s = g[g["season"] == season]
                y = s[ycol].to_numpy(dtype=float)
                if cls is not None:
                    y = np.where(np.isnan(y), np.nan, (y == cls).astype(float))
                curves[season] = (s[col].to_numpy(dtype=float), y)
            path = out_dir / f"reliability_{col}_lead{lead}.png"
            metrics.plot_reliability(curves, f"{title} · lead week {lead} · test years "
                                     f"{int(cal['year'].min())}–{int(cal['year'].max())}", path)
            paths.append(path)
    return paths


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_validate(ds: Dataset, progress: Callable[[str], None], model_version: str | None = None
                 ) -> dict:
    t0 = time.perf_counter()
    mv = model_version or new_model_version()
    out_dir = ARTIFACTS_DIR / mv
    out_dir.mkdir(parents=True, exist_ok=True)
    last_year = ds.final_end.year
    oof_years = list(range(CFG.first_oof_year, last_year + 1))
    test_years = [y for y in oof_years if y >= CFG.first_test_year]

    oof, best_iters, fold_secs = rolling_oof(ds, oof_years, progress)
    oof.to_parquet(out_dir / "oof.parquet", index=False)

    progress("calibrating test years (calibrators fitted on earlier years only)")
    cal = calibrate_test_years(oof, test_years)
    cal.to_parquet(out_dir / "oof_calibrated.parquet", index=False)

    skill = score(cal, progress)
    skill.insert(5, "model_version", mv)
    skill.to_csv(out_dir / "skill.csv", index=False)
    progress("reliability diagrams")
    pngs = reliability_plots(cal, out_dir / "reliability")

    rpss = skill[(skill["target"] == "tercile") & (skill["metric"] == "rpss") & (skill["model"] == "lgbm")]
    info = {
        "model_version": mv,
        "created": datetime.now().isoformat(timespec="seconds"),
        "oof_years": oof_years,
        "test_years": test_years,
        "final_data_end": ds.final_end.isoformat(),
        "best_iters": {k: {str(l): v for l, v in d.items()} for k, d in best_iters.items()},
        "fold_seconds": {str(k): round(v, 1) for k, v in fold_secs.items()},
        "rpss_ci_low": {f"{int(r.lead_week)}|{r.season}": r.ci_low for r in rpss.itertuples()},
        "rpss": {f"{int(r.lead_week)}|{r.season}": r.value for r in rpss.itertuples()},
        "reliability_pngs": [str(p) for p in pngs],
        "n_oof_rows": len(oof),
        "n_test_rows": len(cal),
        "seconds": round(time.perf_counter() - t0, 1),
    }
    (out_dir / "validation.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return {"info": info, "skill": skill, "oof": oof, "cal": cal}
