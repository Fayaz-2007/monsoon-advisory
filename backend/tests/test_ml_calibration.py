"""Calibrated probabilities lie in [0, 1] and tercile probabilities sum to 1."""

import numpy as np

from ml.calibration import P_MIN, BinaryCalibrator, MulticlassCalibrator, normalise
from ml.confidence import confidence_level


def _raw_multiclass(n, rng):
    x = rng.dirichlet([1, 1, 1], size=n)
    y = np.array([rng.choice(3, p=row) for row in x ** 1.5 / (x ** 1.5).sum(1, keepdims=True)])
    return x, y.astype(float)


def test_multiclass_calibration_in_range_and_sums_to_one():
    rng = np.random.default_rng(0)
    p, y = _raw_multiclass(4000, rng)
    cal = MulticlassCalibrator().fit(p, y)
    # include out-of-range and degenerate inputs
    test = np.vstack([rng.dirichlet([0.3, 0.3, 0.3], size=500), [[1, 0, 0], [0, 0, 1], [0, 0, 0]]])
    out = cal.transform(test)
    assert out.shape == test.shape
    assert np.all(out >= P_MIN / 3) and np.all(out <= 1)
    np.testing.assert_allclose(out.sum(axis=1), 1.0, atol=1e-12)


def test_binary_calibration_in_range_and_monotone():
    rng = np.random.default_rng(1)
    p = rng.random(5000)
    y = (rng.random(5000) < p ** 2).astype(float)
    cal = BinaryCalibrator().fit(p, y)
    grid = np.linspace(-0.5, 1.5, 201)
    out = cal.transform(grid)
    assert np.all((out >= P_MIN) & (out <= 1 - P_MIN))
    assert np.all(np.diff(out) >= 0)


def test_normalise_handles_nan_and_zeros():
    out = normalise(np.array([[np.nan, 0.0, 0.0], [0.2, 0.2, 0.6]]))
    np.testing.assert_allclose(out.sum(axis=1), 1.0)
    assert np.all(out > 0)


def test_confidence_rule():
    got = confidence_level(np.array([0.15, 0.15, 0.05, 0.05, 0.01, np.nan]),
                           np.array([0.55, 0.40, 0.50, 0.40, 0.90, 0.90]))
    assert got.tolist() == ["High", "Medium", "Medium", "Low", "Low", "Low"]
