"""Segment 2 settings. Everything that affects model behaviour is fixed here, before any
validation run, and copied into each model card. Nothing in this file is tuned on test years."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pipeline.config import BACKEND_DIR, get_settings

ARTIFACTS_DIR: Path = BACKEND_DIR / "ml" / "artifacts"
MLRUNS_DIR: Path = BACKEND_DIR / "mlruns"
WORK_DIR: Path = BACKEND_DIR / "data" / "processed" / "ml"
LATEST_POINTER: Path = ARTIFACTS_DIR / "LATEST"

MLFLOW_EXPERIMENT = "segment2-monsoon-ml"


@dataclass(frozen=True)
class IndexLag:
    """Publication rule for a monthly index: month M becomes usable on day ``pub_day`` of
    month M + ``delay_months``. At issue date t the latest usable month is used."""

    delay_months: int
    pub_day: int = 1


@dataclass(frozen=True)
class MLConfig:
    leads: tuple[int, ...] = (1, 2, 3, 4)
    issue_start_month: int = 6          # issue dates Jun 1 ...
    issue_end_month: int = 12           # ... to Dec 31
    first_year: int = 1991
    first_oof_year: int = 2001          # rolling-origin predictions start here (calibration pool)
    first_test_year: int = 2011         # scored test years 2011..last final year
    early_stop_years: int = 2           # last N training years = early-stopping set
    heavy_day_mm: float = 64.5          # IMD "heavy rain" threshold
    dry_day_mm: float = field(default_factory=lambda: get_settings().dry_day_threshold_mm)
    clim_half_window: int = 15          # ± days pooled for week climatologies
    quantiles: tuple[float, ...] = (0.1, 0.5, 0.9)

    # ENSO: 3-month ONI centred on M needs M+1; CPC publishes ~1st week of M+2 → day 10.
    oni_lag: IndexLag = IndexLag(delay_months=2, pub_day=10)
    # DMI (HadISST, NOAA PSL): observed operational lag is ~4 months (Sep 2026 file ends May).
    dmi_lag: IndexLag = IndexLag(delay_months=4, pub_day=1)

    # Year-block bootstrap for skill confidence intervals.
    n_boot: int = 1000
    ci_low_pct: float = 5.0
    ci_high_pct: float = 95.0
    seed: int = 42

    # Confidence rule (fixed a priori): uses the LOWER 5% bound of tercile RPSS.
    rpss_high: float = 0.10
    rpss_medium: float = 0.03
    sharp_high: float = 0.50
    sharp_medium: float = 0.45

    # LightGBM (fixed; no tuning on test years).
    max_rounds: int = 600
    early_stopping_rounds: int = 40
    lgbm_params: dict = field(default_factory=lambda: {
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l2": 1.0,
        "max_bin": 255,
        "seed": 42,
        "verbose": -1,
    })


CFG = MLConfig()

SEASONS: dict[str, tuple[int, ...]] = {
    "SWM": (6, 7, 8, 9),
    "NEM": (10, 11, 12),
}


def season_of_month(month: int) -> str:
    for name, months in SEASONS.items():
        if month in months:
            return name
    return "OFF"
