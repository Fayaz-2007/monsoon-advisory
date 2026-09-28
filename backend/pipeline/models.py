"""SQLAlchemy / GeoAlchemy2 table definitions for Segment 1."""

from __future__ import annotations

from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    REAL as Real,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    district: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False)
    area_km2: Mapped[float] = mapped_column(Float, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    source_file: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("level IN ('block', 'district')", name="ck_regions_level"),
        Index("ix_regions_state_level", "state", "level"),
    )


class RegionGridWeight(Base):
    __tablename__ = "region_grid_weights"

    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), primary_key=True
    )
    grid: Mapped[str] = mapped_column(Text, primary_key=True)
    lat: Mapped[float] = mapped_column(Float, primary_key=True)
    lon: Mapped[float] = mapped_column(Float, primary_key=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False, server_default="area")


class RainfallDaily(Base):
    __tablename__ = "rainfall_daily"

    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    rain_mm: Mapped[float | None] = mapped_column(Real)
    n_cells: Mapped[int | None] = mapped_column(SmallInteger)
    source: Mapped[str | None] = mapped_column(Text)  # 'imd_final' | 'imd_realtime'

    __table_args__ = (Index("ix_rainfall_daily_date", "date"),)


class ClimateIndexDaily(Base):
    __tablename__ = "climate_indices_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    oni: Mapped[float | None] = mapped_column(Real)
    dmi: Mapped[float | None] = mapped_column(Real)
    rmm1: Mapped[float | None] = mapped_column(Real)
    rmm2: Mapped[float | None] = mapped_column(Real)
    mjo_phase: Mapped[int | None] = mapped_column(SmallInteger)
    mjo_amplitude: Mapped[float | None] = mapped_column(Real)
    mjo_source: Mapped[str | None] = mapped_column(Text)  # 'rmm' | 'romi'


class Era5Daily(Base):
    __tablename__ = "era5_daily"

    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    u850: Mapped[float | None] = mapped_column(Real)
    v850: Mapped[float | None] = mapped_column(Real)
    tcwv: Mapped[float | None] = mapped_column(Real)
    olr: Mapped[float | None] = mapped_column(Real)


class ClimatologyDaily(Base):
    __tablename__ = "climatology_daily"

    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), primary_key=True
    )
    doy: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    rain_mean: Mapped[float | None] = mapped_column(Real)
    rain_p50: Mapped[float | None] = mapped_column(Real)
    rain_p90: Mapped[float | None] = mapped_column(Real)
    clim_sum_7d: Mapped[float | None] = mapped_column(Real)
    clim_sum_30d: Mapped[float | None] = mapped_column(Real)
    n_years: Mapped[int | None] = mapped_column(SmallInteger)

    __table_args__ = (CheckConstraint("doy BETWEEN 1 AND 366", name="ck_clim_doy"),)


class FeatureDaily(Base):
    __tablename__ = "features_daily"

    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    rain_mm: Mapped[float | None] = mapped_column(Real)
    rain_sum_3d: Mapped[float | None] = mapped_column(Real)
    rain_sum_7d: Mapped[float | None] = mapped_column(Real)
    rain_sum_14d: Mapped[float | None] = mapped_column(Real)
    rain_sum_30d: Mapped[float | None] = mapped_column(Real)
    anomaly_7d_mm: Mapped[float | None] = mapped_column(Real)
    anomaly_7d_pct: Mapped[float | None] = mapped_column(Real)
    anomaly_30d_mm: Mapped[float | None] = mapped_column(Real)
    anomaly_30d_pct: Mapped[float | None] = mapped_column(Real)
    consecutive_dry_days: Mapped[int | None] = mapped_column(SmallInteger)
    wet_days_last_7: Mapped[int | None] = mapped_column(SmallInteger)
    wet_days_last_14: Mapped[int | None] = mapped_column(SmallInteger)
    max_1day_rain_last_7: Mapped[float | None] = mapped_column(Real)
    doy_sin: Mapped[float] = mapped_column(Real, nullable=False)
    doy_cos: Mapped[float] = mapped_column(Real, nullable=False)
    oni: Mapped[float | None] = mapped_column(Real)
    oni_lag30: Mapped[float | None] = mapped_column(Real)
    dmi: Mapped[float | None] = mapped_column(Real)
    dmi_lag30: Mapped[float | None] = mapped_column(Real)
    rmm1: Mapped[float | None] = mapped_column(Real)
    rmm2: Mapped[float | None] = mapped_column(Real)
    mjo_phase: Mapped[int | None] = mapped_column(SmallInteger)
    mjo_amplitude: Mapped[float | None] = mapped_column(Real)
    mjo_source: Mapped[str | None] = mapped_column(Text)
    u850: Mapped[float | None] = mapped_column(Real)
    v850: Mapped[float | None] = mapped_column(Real)
    tcwv: Mapped[float | None] = mapped_column(Real)
    olr: Mapped[float | None] = mapped_column(Real)
    is_monsoon_season: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_features_daily_date", "date"),)


class CropCalendar(Base):
    __tablename__ = "crop_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    district: Mapped[str] = mapped_column(Text, nullable=False)
    crop: Mapped[str] = mapped_column(Text, nullable=False)
    season: Mapped[str] = mapped_column(Text, nullable=False)
    sowing_start_doy: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sowing_end_doy: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    stage_name: Mapped[str] = mapped_column(Text, nullable=False)
    stage_start_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    stage_end_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    source: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("state", "district", "crop", "season", "stage_name",
                         name="uq_crop_calendar_stage"),
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    message: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JSONB)
