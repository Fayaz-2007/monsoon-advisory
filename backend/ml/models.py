"""LightGBM wrappers: one global model per target per lead week (all districts pooled).

Model keys: ``q10``/``q50``/``q90`` (quantile regression on log1p(weekly_total_mm)),
``tercile`` (multiclass, 3 classes), ``heavy_day`` and ``dry_week`` (binary).

Boosting starts from the fold climatology (``init_score``): logit of the climatological
frequency, log of the tercile class frequencies, log1p of the climatological quantile.
The trees therefore learn departures from each district's normal for that week, instead
of first having to rediscover the climatology from a single global average.
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.config import CFG
from ml.features import CATEGORICAL

QUANTILE_KEYS = {"q10": 0.1, "q50": 0.5, "q90": 0.9}
MODEL_KEYS = [*QUANTILE_KEYS, "tercile", "heavy_day", "dry_week"]


P_CLIP = 0.005  # climatological probabilities are clipped before logit/log


@dataclass(frozen=True)
class Spec:
    objective: dict
    label: str
    init_cols: tuple[str, ...]  # fold-climatology columns the boosting starts from

    @property
    def kind(self) -> str:
        return {"quantile": "quantile", "multiclass": "multiclass"}.get(
            self.objective["objective"], "binary")

    def y(self, frame: pd.DataFrame) -> np.ndarray:
        y = frame[self.label].to_numpy(dtype=float)
        return np.log1p(y) if self.kind == "quantile" else y

    def init_score(self, frame: pd.DataFrame) -> np.ndarray:
        c = frame[list(self.init_cols)].to_numpy(dtype=float)
        if self.kind == "quantile":
            return np.log1p(np.clip(np.nan_to_num(c[:, 0]), 0.0, None))
        c = np.clip(np.nan_to_num(c, nan=1.0 / max(c.shape[1], 2)), P_CLIP, 1 - P_CLIP)
        if self.kind == "binary":
            return np.log(c[:, 0] / (1 - c[:, 0]))
        return np.log(c / c.sum(axis=1, keepdims=True))  # [n, 3]; LightGBM wants it flat

    def transform(self, raw: np.ndarray) -> np.ndarray:
        if self.kind == "quantile":
            return np.clip(np.expm1(raw), 0.0, None)
        if self.kind == "binary":
            return 1.0 / (1.0 + np.exp(-raw))
        e = np.exp(raw - raw.max(axis=1, keepdims=True))
        return e / e.sum(axis=1, keepdims=True)


SPECS: dict[str, Spec] = {
    **{k: Spec({"objective": "quantile", "alpha": a, "metric": "quantile"}, "y_total",
               (f"cb_p{int(round(a * 100))}",))
       for k, a in QUANTILE_KEYS.items()},
    "tercile": Spec({"objective": "multiclass", "num_class": 3, "metric": "multi_logloss"},
                    "y_tercile", ("cb_f_below", "cb_f_normal", "cb_f_above")),
    "heavy_day": Spec({"objective": "binary", "metric": "binary_logloss"}, "y_heavy",
                      ("clim_heavy_freq",)),
    "dry_week": Spec({"objective": "binary", "metric": "binary_logloss"}, "y_dry",
                     ("clim_dry_freq",)),
}


def _dataset(X: pd.DataFrame, y: np.ndarray, init: np.ndarray,
             reference: lgb.Dataset | None = None) -> lgb.Dataset:
    cats = [c for c in CATEGORICAL if c in X.columns]
    # Multiclass init_score is class-major when flattened (all rows of class 0, then 1, 2).
    init = init.T.ravel() if init.ndim == 2 else init
    return lgb.Dataset(X, label=y, init_score=init, categorical_feature=cats,
                       reference=reference, free_raw_data=True)


def fit(key: str, X_tr: pd.DataFrame, tr: pd.DataFrame, X_va: pd.DataFrame | None = None,
        va: pd.DataFrame | None = None, rounds: int | None = None) -> tuple[lgb.Booster, int]:
    """Train one model. With a validation set: early stopping, returns the best iteration.
    Without: exactly ``rounds`` rounds (used for the final all-years model)."""
    spec = SPECS[key]
    params = {**CFG.lgbm_params, **spec.objective}
    dtrain = _dataset(X_tr, spec.y(tr), spec.init_score(tr))
    if X_va is not None and va is not None:
        dvalid = _dataset(X_va, spec.y(va), spec.init_score(va), reference=dtrain)
        booster = lgb.train(params, dtrain, num_boost_round=CFG.max_rounds, valid_sets=[dvalid],
                            callbacks=[lgb.early_stopping(CFG.early_stopping_rounds, verbose=False)])
        return booster, int(booster.best_iteration or CFG.max_rounds)
    n = int(rounds or CFG.max_rounds)
    return lgb.train(params, dtrain, num_boost_round=n), n


def predict(key: str, booster: lgb.Booster, frame: pd.DataFrame, features: list[str]
            ) -> np.ndarray:
    """Uncalibrated prediction: mm for quantiles, class probabilities [n,3] for tercile,
    P(1) for binary. ``frame`` must hold the features and the climatology init columns."""
    spec = SPECS[key]
    raw = booster.predict(frame[features], num_iteration=booster.best_iteration or None,
                          raw_score=True)
    return spec.transform(np.asarray(raw) + spec.init_score(frame))


def sort_quantiles(q10: np.ndarray, q50: np.ndarray, q90: np.ndarray
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Remove quantile crossing by sorting the three values per row."""
    q = np.sort(np.column_stack([q10, q50, q90]), axis=1)
    return q[:, 0], q[:, 1], q[:, 2]
