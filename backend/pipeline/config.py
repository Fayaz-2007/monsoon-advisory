"""Central configuration (pydantic-settings).

Every value can be overridden by an environment variable of the same name
(case-insensitive) or by ``backend/.env``. Adding a new state means changing
STATE_NAME / STATE_CODE / BBOX_* / CROP_CALENDAR_FILE and dropping new boundary
files into ``data/raw/boundaries/`` — no code changes.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR: Path = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database ---
    # Always set DATABASE_URL in backend/.env; this default only documents the expected shape.
    database_url: str = "postgresql+psycopg2://monsoon_app@localhost:5432/monsoon"

    # --- Region of interest ---
    state_name: str = "Tamil Nadu"
    state_code: str = "tn"
    bbox_lat_min: float = 7.75
    bbox_lat_max: float = 13.75
    bbox_lon_min: float = 76.0
    bbox_lon_max: float = 80.5
    boundary_file: str | None = None
    # Optional explicit attribute-column names in the boundary file (else auto-detected).
    boundary_name_col: str | None = None
    boundary_district_col: str | None = None
    boundary_state_col: str | None = None
    crop_calendar_file: str = "crop_calendar_tn.csv"

    # --- Paths ---
    data_dir: Path = BACKEND_DIR / "data"

    # --- Dates ---
    start_date: date = date(1991, 1, 1)
    end_date: date = date(2025, 12, 31)
    clim_start_year: int = 1991
    clim_end_year: int = 2020
    clim_window_days: int = Field(15, description="± days pooled around each day-of-year")

    # --- Grid / geometry ---
    imd_grid_res: float = 0.25
    era5_grid_res: float = 0.25
    equal_area_crs: str = "EPSG:7755"  # India NSF LCC — used for area computations

    # --- Features ---
    dry_day_threshold_mm: float = 2.5
    rain_flag_threshold_mm: float = 500.0
    monsoon_season_start_month: int = 6
    monsoon_season_end_month: int = 12
    anomaly_pct_min_clim_mm: float = Field(
        1.0, description="Percent-of-normal is NULL when the climatological sum is below this"
    )
    feature_lookback_days: int = 60  # history loaded before --start so rolling windows are complete

    # --- Climate indices ---
    oni_url: str = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
    dmi_url: str = "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data"
    rmm_url: str = "http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt"
    romi_url: str = "https://psl.noaa.gov/mjo/mjoindex/romi.cpcolr.1x.txt"
    romi_rotation_deg: float = -30.0  # calibration of ROMI onto RMM phase space
    mjo_source_mode: Literal["rmm_then_romi", "rmm_only", "romi_only"] = "rmm_then_romi"
    index_refresh_hours: int = 20  # re-download index files older than this
    monthly_index_ffill_days: int = 92  # forward-fill ONI/DMI at most this far past last value
    daily_index_ffill_days: int = 5  # forward-fill RMM/ROMI gaps at most this far
    indices_start_date: date = date(1990, 1, 1)  # ≥30 days before start_date for lag features

    # --- IMD ---
    imd_keep_grd: bool = True
    imd_realtime_days_back: int = 10  # daily mode re-fetches this many recent days (provisional)
    imd_realtime_url: str = "https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php"
    daily_backfill_days: int = 365  # daily mode retries rainfall gaps this far back
    imd_realtime_workers: int = 4  # parallel downloads (IMD server is ~10-30 s per request)

    # --- ERA5 (optional) ---
    cds_api_key: str | None = None
    cds_api_url: str = "https://cds.climate.copernicus.eu/api"
    era5_start_date: date = date(2015, 1, 1)

    # --- Network ---
    http_proxy_url: str | None = None
    http_timeout_s: int = 120
    user_agent: str = "Mozilla/5.0 (monsoon-advisory data pipeline)"

    @field_validator("boundary_file", "cds_api_key", "http_proxy_url", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    # --- Derived paths ---
    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def boundaries_dir(self) -> Path:
        return self.raw_dir / "boundaries"

    @property
    def imd_dir(self) -> Path:
        return self.raw_dir / "imd"

    @property
    def indices_dir(self) -> Path:
        return self.raw_dir / "indices"

    @property
    def era5_dir(self) -> Path:
        return self.raw_dir / "era5"

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(lon_min, lat_min, lon_max, lat_max)."""
        return (self.bbox_lon_min, self.bbox_lat_min, self.bbox_lon_max, self.bbox_lat_max)

    @property
    def proxies(self) -> dict[str, str] | None:
        if not self.http_proxy_url:
            return None
        return {"http": self.http_proxy_url, "https": self.http_proxy_url}

    def ensure_dirs(self) -> None:
        for d in (self.raw_dir, self.processed_dir, self.boundaries_dir, self.imd_dir,
                  self.indices_dir, self.era5_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
