"""Final models: trained on every final year, calibrated on the rolling-origin OOF.

Needs a validated model version (``--stage validate`` first): the number of boosting rounds
per model is the median early-stopping iteration across the validation folds, and the
isotonic calibrators are fitted on all OOF predictions.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.confidence import rule_text
from ml.config import ARTIFACTS_DIR, CFG, LATEST_POINTER
from ml.data import Dataset
from ml.features import CATEGORICAL, FEATURE_LAGS, assemble, feature_columns
from ml.models import MODEL_KEYS, SPECS, fit
from ml.targets import FoldClimatology
from ml.validate import fit_calibrators


def latest_validated() -> str:
    cands = sorted(p.parent.name for p in ARTIFACTS_DIR.glob("*/validation.json"))
    if not cands:
        raise RuntimeError("No validated model version. Run: python -m ml.run --stage validate")
    return cands[-1]


def latest_trained() -> str:
    if LATEST_POINTER.exists():
        mv = LATEST_POINTER.read_text(encoding="utf-8").strip()
        if (ARTIFACTS_DIR / mv / "meta.json").exists():
            return mv
    raise RuntimeError("No trained model. Run: python -m ml.run --stage train")


def run_train(ds: Dataset, progress: Callable[[str], None], model_version: str | None = None
              ) -> dict:
    t0 = time.perf_counter()
    mv = model_version or latest_validated()
    out = ARTIFACTS_DIR / mv
    val = json.loads((out / "validation.json").read_text(encoding="utf-8"))
    (out / "models").mkdir(parents=True, exist_ok=True)

    years = list(range(CFG.first_year, ds.final_end.year + 1))
    progress(f"climatology {years[0]}-{years[-1]}")
    clim = FoldClimatology.fit(ds.rain, years)
    clim.save(out / "climatology.npz")

    rounds: dict[str, dict[int, int]] = {}
    importance: list[pd.DataFrame] = []
    feats: list[str] = []
    n_rows: dict[int, int] = {}
    for lead in CFG.leads:
        frame = assemble(ds.issue, clim, lead)
        frame = frame[frame["y_total"].notna()]
        feats = feature_columns(frame)
        n_rows[lead] = len(frame)
        for key in MODEL_KEYS:
            progress(f"final model · lead {lead} · {key}")
            n = int(np.median(val["best_iters"][key][str(lead)]))
            rounds.setdefault(key, {})[lead] = n
            label = SPECS[key].label
            tr = frame[frame[label].notna()]
            booster, _ = fit(key, tr[feats], tr, rounds=n)
            booster.save_model(str(out / "models" / f"{key}_l{lead}.txt"))
            gain = booster.feature_importance(importance_type="gain")
            importance.append(pd.DataFrame({"feature": booster.feature_name(), "gain": gain,
                                            "model": key, "lead": lead}))

    progress("isotonic calibrators (all OOF years)")
    oof = pd.read_parquet(out / "oof.parquet")
    joblib.dump(fit_calibrators(oof), out / "calibrators.joblib")

    imp = pd.concat(importance, ignore_index=True)
    # Normalise gain within each model, then average across the 24 models.
    imp["share"] = imp["gain"] / imp.groupby(["model", "lead"])["gain"].transform("sum")
    top = (imp.groupby("feature")["share"].mean().sort_values(ascending=False) * 100).round(2)
    top.to_csv(out / "feature_importance.csv", header=["mean_gain_pct"])

    seconds = round(time.perf_counter() - t0, 1)
    meta = {
        "model_version": mv,
        "trained": datetime.now().isoformat(timespec="seconds"),
        "train_years": [years[0], years[-1]],
        "final_data_end": ds.final_end.isoformat(),
        "features": feats,
        "categorical": [c for c in CATEGORICAL if c in feats],
        "rounds": rounds,
        "rows_per_lead": n_rows,
        "rpss_ci_low": val["rpss_ci_low"],
        "train_seconds": seconds,
        "validate_seconds": val["seconds"],
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    skill = pd.read_csv(out / "skill.csv")
    (out / "model_card.md").write_text(model_card(meta, val, skill, top), encoding="utf-8")
    LATEST_POINTER.write_text(mv, encoding="utf-8")
    return {"meta": meta, "top": top, "seconds": seconds}


def load_models(mv: str) -> tuple[dict, dict[tuple[str, int], lgb.Booster], dict, FoldClimatology]:
    out = ARTIFACTS_DIR / mv
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    boosters = {(k, lead): lgb.Booster(model_file=str(out / "models" / f"{k}_l{lead}.txt"))
                for k in MODEL_KEYS for lead in CFG.leads}
    cals = joblib.load(out / "calibrators.joblib")
    return meta, boosters, cals, FoldClimatology.load(out / "climatology.npz")


# ---------------------------------------------------------------------------
# Model card
# ---------------------------------------------------------------------------


def _fmt(v: float, lo: float, hi: float, digits: int = 3) -> str:
    if pd.isna(v):
        return "–"
    s = f"{v:.{digits}f}"
    return s if pd.isna(lo) else f"{s} [{lo:.{digits}f}, {hi:.{digits}f}]"


def skill_markdown(skill: pd.DataFrame, model: str = "lgbm") -> str:
    """Lead × season table: tercile RPSS, heavy/dry BSS + AUC, quantile QSS, with 5–95% CIs."""
    s = skill[skill["model"] == model]
    pick = {("tercile", "rpss"): "Tercile RPSS", ("heavy_day", "bss"): "Heavy BSS",
            ("heavy_day", "auc"): "Heavy AUC", ("dry_week", "bss"): "Dry-week BSS",
            ("dry_week", "auc"): "Dry-week AUC", ("weekly_total_mm", "qss"): "Quantile skill"}
    head = "| Lead | Season | " + " | ".join(pick.values()) + " |"
    lines = [head, "|" + "---|" * (len(pick) + 2)]
    for lead in CFG.leads:
        for season in ("SWM", "NEM", "ALL"):
            cells = []
            for (target, metric) in pick:
                r = s[(s["target"] == target) & (s["metric"] == metric)
                      & (s["lead_week"] == lead) & (s["season"] == season)]
                cells.append("–" if r.empty else _fmt(r["value"].iloc[0], r["ci_low"].iloc[0],
                                                      r["ci_high"].iloc[0]))
            lines.append(f"| {lead} | {season} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def confidence_table(rpss_low: dict[str, float]) -> str:
    lines = ["| Lead | SWM RPSS lower bound → max level | NEM RPSS lower bound → max level |",
             "|---|---|---|"]

    def tier(v: float) -> str:
        if v is None or pd.isna(v) or v < CFG.rpss_medium:
            return "Low only"
        return "up to High" if v >= CFG.rpss_high else "up to Medium"

    for lead in CFG.leads:
        a, b = rpss_low.get(f"{lead}|SWM"), rpss_low.get(f"{lead}|NEM")
        lines.append(f"| {lead} | {a:.3f} → {tier(a)} | {b:.3f} → {tier(b)} |")
    return "\n".join(lines)


def model_card(meta: dict, val: dict, skill: pd.DataFrame, top: pd.Series) -> str:
    feats = meta["features"]
    lag_rows = "\n".join(f"| `{f}` | {FEATURE_LAGS.get(f, 'external hook (value available on t)')} |"
                         for f in feats)
    rounds = "\n".join(f"| {k} | " + " | ".join(str(meta["rounds"][k][lead]) for lead in CFG.leads) + " |"
                       for k in MODEL_KEYS)
    params = "\n".join(f"| `{k}` | {v} |" for k, v in CFG.lgbm_params.items())
    top15 = "\n".join(f"| {i} | `{f}` | {v:.2f} |" for i, (f, v) in enumerate(top.head(15).items(), 1))
    pngs = "\n".join(f"- `{Path(p).relative_to(ARTIFACTS_DIR / meta['model_version']).as_posix()}`"
                     for p in val["reliability_pngs"])
    return f"""# Model card · {meta['model_version']}

Segment 2 of the Hyperlocal Monsoon Onset & Break Prediction System: weekly rainfall
forecasts for the 38 Tamil Nadu districts, lead weeks 1–4, issued daily Jun 1 – Dec 31.

## Data and training
| Item | Value |
|---|---|
| Final models trained on | issue years {meta['train_years'][0]}–{meta['train_years'][1]} (IMD final gridded rainfall to {meta['final_data_end']}) |
| Rows per lead week | {', '.join(f"L{k}: {v:,}" for k, v in meta['rows_per_lead'].items())} |
| Validation | rolling origin by year: out-of-fold years {val['oof_years'][0]}–{val['oof_years'][-1]}; **scored test years {val['test_years'][0]}–{val['test_years'][-1]}** |
| Fold scheme | test year Y: climatology from {CFG.first_year}–(Y−1); train {CFG.first_year}–(Y−3); early stopping on (Y−2)–(Y−1) |
| Calibration | isotonic on OOF predictions; for test year Y fitted on {val['oof_years'][0]}–(Y−1) only. Final calibrators use all OOF years. |
| Confidence intervals | year-block bootstrap: resample test years, {CFG.n_boot} draws, {CFG.ci_low_pct:.0f}–{CFG.ci_high_pct:.0f}% |
| Validation time | {meta['validate_seconds'] / 60:.1f} min |
| Final training time | {meta['train_seconds'] / 60:.1f} min |

## Targets
Week k after issue date t covers days t+7(k−1)+1 … t+7k.
* `weekly_total_mm` → quantiles p10 / p50 / p90 (LightGBM quantile loss on log1p)
* tercile (below / normal / above) vs the district's own week climatology (±{CFG.clim_half_window} days, training years only)
* `heavy_day`: any day ≥ {CFG.heavy_day_mm} mm · `dry_week`: all 7 days < {CFG.dry_day_mm} mm

## Features and lags (issue date t; m = month of t)
| Feature | Value used |
|---|---|
{lag_rows}

## Fixed hyperparameters (not tuned on test years)
| Parameter | Value |
|---|---|
{params}
| `max_rounds` / early stopping | {CFG.max_rounds} / {CFG.early_stopping_rounds} |

Boosting rounds of the final models (median best iteration across folds):

| Model | L1 | L2 | L3 | L4 |
|---|---|---|---|---|
{rounds}

## Skill vs climatology, test years {val['test_years'][0]}–{val['test_years'][-1]} (value [5%, 95%])
Positive = better than climatology. Quantile skill = 1 − mean pinball / climatology's.

{skill_markdown(skill, 'lgbm')}

### Persistence baseline (same metrics)
{skill_markdown(skill, 'persistence')}

## Confidence level
{rule_text()}

{confidence_table(meta['rpss_ci_low'])}

## Top 15 features (mean share of gain across the 24 models, %)
| # | Feature | Gain % |
|---|---|---|
{top15}

## Reliability diagrams (calibrated, test years)
{pngs}

## Limitations
* District averages of 0.25° IMD grids; no station-level or block-level detail.
* Predictors are observations only (no dynamical model yet); skill beyond week 2 comes mostly from
  seasonality, ENSO and district climatology.
* MJO source changes from BoM RMM to rotated ROMI in Feb 2024; only 2024–2025 test years use ROMI.
* 2026 rainfall is IMD provisional real-time data; real-time forecasts use it as input.
* Quantiles are not calibrated (check `coverage_80`), and CRPS is approximated from 3 quantiles.
"""
