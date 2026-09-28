"""Isotonic calibration fitted on out-of-fold predictions.

Binary targets: one isotonic map P_raw → P. Terciles: one-vs-rest isotonic per class,
then renormalised so the three probabilities sum to 1. Outputs are clipped to
[P_MIN, 1 − P_MIN] so a calibrated forecast is never exactly 0 or 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.isotonic import IsotonicRegression

P_MIN = 0.001


def _iso() -> IsotonicRegression:
    return IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")


@dataclass
class BinaryCalibrator:
    iso: IsotonicRegression = field(default_factory=_iso)

    def fit(self, p: np.ndarray, y: np.ndarray) -> BinaryCalibrator:
        ok = ~(np.isnan(p) | np.isnan(y))
        self.iso.fit(p[ok], y[ok])
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        return np.clip(self.iso.predict(p), P_MIN, 1.0 - P_MIN)


@dataclass
class MulticlassCalibrator:
    n_class: int = 3
    isos: list[IsotonicRegression] = field(default_factory=list)

    def fit(self, p: np.ndarray, y: np.ndarray) -> MulticlassCalibrator:
        ok = ~(np.isnan(p).any(axis=1) | np.isnan(y))
        self.isos = [_iso().fit(p[ok, k], (y[ok] == k).astype(float)) for k in range(self.n_class)]
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        cal = np.column_stack([iso.predict(p[:, k]) for k, iso in enumerate(self.isos)])
        return normalise(cal)


def normalise(p: np.ndarray) -> np.ndarray:
    """Clip to [P_MIN, 1] and rescale rows to sum to 1 (uniform if a row is all ~0)."""
    p = np.clip(np.nan_to_num(p, nan=0.0), P_MIN, 1.0)
    s = p.sum(axis=1, keepdims=True)
    return p / s
