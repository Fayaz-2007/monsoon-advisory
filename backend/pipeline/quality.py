"""Data-quality checks → data/processed/quality_report.md (+ summary in pipeline_runs)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from pipeline.config import get_settings
from pipeline.db import read_df
from pipeline.utils import as_date

log = logging.getLogger(__name__)


@dataclass
class QualityResult:
    checks: list[tuple[str, str, str]] = field(default_factory=list)  # (name, status, detail)
    sections: list[str] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, warn_only: bool = False) -> None:
        status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
        self.checks.append((name, status, detail))

    @property
    def n_fail(self) -> int:
        return sum(1 for _, s, _ in self.checks if s == "FAIL")

    @property
    def n_warn(self) -> int:
        return sum(1 for _, s, _ in self.checks if s == "WARN")

    def summary(self) -> str:
        return (f"{len(self.checks)} checks: {len(self.checks) - self.n_fail - self.n_warn} pass, "
                f"{self.n_warn} warn, {self.n_fail} fail")


def _md_table(df: pd.DataFrame, max_rows: int = 25) -> str:
    if df.empty:
        return "_none_\n"
    shown = df.head(max_rows)
    lines = ["| " + " | ".join(map(str, shown.columns)) + " |",
             "| " + " | ".join("---" for _ in shown.columns) + " |"]
    for row in shown.itertuples(index=False):
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
    if len(df) > max_rows:
        lines.append(f"\n_… {len(df) - max_rows} more rows_")
    return "\n".join(lines) + "\n"


def _gaps(dates: pd.Series) -> pd.DataFrame:
    """Contiguous runs of missing dates → DataFrame[gap_start, gap_end, days]."""
    if dates.empty:
        return pd.DataFrame(columns=["gap_start", "gap_end", "days"])
    d = pd.to_datetime(dates).sort_values().reset_index(drop=True)
    new_run = d.diff().dt.days.ne(1)
    grp = new_run.cumsum()
    runs = d.groupby(grp).agg(["min", "max", "count"])
    runs.columns = ["gap_start", "gap_end", "days"]
    runs["gap_start"] = runs["gap_start"].dt.date
    runs["gap_end"] = runs["gap_end"].dt.date
    return runs.sort_values("days", ascending=False).reset_index(drop=True)


def run_quality(start: date, end: date) -> QualityResult:
    s = get_settings()
    res = QualityResult()
    regions = read_df("SELECT id, code, name, district, level, area_km2 FROM regions "
                      "WHERE active AND state = :s ORDER BY id", {"s": s.state_name})
    res.add("regions loaded", not regions.empty,
            f"{len(regions)} active regions" + (f" ({regions['level'].iloc[0]} level)"
                                                 if not regions.empty else ""))

    rng = read_df("SELECT min(date) AS lo, max(date) AS hi FROM rainfall_daily")
    lo, hi = as_date(rng["lo"].iloc[0]), as_date(rng["hi"].iloc[0])
    if lo is not None and hi is not None:
        start, end = max(start, lo), min(end, hi)
    n_days = (end - start).days + 1 if end >= start else 0

    # 1. Missing dates per region
    cov = read_df("""
        SELECT r.id AS region_id, r.name, r.district,
               count(rd.rain_mm) AS days_with_rain
        FROM regions r
        LEFT JOIN rainfall_daily rd ON rd.region_id = r.id AND rd.date BETWEEN :a AND :b
        WHERE r.active AND r.state = :s
        GROUP BY r.id, r.name, r.district ORDER BY r.id
    """, {"a": start, "b": end, "s": s.state_name})
    cov["missing_days"] = n_days - cov["days_with_rain"]
    bad_cov = cov[cov["missing_days"] > 0].sort_values("missing_days", ascending=False)
    res.add("missing rainfall dates per region", bad_cov.empty,
            f"{len(bad_cov)} of {len(cov)} regions have gaps in {start}..{end} ({n_days} days)")
    res.sections.append("## Missing rainfall dates per region\n\n"
                        f"Window: {start} to {end} ({n_days} days)\n\n" + _md_table(bad_cov))

    # 2. Negative rainfall
    neg = read_df("SELECT region_id, date, rain_mm FROM rainfall_daily WHERE rain_mm < 0 "
                  "ORDER BY rain_mm LIMIT 100")
    res.add("negative rainfall", neg.empty, f"{len(neg)} rows < 0 mm")
    res.sections.append("## Negative rainfall\n\n" + _md_table(neg))

    # 3. Extreme values
    ext = read_df("""SELECT rd.region_id, r.name, r.district, rd.date, rd.rain_mm
                     FROM rainfall_daily rd JOIN regions r ON r.id = rd.region_id
                     WHERE rd.rain_mm > :t ORDER BY rd.rain_mm DESC LIMIT 100""",
                  {"t": s.rain_flag_threshold_mm})
    res.add(f"rainfall > {s.rain_flag_threshold_mm:g} mm/day", ext.empty,
            f"{len(ext)} rows flagged (review, not necessarily wrong)", warn_only=True)
    res.sections.append(f"## Rainfall above {s.rain_flag_threshold_mm:g} mm/day (flagged)\n\n"
                        + _md_table(ext))

    # 4. Regions with no grid cells / nearest-cell fallback
    w = read_df("""
        SELECT r.id AS region_id, r.name, r.district, round(r.area_km2::numeric, 1) AS area_km2,
               count(w.region_id) AS n_cells, max(w.method) AS method
        FROM regions r LEFT JOIN region_grid_weights w
             ON w.region_id = r.id AND w.grid = 'imd025'
        WHERE r.active AND r.state = :s
        GROUP BY r.id, r.name, r.district, r.area_km2 ORDER BY r.id
    """, {"s": s.state_name})
    none = w[w["n_cells"] == 0]
    nearest = w[w["method"] == "nearest"]
    res.add("regions with no grid cells", none.empty, f"{len(none)} regions have no weights")
    res.add("regions using nearest-cell fallback", nearest.empty,
            f"{len(nearest)} regions (too small / coastal for area overlap)", warn_only=True)
    res.sections.append("## Regions with no grid cells\n\n" + _md_table(none)
                        + "\n### Regions using nearest-cell fallback\n\n" + _md_table(nearest)
                        + "\n### Grid cells per region (distribution)\n\n"
                        + _md_table(w["n_cells"].describe().round(2).reset_index()
                                    .rename(columns={"index": "stat"})))

    # 5. Climate-index coverage gaps
    idx = read_df("SELECT * FROM climate_indices_daily WHERE date BETWEEN :a AND :b "
                  "ORDER BY date", {"a": start, "b": end})
    all_days = pd.date_range(start, end, freq="D")
    parts = []
    if idx.empty:
        res.add("climate index coverage", False, "climate_indices_daily has no rows in window")
    else:
        idx["date"] = pd.to_datetime(idx["date"])
        full = idx.set_index("date").reindex(all_days)
        rows = []
        for col in ["oni", "dmi", "rmm1", "rmm2", "mjo_phase", "mjo_amplitude"]:
            missing = full.index[full[col].isna()].to_series()
            rows.append({"index": col, "missing_days": len(missing),
                         "coverage_pct": round(100 * (1 - len(missing) / len(all_days)), 2)})
            if len(missing):
                g = _gaps(missing)
                parts.append(f"### {col} gaps\n\n" + _md_table(g, 10))
        cov_df = pd.DataFrame(rows)
        worst = cov_df["missing_days"].max()
        res.add("climate index coverage", worst == 0,
                f"max {worst} missing days in any index column", warn_only=True)
        src = idx["mjo_source"].value_counts(dropna=False).rename_axis("mjo_source") \
            .reset_index(name="days")
        parts.insert(0, _md_table(cov_df) + "\n### MJO source mix\n\n" + _md_table(src))
    res.sections.append("## Climate index coverage\n\n" + "\n".join(parts))

    # 6. Table row counts + feature coverage
    counts = read_df("""
        SELECT "table", "rows" FROM (
                  SELECT 1 AS o, 'regions (active)' AS "table", count(*) AS "rows" FROM regions WHERE active
        UNION ALL SELECT 2, 'region_grid_weights', count(*) FROM region_grid_weights
        UNION ALL SELECT 3, 'rainfall_daily', count(*) FROM rainfall_daily
        UNION ALL SELECT 4, 'climate_indices_daily', count(*) FROM climate_indices_daily
        UNION ALL SELECT 5, 'era5_daily', count(*) FROM era5_daily
        UNION ALL SELECT 6, 'climatology_daily', count(*) FROM climatology_daily
        UNION ALL SELECT 7, 'features_daily', count(*) FROM features_daily
        UNION ALL SELECT 8, 'crop_calendar', count(*) FROM crop_calendar
        UNION ALL SELECT 9, 'pipeline_runs', count(*) FROM pipeline_runs
        ) c ORDER BY o
    """)
    clim_n = int(counts.loc[counts["table"] == "climatology_daily", "rows"].iloc[0])
    res.add("climatology complete", clim_n >= 366 * len(regions),
            f"{clim_n} rows (expected {366 * len(regions)})", warn_only=True)
    feat = read_df("""
        SELECT count(*) AS n_rows, count(rain_sum_30d) AS with_30d, count(anomaly_30d_mm) AS with_anom,
               count(oni) AS with_oni, count(rmm1) AS with_mjo, count(tcwv) AS with_era5,
               min(date) AS first_date, max(date) AS last_date
        FROM features_daily f JOIN regions r ON r.id = f.region_id WHERE r.active
    """)
    res.add("features_daily populated", int(feat["n_rows"].iloc[0]) > 0,
            f"{int(feat['n_rows'].iloc[0])} rows, {feat['first_date'].iloc[0]} to "
            f"{feat['last_date'].iloc[0]}")
    res.sections.insert(0, "## Table row counts\n\n" + _md_table(counts)
                        + "\n### features_daily non-null counts\n\n" + _md_table(feat))

    write_report(res, start, end)
    return res


def write_report(res: QualityResult, start: date, end: date) -> None:
    s = get_settings()
    lines = [
        "# Segment 1 data-quality report",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} · state **{s.state_name}** · window {start} to {end}",
        "",
        f"**{res.summary()}**",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
        *[f"| {n} | {st} | {d} |" for n, st, d in res.checks],
        "",
        *res.sections,
    ]
    path = s.processed_dir / "quality_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Quality report written to %s (%s)", path, res.summary())
