# Contract: Segment 1 → Segment 2 (`features_daily`)

**Owner:** Segment 1 (data pipeline) · **Consumer:** Segment 2 (ML) · **Version:** 1.0 (2026-09-28)

Segment 2 reads **only** `features_daily` (plus `regions` for metadata), preferably through
the helper:

```python
from pipeline import load_features, load_regions

df = load_features(region_ids=None, start="1991-01-01", end="2025-12-31")  # all active regions
meta = load_regions()   # id, code, name, district, level, state, area_km2
```

`load_features` returns a `pandas.DataFrame` sorted by `(region_id, date)` with every column
below except `updated_at`. Its dtypes are fixed, whatever rows you select: `region_id` int64,
`date` datetime64[ns], `consecutive_dry_days` / `wet_days_last_7` / `wet_days_last_14` /
`mjo_phase` nullable `Int64`, `mjo_source` `string`, `is_monsoon_season` bool, and every other
column float64 (NULL → NaN). With `region_ids=None` only
**active** regions (the currently loaded boundary level) are returned.

## Grain and keys

* One row per **region per calendar day**. Primary key: `(region_id, date)`.
* `region_id` → `regions.id`. `regions.level` is `block` or `district` (depends on which
  boundary files were loaded); `regions.code` (`tn/<district>/<block>`) is the stable
  human-readable key and survives reloads. Always join on `region_id` within one database.
* Dates run continuously from the pipeline `--start` to the last day with rainfall data.
  No gaps in dates. Missing *values* are NULL, never filled or imputed.
* There are **no targets or labels** in this table. Segment 2 owns those.

## Columns

Conventions: "trailing *N* days" means the *N* days ending **on and including** `date`.
A **wet day** has `rain_mm ≥ 2.5` and a **dry day** has `rain_mm < 2.5` (`DRY_DAY_THRESHOLD_MM`).

| Column | Type | Unit | Definition | NULL when |
| --- | --- | --- | --- | --- |
| `region_id` | int | — | FK to `regions.id` | never |
| `date` | date | — | calendar day (IST day as defined by IMD: 08:30 IST of `date` to 08:30 IST of the next day) | never |
| `rain_mm` | real | mm/day | area-weighted mean of IMD 0.25° gridded rainfall over the region | no IMD data that day |
| `rain_sum_3d` / `_7d` / `_14d` / `_30d` | real | mm | trailing 3/7/14/30-day sum | any day in the window is NULL |
| `anomaly_7d_mm` | real | mm | `rain_sum_7d − clim_sum_7d(doy)` | sum NULL or no climatology |
| `anomaly_7d_pct` | real | % of normal | `100 × rain_sum_7d / clim_sum_7d` (100 = normal) | as above, or `clim_sum_7d < 1 mm` |
| `anomaly_30d_mm` | real | mm | `rain_sum_30d − clim_sum_30d(doy)` | as above |
| `anomaly_30d_pct` | real | % of normal | `100 × rain_sum_30d / clim_sum_30d` | as above, or `clim_sum_30d < 1 mm` |
| `consecutive_dry_days` | smallint | days | length of the dry run ending on `date` (0 on a wet day) | `rain_mm` NULL (count restarts at 0 after a gap) |
| `wet_days_last_7` / `_14` | smallint | days | number of wet days in the trailing 7/14 days | any day in window NULL |
| `max_1day_rain_last_7` | real | mm | max daily rain in the trailing 7 days | any day in window NULL |
| `doy_sin`, `doy_cos` | real | — | `sin/cos(2π·(doy−1)/366)` on a 366-day calendar (Feb 29 = 60, Mar 1 = 61 every year) | never |
| `oni` | real | °C | ONI anomaly of the 3-month season **centred** on this month (CPC) | beyond 92 days after last published value |
| `oni_lag30` | real | °C | `oni` at `date − 30 days` | as above |
| `dmi` | real | °C | monthly Dipole Mode Index (HadISST, NOAA PSL) for this month | beyond 92 days after last value |
| `dmi_lag30` | real | °C | `dmi` at `date − 30 days` | as above |
| `rmm1`, `rmm2` | real | σ | MJO RMM components (see `mjo_source`) | gap > 5 days in source |
| `mjo_phase` | smallint | 1–8 | Wheeler–Hendon phase | as above |
| `mjo_amplitude` | real | σ | `sqrt(rmm1² + rmm2²)` as published | as above |
| `mjo_source` | text | — | `rmm` (BoM RMM, 1974 to 2024-02-24) or `romi` (NOAA PSL real-time OMI, rotated −30° onto RMM space) | as above |
| `u850`, `v850` | real | m/s | ERA5 850 hPa wind, daily mean of 00/06/12/18 UTC | ERA5 not configured / before `ERA5_START_DATE` / ~6-day ERA5 lag |
| `tcwv` | real | kg/m² | ERA5 total column water vapour | as above |
| `olr` | real | W/m² | ERA5 OLR proxy (`−ttr/3600`) | as above |
| `is_monsoon_season` | boolean | — | month in `[MONSOON_SEASON_START_MONTH, MONSOON_SEASON_END_MONTH]` (default Jun–Dec, which covers the SW and NE monsoons) | never |
| `updated_at` | timestamptz | — | last upsert time (not returned by `load_features`) | never |

## Things Segment 2 must know

1. **Look-ahead in climate indices.** The values are stored at their *valid* time, not their
   *publication* time:
   * ONI for month *m* is a 3-month mean centred on *m*, so it uses month *m+1* and is published about a week after that month ends.
   * DMI for month *m* is known only after *m* ends.
   * RMM/ROMI are known about a day later.

   For honest hindcasts, build lagged predictors from `*_lag30`, or shift further (for example, use ONI at `date − 60`).
2. **MJO source switch.** BoM stopped updating RMM in Feb 2024. From 2024-02-25 onwards
   `mjo_source = 'romi'`. Over 1991–2024 the rotated ROMI correlates about 0.73 with RMM per component,
   and 94% of strong-MJO days (amplitude > 1) fall within ±1 phase. Consider `mjo_source`
   as a feature, or train on ROMI-only data if consistency matters more (`MJO_SOURCE_MODE=romi_only`).
3. **Provisional recent rainfall.** Rows whose `rainfall_daily.source = 'imd_realtime'` use IMD's
   provisional real-time grid. The `daily` job re-fetches the last 10 days, so the values can change.
   When IMD publishes the final yearly file, re-run `rainfall` and `aggregate` for that year.
4. **Climatology base period** is 1991–2020 (`CLIM_START_YEAR/CLIM_END_YEAR`), pooling ±15 days
   around each day of year. Anomalies for dates inside the base period are therefore not fully out-of-sample.
5. **First rows.** Rolling features are NULL for the first 2/6/13/29 days of the series.
   `consecutive_dry_days` on the first dry run of the series counts only from the series start.
6. Units are SI/mm as listed. Floats are rounded to 4 decimals.

## Example row

Computed from real IMD 2025 data for a test block in Thanjavur district during the NE monsoon
(values rounded here; ERA5 not configured). This example's anomalies use a 2024–2025 test
climatology, not 1991–2020, so they are illustrative only:

```json
{
  "region_id": 1, "date": "2025-10-20",
  "rain_mm": 22.62, "rain_sum_3d": 65.85, "rain_sum_7d": 112.5, "rain_sum_14d": 141.57, "rain_sum_30d": 207.45,
  "anomaly_7d_mm": 58.44, "anomaly_7d_pct": 208.09, "anomaly_30d_mm": 29.49, "anomaly_30d_pct": 116.57,
  "consecutive_dry_days": 0, "wet_days_last_7": 6, "wet_days_last_14": 9, "max_1day_rain_last_7": 36.43,
  "doy_sin": -0.95, "doy_cos": 0.3123,
  "oni": -0.57, "oni_lag30": -0.43, "dmi": -0.448, "dmi_lag30": -0.467,
  "rmm1": 0.313, "rmm2": -1.3864, "mjo_phase": 3, "mjo_amplitude": 1.4213, "mjo_source": "romi",
  "u850": null, "v850": null, "tcwv": null, "olr": null,
  "is_monsoon_season": true
}
```

## Change policy

Adding columns is backwards-compatible and needs only a note here. Renaming or removing a column,
or changing a unit or NULL rule, needs a new contract version and sign-off from Segment 2.
