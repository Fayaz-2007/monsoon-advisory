# Segment 2 — ML prediction engine

Weekly rainfall forecasts for every district, lead weeks 1–4, issued daily Jun 1 – Dec 31:
tercile probabilities, p10/p50/p90 weekly totals, P(heavy day), P(dry week) and a confidence level.

* Input contract: `docs/contracts/segment1_output.md` (read via `pipeline.load_features()`).
* Output contract: `docs/contracts/segment2_output.md` (read via `ml.load_forecasts()`).

## Run

```bash
python -m ml.run --stage build-targets   # features + targets → data/processed/ml/*.parquet
python -m ml.run --stage validate        # rolling-origin hindcast 2001–2025 → model_skill, artifacts
python -m ml.run --stage train           # final models on 1991–2025 + calibrators + model card
python -m ml.run --stage predict --issue-date 2026-09-28
python -m ml.run --stage all             # all four in order
```

`validate` must run before `train`: the final calibrators are fitted on the validation's
out-of-fold predictions, and the boosting rounds are the median early-stopping iteration.
`predict` without `--issue-date` uses the day after the last rainfall date.

## Modules

| File | Role |
| --- | --- |
| `config.py` | every fixed setting: lags, thresholds, LightGBM params, bootstrap, confidence rule |
| `targets.py` | week windows, weekly targets, `FoldClimatology` (tercile thresholds etc., training years only) |
| `features.py` | issue-date features with explicit lags; `assemble` adds fold features for one lead |
| `external.py` | hook for ECMWF S2S (or other dynamical) features; returns None for now |
| `data.py` | loads Segment 1 data, builds and caches the dataset |
| `models.py` | LightGBM quantile / multiclass / binary models, boosted from climatology |
| `calibration.py` | isotonic calibration (tercile probabilities renormalised to sum to 1) |
| `baselines.py` | climatology and persistence reference forecasts |
| `metrics.py` | RPSS, BSS, AUC, pinball / CRPS approx, year-block bootstrap, reliability plots |
| `validate.py` | rolling-origin OOF, per-year calibration, skill table |
| `train.py` | final models, calibrators, feature importance, `model_card.md` |
| `confidence.py` | High / Medium / Low rule |
| `predict.py` | real-time forecasts → `forecasts` |
| `schema.py` | `forecasts` / `model_skill` DDL and idempotent upsert |
| `tracking.py` | MLflow (local file store `backend/mlruns/`) |

Artifacts (`backend/ml/artifacts/<model_version>/`, git-ignored): models, calibrators,
climatology, OOF predictions, `skill.csv`, reliability PNGs, `model_card.md`.
