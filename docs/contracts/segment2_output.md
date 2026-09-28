# Contract: Segment 2 → Segment 3 (`forecasts`, `model_skill`)

**Owner:** Segment 2 (ML prediction engine) · **Consumer:** Segment 3 (hazards / advisories) ·
**Version:** 1.0 (2026-09-29)

Segment 3 reads forecasts through the helper:

```python
from ml import load_forecasts

df = load_forecasts(issue_date="2026-09-28")          # all districts, lead weeks 1–4
df = load_forecasts(region_ids=[12], issue_date=None)  # every stored issue date for one district
```

`load_forecasts` returns a `pandas.DataFrame` sorted by `(region_id, issue_date, lead_week)` with
fixed dtypes: `region_id`, `lead_week` int64; `issue_date`, `week_start`, `week_end`
datetime64[ns]; probabilities and quantiles float64; `confidence`, `model_version` string;
`created_at` timezone-aware timestamp.

## Grain and keys

* One row per **district × issue date × lead week**. Primary key `(region_id, issue_date, lead_week)`.
* `region_id` → `regions.id` (same ids as `features_daily`; 38 Tamil Nadu districts today).
* Issue dates are **Jun 1 – Dec 31** only. The models were trained for those dates and refuse others.
* Writes are idempotent upserts. Re-running a date overwrites its rows and refreshes `created_at`.
* **Information cut-off:** a forecast issued on *t* uses rainfall up to and including IMD day
  *t−1* (08:30 IST *t−1* → 08:30 IST *t*), MJO of *t−1*, and only ONI/DMI months already
  published on *t*. Rain on IMD day *t* itself is in neither the inputs nor the target weeks.

## Columns (`forecasts`)

| Column | Type | Unit | Definition |
| --- | --- | --- | --- |
| `region_id` | int | — | district (FK `regions.id`) |
| `issue_date` | date | — | *t*, the day the forecast is issued |
| `lead_week` | smallint | 1–4 | week *k* after *t* |
| `week_start` | date | — | *t* + 7(*k*−1) + 1 |
| `week_end` | date | — | *t* + 7*k* (7 days, both ends inclusive) |
| `p_below` / `p_normal` / `p_above` | real | probability | calibrated tercile probabilities of the week's total vs that district's normal for that week (below p33 / between / above p67 of 1991–2025 weekly totals, ±15-day window). **They sum to 1** (4-decimal rounding is absorbed by `p_normal`). |
| `q10_mm` / `q50_mm` / `q90_mm` | real | mm per week | 10th / 50th / 90th percentile of the week's total rainfall. Never crossing (q10 ≤ q50 ≤ q90). Not calibrated; see `coverage_80` in `model_skill`. |
| `p_heavy` | real | probability | P(at least one day in the week has ≥ 64.5 mm), calibrated |
| `p_dry_week` | real | probability | P(all 7 days < 2.5 mm), calibrated |
| `confidence` | text | High / Medium / Low | see below |
| `model_version` | text | — | e.g. `s2-lgbm-20260929-0306`; artifacts and model card in `backend/ml/artifacts/<model_version>/` |
| `created_at` | timestamptz | — | time the row was last written |

All probabilities lie in [0.001, 0.999]. A calibrated forecast is never exactly 0 or 1.

## Confidence level

One level per row, from the **validated skill of that lead week in that season** and the
**sharpness** of the row:

* `skill` = the **lower 5% bound** of the tercile RPSS vs climatology, from a year-block bootstrap
  (test years 2011–2025 resampled with replacement, 1000 draws). Seasons: **SWM** = issue month
  Jun–Sep, **NEM** = Oct–Dec.
* `sharp` = max(`p_below`, `p_normal`, `p_above`).

| Level | Rule |
| --- | --- |
| **High** | skill ≥ 0.10 **and** sharp ≥ 0.50 |
| **Medium** | skill ≥ 0.10 and sharp < 0.50, **or** 0.03 ≤ skill < 0.10 and sharp ≥ 0.45 |
| **Low** | everything else. Always Low when skill < 0.03. |

The thresholds were fixed before validation (`backend/ml/config.py`). Using the CI lower bound
means a lead week only gets higher confidence when its skill is positive with high confidence,
not just on average. Which levels each lead/season can reach for the current model is listed in
its model card.

## `model_skill` (validation results)

One row per `(target, lead_week, season, metric, model, model_version)`:

| Column | Meaning |
| --- | --- |
| `target` | `tercile`, `heavy_day`, `dry_week`, `weekly_total_mm` |
| `lead_week` | 1–4 |
| `season` | `SWM`, `NEM`, `ALL` (by issue month) |
| `metric` | `rpss`, `rps` (tercile) · `bss`, `auc`, `brier`, `base_rate` (binary) · `qss`, `crps_approx`, `pinball_q10/q50/q90`, `coverage_80` (quantiles) |
| `model` | `lgbm` (calibrated, what `forecasts` contains), `lgbm_uncalibrated`, `persistence`, `climatology`, `observed` |
| `value`, `ci_low`, `ci_high` | score and 5–95% year-block bootstrap CI (CIs for skill scores and AUC) |
| `n_samples`, `n_years` | rows and test years scored |

Skill scores are relative to climatology: > 0 is better than climatology, 0 is no better, < 0 is worse.
`crps_approx` is 2 × the mean pinball loss over the three quantiles, a coarse approximation of CRPS.

## Example rows

_Filled from the 2026-09-28 run, see below._

## How Segment 3 should use this

* Treat `p_*` as probabilities, not categories. For example, a dry-spell alert could require
  `p_dry_week` ≥ some threshold **and** `confidence` ≠ `Low`.
* Onset / revival logic can combine consecutive lead weeks (`p_above` rising, `p_dry_week` falling).
* Check `model_skill` before trusting a lead week. Lead weeks 3–4 are close to climatology.

## Change policy

Adding columns is backwards-compatible and needs only a note here. Renaming or removing a
column, or changing a unit, a probability definition or the confidence rule, needs a new
contract version and sign-off from Segment 3.
