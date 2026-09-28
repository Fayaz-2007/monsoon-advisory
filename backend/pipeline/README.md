# Segment 1 — Data pipeline

Downloads, cleans and aggregates climate data to block (or district) level and writes
`features_daily`, the table Segment 2 consumes. Output contract:
[`docs/contracts/segment1_output.md`](../../docs/contracts/segment1_output.md).

## Stages

| Stage | Reads | Writes | Notes |
| --- | --- | --- | --- |
| `boundaries` | `data/raw/boundaries/*` | `regions` | block level if present, else district level; upsert by `code` |
| `cropcal` | `data/raw/crop_calendar_tn.csv` | `crop_calendar` | **SAMPLE** seed data |
| `indices` | ONI, DMI, RMM, ROMI URLs | `climate_indices_daily` | files cached in `data/raw/indices/`, refreshed if older than 20 h |
| `rainfall` | IMD via `imdlib` | `data/raw/imd/cropped/*.nc` | final yearly files, plus real-time days for years not yet final |
| `era5` | Copernicus CDS | `data/raw/era5/*.nc` | **optional**: *skipped* without `CDS_API_KEY` |
| `aggregate` | cropped NetCDFs + `regions` | `region_grid_weights`, `rainfall_daily`, `era5_daily` | exact area-weighted zonal mean |
| `climatology` | `rainfall_daily` (1991–2020) | `climatology_daily` | ±15-day pooled window per day of year |
| `features` | all of the above | `features_daily` | see the contract |
| `quality` | all tables | `data/processed/quality_report.md`, `pipeline_runs` | |
| `all` | | | runs every stage above, in order |
| `daily` | | | incremental: indices, new/provisional rainfall, aggregate, features and quality for the recent window |

```
python -m pipeline.run --stage <stage> [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--force] [-v]
```

Every stage is recorded in `pipeline_runs` as `running`, then `success`, `skipped` or `failed`. All table
writes are `INSERT … ON CONFLICT DO UPDATE` via a COPY-to-temp-table bulk path (`db.upsert_df`),
so re-running any stage never duplicates rows. A failed required stage stops `all`. Optional
stages (`era5`, `cropcal`) never stop the run.

## How aggregation works

1. Every IMD grid point becomes a 0.25° cell polygon. Cells that never carry data (sea) or that
   are identically zero in every year are excluded.
2. `region ∩ cell` is computed in lon/lat and its area measured in EPSG:7755 (equal-area). Each
   weight = intersection area / total intersected area of the region.
3. A daily region value is `Σ wᵢ·xᵢ / Σ wᵢ` over the cells valid **that day**, so a missing cell
   renormalises the weights instead of biasing the value toward zero.
4. A region smaller than, or entirely offshore of, every valid cell uses its nearest valid cell
   (`method = 'nearest'`). The quality report lists these regions.

## `daily` mode (for the scheduler)

* Window: from the earliest of `last rainfall date + 1`, `yesterday − 10 days`, and the first day in the
  last 365 days that is missing rainfall (`DAILY_BACKFILL_DAYS`), to yesterday. Days IMD failed to
  serve are therefore retried on every run until they succeed.
* Re-downloads the index files (after 20 h), fetches missing real-time IMD days, **re-fetches
  the last 10 provisional days**, re-aggregates using the stored weights, and recomputes features
  (with 60 days of look-back so rolling windows stay exact and dry-spell counts continue from the
  stored value).
* Real-time days are downloaded 4 at a time (`IMD_REALTIME_WORKERS`), each with 3 retries. The
  IMD server takes 10–30 s per request and sometimes returns empty files. A normal daily run
  (about 10 days re-fetched) takes about 1 minute (measured: 61 s). Catching up after a long gap takes about 1 minute per
  ~10 missing days.
* Suggested schedule: once a day at 12:00 IST (IMD real-time data for the previous day is usually
  posted by late morning).

## Module map

```
config.py        pydantic-settings (every value overridable via env / backend/.env)
db.py            engine, init_db (PostGIS + tables), upsert_df (COPY upsert), track_run
models.py        SQLAlchemy / GeoAlchemy2 tables
logging_setup.py rich console + data/processed/pipeline.log
utils.py         cached downloads, slugify, doy366
sources/         boundaries, crop_calendar, climate_indices, imd_rainfall, era5
transform/       weights (zonal maths), aggregate, climatology, features
quality.py       checks + Markdown report
run.py           CLI
__init__.py      load_features() / load_regions() for Segment 2
```

## Adding another state

Edit `backend/.env`: `STATE_NAME`, `STATE_CODE`, `BBOX_LAT_MIN/MAX`, `BBOX_LON_MIN/MAX` and
`CROP_CALENDAR_FILE`. Then drop that state's boundary file(s) into `data/raw/boundaries/`
and run `--stage all`. Cropped rainfall caches are per bounding box, so delete
`data/raw/imd/cropped/` when you change the box. The raw `.grd` downloads are reused.
