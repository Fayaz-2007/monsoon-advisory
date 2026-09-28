"""Hook for external dynamical forecasts (e.g. ECMWF S2S reforecasts / real-time runs).

Not implemented yet: :func:`external_features` returns ``None`` and the models use only
observed predictors. To add S2S later:

1. Download and regrid the forecasts elsewhere (not in this package).
2. Return a DataFrame with ``region_id``, ``issue_date`` and feature columns prefixed
   ``ext_`` (e.g. ``ext_s2s_week1_tp_mm``). Values must be those available ON the issue
   date: use the latest initialisation ≤ t, and reforecasts for the training years.
3. Re-run ``--stage validate`` and ``--stage train``. ``features.feature_columns`` picks up
   any ``ext_`` column automatically, and the model card lists them.
"""

from __future__ import annotations

import pandas as pd


def external_features(issue_dates: pd.DatetimeIndex, region_ids: list[int]) -> pd.DataFrame | None:
    return None
