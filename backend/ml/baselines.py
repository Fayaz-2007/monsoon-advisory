"""Reference forecasts built from an assembled frame (see ``features.assemble``).

* climatology — tercile probabilities = in-fold climatological class frequencies of the
  target week (1/3 each unless many weeks tie at 0 mm); P(heavy), P(dry) = in-fold
  climatological frequencies; quantiles = in-fold climatological p10/p50/p90.
* persistence — "next week looks like last week": the tercile of the last 7 days' total
  (t−7 … t−1) judged against the target week's thresholds, last week's heavy/dry flags,
  and last week's total as all three quantiles. Issued as certain (0/1) forecasts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.config import CFG
from ml.targets import tercile_class


def climatology(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    p = frame[["cb_f_below", "cb_f_normal", "cb_f_above"]].to_numpy(dtype=float)
    return {
        "tercile": p,
        "heavy_day": frame["clim_heavy_freq"].to_numpy(dtype=float),
        "dry_week": frame["clim_dry_freq"].to_numpy(dtype=float),
        "q10": frame["cb_p10"].to_numpy(dtype=float),
        "q50": frame["cb_p50"].to_numpy(dtype=float),
        "q90": frame["cb_p90"].to_numpy(dtype=float),
    }


def persistence(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    last7 = frame["rain_sum_7d"].to_numpy(dtype=float)
    cls = tercile_class(last7, frame["clim_week_p33"].to_numpy(dtype=float),
                        frame["clim_week_p67"].to_numpy(dtype=float))
    p = np.full((len(frame), 3), np.nan)
    ok = ~np.isnan(cls)
    p[ok] = np.eye(3)[cls[ok].astype(int)]
    heavy = (frame["max_1day_rain_last_7"].to_numpy(dtype=float) >= CFG.heavy_day_mm).astype(float)
    dry = (frame["max_1day_rain_last_7"].to_numpy(dtype=float) < CFG.dry_day_mm).astype(float)
    return {"tercile": p, "heavy_day": heavy, "dry_week": dry,
            "q10": last7, "q50": last7, "q90": last7}
