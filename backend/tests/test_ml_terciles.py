"""Tercile thresholds come from training years only."""

import numpy as np
import pandas as pd

from ml.targets import FoldClimatology, tercile_class


def _synthetic_rain(seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2000-01-01", "2005-12-31", freq="D")
    return pd.DataFrame({1: rng.gamma(0.8, 6.0, len(idx)), 2: rng.gamma(1.2, 4.0, len(idx))},
                        index=idx)


def test_thresholds_ignore_test_year():
    rain = _synthetic_rain()
    train = range(2000, 2005)
    base = FoldClimatology.fit(rain, train)

    changed = rain.copy()
    changed.loc["2005"] = changed.loc["2005"] * 50 + 300    # wreck the "test" year
    again = FoldClimatology.fit(changed, train)
    for name in ("p33", "p67", "mean", "f_below", "f_heavy", "f_dry", "n7", "n30", "std"):
        np.testing.assert_array_equal(base.arrays[name], again.arrays[name], err_msg=name)

    with_test = FoldClimatology.fit(changed, range(2000, 2006))
    assert not np.allclose(base.arrays["p67"][:, 1:], with_test.arrays["p67"][:, 1:])


def test_thresholds_split_training_weeks_into_thirds():
    rain = _synthetic_rain(1)
    clim = FoldClimatology.fit(rain, range(2000, 2006))
    below, normal, above = (clim.arrays[k][:, 1:] for k in ("f_below", "f_normal", "f_above"))
    assert np.allclose(below, 1 / 3, atol=0.02)
    assert np.allclose(above, 1 / 3, atol=0.02)
    assert np.allclose(below + normal + above, 1.0)


def test_tercile_class_strict_bounds():
    t33, t67 = np.array([10.0] * 5), np.array([20.0] * 5)
    got = tercile_class(np.array([5.0, 10.0, 15.0, 20.0, 25.0]), t33, t67)
    np.testing.assert_array_equal(got, [0, 1, 1, 1, 2])
    assert np.isnan(tercile_class(np.array([np.nan]), t33[:1], t67[:1])[0])
