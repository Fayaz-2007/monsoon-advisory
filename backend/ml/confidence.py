"""Confidence level of a forecast row.

skill  = LOWER 5% bound of the year-block bootstrap CI of tercile RPSS for that lead week
         and season (validated on 2011–2025).
sharp  = max(p_below, p_normal, p_above) of the row.

    High    skill ≥ 0.10 and sharp ≥ 0.50
    Medium  skill ≥ 0.10 and sharp < 0.50,  or  0.03 ≤ skill < 0.10 and sharp ≥ 0.45
    Low     everything else (always Low when skill < 0.03)

Thresholds are fixed in ``ml.config`` before validation and never tuned.
"""

from __future__ import annotations

import numpy as np

from ml.config import CFG


def confidence_level(skill_low: np.ndarray | float, sharp: np.ndarray | float) -> np.ndarray:
    s = np.asarray(skill_low, dtype=float)
    p = np.asarray(sharp, dtype=float)
    s = np.where(np.isnan(s), -np.inf, s)
    high = (s >= CFG.rpss_high) & (p >= CFG.sharp_high)
    medium = ((s >= CFG.rpss_high) & (p < CFG.sharp_high)) | (
        (s >= CFG.rpss_medium) & (s < CFG.rpss_high) & (p >= CFG.sharp_medium))
    return np.where(high, "High", np.where(medium, "Medium", "Low"))


def rule_text() -> str:
    return (
        f"skill = lower {CFG.ci_low_pct:.0f}% bound of tercile RPSS (year-block bootstrap, "
        f"{CFG.n_boot} draws) for the lead week and season; sharp = max tercile probability.\n"
        f"High: skill >= {CFG.rpss_high} and sharp >= {CFG.sharp_high}. "
        f"Medium: skill >= {CFG.rpss_high} and sharp < {CFG.sharp_high}, or "
        f"{CFG.rpss_medium} <= skill < {CFG.rpss_high} and sharp >= {CFG.sharp_medium}. "
        f"Low: otherwise (always Low when skill < {CFG.rpss_medium})."
    )
