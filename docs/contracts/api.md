# Contract: AgriVarsha API (Segment 5 → frontend)

**Owner:** backend (Segments 3, 4, 5, 7) · **Consumer:** frontend (Vite) · **Version:** 1.0 (2026-09-29)

Base URL `http://127.0.0.1:8000` (run `uvicorn app.main:app --reload` from `backend/`).
Interactive OpenAPI docs: `/docs` · schema: `/openapi.json`. CORS allows the Vite dev server
(`http://localhost:5173`) and any `localhost` port.

Every example below is a **real response** captured from this build (lists trimmed to two
items, shown as `"…"`).

## Conventions

* JSON everywhere except `POST /api/chat` (Server-Sent Events).
* Dates are `YYYY-MM-DD`; timestamps are ISO-8601 with timezone.
* Probabilities are fractions in [0, 1] (`0.72` = 72%). Rain is mm (weekly totals for
  `q10_mm/q50_mm/q90_mm`, daily for rainfall series).
* **District keys**: any endpoint taking `{district}` accepts the slug (`chennai`,
  `the-nilgiris`), the name (`Chennai`), the code (`tn/chennai`) or the numeric id.
* **Context**: data endpoints accept `?date=` (the forecast *issue date*). Without it the
  backend uses the active scenario's demo date, else today. Responses carry a `context`
  object; show it in the UI:

  | field | meaning |
  | --- | --- |
  | `issue_date` | date the forecast is issued for |
  | `forecast_source` | `mock` or `real` |
  | `scenario` | active demo scenario or `none` |
  | `forecast_issue_date` | issue date of the forecast actually used (real mode falls back to the latest Segment 2 run ≤ `issue_date`) |
  | `model_version` | `mock-gen-v1` or e.g. `s2-lgbm-20260929-0304` |
  | `observed_through` | last day of observed rain used by the hazard rules |
  | `note` | human-readable caveat (mock / stale forecast), may be `null` |
  | `hazard_run_id` | internal id of the hazard computation |

* **Severity** (hazards and advisories): `info` < `watch` < `warning`. Suggested colours:
  info = blue, watch = amber, warning = red, none = grey.
* **Hazard types**: `onset`, `false_onset`, `active_phase`, `dry_spell` (subtype `7d`/`14d`),
  `heavy_rain` (subtype `heavy`/`very_heavy`), `revival`. `lead_week` 0 = already observed,
  1–4 = forecast week. `basis` is `observed`, `forecast` or `observed+forecast`.
* **Advisory status**: `draft` → `approved` → `sent`; `draft|approved` → `rejected`;
  editing sends an advisory back to `draft`; `superseded` = a draft whose hazard vanished.
* **Errors**: `{"detail": "..."}` with 404 (unknown id/district, no forecast), 409 (invalid
  status transition, broadcasting a non-approved advisory), 422 (validation).


```http
GET /api/forecast/atlantis
```
Response `404`:
```json
{
  "detail": "Unknown district 'atlantis'. Use a name, slug (e.g. 'chennai') or id from GET /api/districts."
}
```


## What is mocked

| Data | Source | Switch |
| --- | --- | --- |
| Districts, boundaries, observed rainfall, normals, crop calendar, pipeline runs, model skill | **real** (Segments 1–2) | — |
| Forecasts | mock generator (default) or real Segment 2 | `GET/POST /api/settings/forecast-source` |
| Farmer counts (`farmers_targeted`, recipients) | mock | `FARMER_COUNT_SOURCE` |
| SMS/WhatsApp/IVR delivery and `simulated=true` feedback | simulated | `DELIVERY_MODE` |
| Plain-language text (`simple_text_en`), chat | templates, Claude if `LLM_API_KEY` set | `LLM_API_KEY` |

---

## System

### GET /api/health
Liveness, active switches and the default date.

```http
GET /api/health
```
Response `200`:
```json
{
  "status": "ok",
  "demo_mode": true,
  "forecast_source": "mock",
  "scenario": null,
  "llm_enabled": false,
  "today": "2026-09-29",
  "default_date": "2026-09-29",
  "tables": [
    "feedback",
    "broadcast_channels",
    "…"
  ]
}
```


### GET /api/context?date=
The context other endpoints will use (computes hazards/advisories for it if needed).

```http
GET /api/context?date=2026-09-29
```
Response `200`:
```json
{
  "issue_date": "2026-09-29",
  "forecast_source": "mock",
  "scenario": "none",
  "forecast_issue_date": "2026-09-29",
  "model_version": "mock-gen-v1",
  "observed_through": "2026-09-28",
  "note": "MOCK forecasts (deterministic generator)",
  "hazard_run_id": 1
}
```


---

## Map and forecasts

### GET /api/districts?date=&tolerance=0.005
GeoJSON `FeatureCollection` of the 38 districts (Segment 1 boundaries). `tolerance` is the
simplification in degrees (0 = full detail; 0.005 default; 0.02 is plenty for a state map).
`properties.risk` gives each district's worst current hazard (`severity: "none"` when calm).
Feature `id` = district id.

```http
GET /api/districts?date=2026-09-29&tolerance=0.05
```
Response `200`:
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 1,
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              [
                79.46028,
                11.1505
              ],
              [
                79.5015,
                11.31219
              ],
              "…"
            ]
          ]
        ]
      },
      "properties": {
        "id": 1,
        "code": "tn/ariyalur",
        "slug": "ariyalur",
        "name": "Ariyalur",
        "area_km2": 1985.7,
        "centroid": [
          79.2434,
          11.1624
        ],
        "coastal": false,
        "risk": {
          "severity": "info",
          "top_hazard": "onset",
          "top_probability": 1.0,
          "hazard_types": [
            "onset"
          ]
        }
      }
    }
  ],
  "context": {
    "issue_date": "2026-09-29",
    "forecast_source": "mock",
    "scenario": "none",
    "forecast_issue_date": "2026-09-29",
    "model_version": "mock-gen-v1",
    "observed_through": "2026-09-28",
    "note": "MOCK forecasts (deterministic generator)",
    "hazard_run_id": 1
  }
}
```


### GET /api/forecast/{district}?date=
Four lead weeks (Segment 2 schema) plus the district's hazards, crop stages and recent rain.
Forecast row fields: `lead_week`, `week_start`, `week_end` (7 days inclusive), `p_below`,
`p_normal`, `p_above` (sum to 1), `q10_mm ≤ q50_mm ≤ q90_mm` (weekly total),
`p_heavy` (≥ 1 day ≥ 64.5 mm), `p_dry_week` (all 7 days < 2.5 mm), `confidence`
(High/Medium/Low), `model_version`.

```http
GET /api/forecast/madurai?date=2026-09-29
```
Response `200`:
```json
{
  "context": {
    "issue_date": "2026-09-29",
    "forecast_source": "mock",
    "scenario": "none",
    "forecast_issue_date": "2026-09-29",
    "model_version": "mock-gen-v1",
    "observed_through": "2026-09-28",
    "note": "MOCK forecasts (deterministic generator)",
    "hazard_run_id": 1
  },
  "district": {
    "id": 14,
    "code": "tn/madurai",
    "slug": "madurai",
    "name": "Madurai",
    "area_km2": 3771.000850614114,
    "lon": 78.00760399765059,
    "lat": 9.921103669455382,
    "coastal": false
  },
  "forecast": [
    {
      "lead_week": 1,
      "week_start": "2026-09-30",
      "week_end": "2026-10-06",
      "p_below": 0.1206,
      "p_normal": 0.2936,
      "p_above": 0.5858,
      "q10_mm": 1.85,
      "q50_mm": 41.42,
      "q90_mm": 125.75,
      "p_heavy": 0.0548,
      "p_dry_week": 0.2277,
      "confidence": "High",
      "model_version": "mock-gen-v1"
    },
    {
      "lead_week": 2,
      "week_start": "2026-10-07",
      "week_end": "2026-10-13",
      "p_below": 0.4148,
      "p_normal": 0.3473,
      "p_above": 0.2379,
      "q10_mm": 1.43,
      "q50_mm": 32.26,
      "q90_mm": 92.72,
      "p_heavy": 0.0252,
      "p_dry_week": 0.2609,
      "confidence": "Low",
      "model_version": "mock-gen-v1"
    },
    "…"
  ],
  "hazards": [
    {
      "id": 5,
      "region_id": 14,
      "district": "Madurai",
      "hazard_type": "false_onset",
      "subtype": null,
      "severity": "watch",
      "probability": 1.0,
      "lead_week": 0,
      "window_start": "2026-09-20",
      "window_end": "2026-09-28",
      "confidence": "High",
      "basis": "observed",
      "why": "False onset under way: 42.0 mm fell 20 Sep–21 Sep, and it has now been dry (< 2.5 mm/day) for 7 days since 22 Sep. Relief likely: 59% chance of ≥ 20 mm in week 1.",
      "evidence": {
        "onset": {
          "end": "2026-09-21",
          "days": 2,
          "start": "2026-09-20",
          "total_mm": 42.0
        },
        "dry_run_days": 7,
        "p_rain_week1": 0.5937,
        "max_p_dry_weeks_1_3": 0.2609
      }
    },
    {
      "id": 26,
      "region_id": 14,
      "district": "Madurai",
      "hazard_type": "dry_spell",
      "subtype": "7d",
      "severity": "info",
      "probability": 1.0,
      "lead_week": 0,
      "window_start": "2026-09-22",
      "window_end": "2026-09-28",
      "confidence": "High",
      "basis": "observed",
      "why": "7 consecutive dry days observed (< 2.5 mm/day) up to 28 Sep. Likely to end: 59% chance of ≥ 20 mm in week 1.",
      "evidence": {
        "p_rain_week1": 0.5937,
        "observed_dry_days": 7
      }
    },
    "…"
  ],
  "crop_stages": [
    {
      "crop": "cotton",
      "season": "rainfed_winter",
      "stage": "emergence",
      "stage_group": "establishment",
      "days_after_sowing": 7,
      "typical_sowing_date": "2026-09-22",
      "sowing_window": [
        "2026-08-31",
        "2026-10-14"
      ],
      "calendar_district": "ALL",
      "is_sample": true
    },
    {
      "crop": "groundnut",
      "season": "kharif",
      "stage": "pod_development",
      "stage_group": "grain_fill",
      "days_after_sowing": 84,
      "typical_sowing_date": "2026-07-07",
      "sowing_window": [
        "2026-06-14",
        "2026-07-30"
      ],
      "calendar_district": "ALL",
      "is_sample": true
    },
    "…"
  ],
  "observed": {
    "through": "2026-09-28",
    "last_7_days_mm": 1.6,
    "last_30_days_mm": 135.7,
    "source": "Segment 1 rainfall_daily (IMD gridded, area-weighted)"
  }
}
```


### GET /api/forecasts?date=&lead_week=
All districts' forecast rows (for choropleths). `lead_week` optional (1–4).

```http
GET /api/forecasts?date=2026-09-29&lead_week=1
```
Response `200`:
```json
{
  "context": {
    "issue_date": "2026-09-29",
    "forecast_source": "mock",
    "scenario": "none",
    "forecast_issue_date": "2026-09-29",
    "model_version": "mock-gen-v1",
    "observed_through": "2026-09-28",
    "note": "MOCK forecasts (deterministic generator)",
    "hazard_run_id": 1
  },
  "count": 38,
  "forecasts": [
    {
      "region_id": 1,
      "issue_date": "2026-09-29",
      "lead_week": 1,
      "week_start": "2026-09-30",
      "week_end": "2026-10-06",
      "p_below": 0.3464,
      "p_normal": 0.3553,
      "p_above": 0.2983,
      "q10_mm": 0.99,
      "q50_mm": 27.36,
      "q90_mm": 90.04,
      "p_heavy": 0.0234,
      "p_dry_week": 0.2952,
      "confidence": "Medium",
      "model_version": "mock-gen-v1",
      "district": "Ariyalur"
    },
    {
      "region_id": 2,
      "issue_date": "2026-09-29",
      "lead_week": 1,
      "week_start": "2026-09-30",
      "week_end": "2026-10-06",
      "p_below": 0.8799,
      "p_normal": 0.109,
      "p_above": 0.0111,
      "q10_mm": 0.55,
      "q50_mm": 11.94,
      "q90_mm": 34.07,
      "p_heavy": 0.0019,
      "p_dry_week": 0.3869,
      "confidence": "High",
      "model_version": "mock-gen-v1",
      "district": "Chengalputtu"
    },
    "…"
  ]
}
```


### GET /api/hazards?date=&district=&type=&severity=&min_severity=
Hazards, most severe first. Each has `district`, `hazard_type`, `subtype`, `severity`,
`probability`, `lead_week`, `window_start/window_end`, `confidence`, `basis`, a `why`
sentence quoting the numbers, and machine-readable `evidence`.

```http
GET /api/hazards?date=2026-09-29&min_severity=watch
```
Response `200`:
```json
{
  "context": {
    "issue_date": "2026-09-29",
    "forecast_source": "mock",
    "scenario": "none",
    "forecast_issue_date": "2026-09-29",
    "model_version": "mock-gen-v1",
    "observed_through": "2026-09-28",
    "note": "MOCK forecasts (deterministic generator)",
    "hazard_run_id": 1
  },
  "count": 14,
  "hazards": [
    {
      "id": 1,
      "region_id": 4,
      "district": "Coimbatore",
      "hazard_type": "false_onset",
      "subtype": null,
      "severity": "watch",
      "probability": 1.0,
      "lead_week": 0,
      "window_start": "2026-09-15",
      "window_end": "2026-09-28",
      "confidence": "High",
      "basis": "observed",
      "why": "False onset under way: 27.3 mm fell 15 Sep–17 Sep, and it has now been dry (< 2.5 mm/day) for 7 days since 22 Sep. Relief likely: 62% chance of ≥ 20 mm in week 1.",
      "evidence": {
        "onset": {
          "end": "2026-09-17",
          "days": 3,
          "start": "2026-09-15",
          "total_mm": 27.3
        },
        "dry_run_days": 7,
        "p_rain_week1": 0.6236,
        "max_p_dry_weeks_1_3": 0.2789
      }
    },
    {
      "id": 2,
      "region_id": 7,
      "district": "Dindigul",
      "hazard_type": "false_onset",
      "subtype": null,
      "severity": "watch",
      "probability": 1.0,
      "lead_week": 0,
      "window_start": "2026-09-20",
      "window_end": "2026-09-28",
      "confidence": "High",
      "basis": "observed",
      "why": "False onset under way: 42.6 mm fell 20 Sep–21 Sep, and it has now been dry (< 2.5 mm/day) for 7 days since 22 Sep. Relief likely: 64% chance of ≥ 20 mm in week 1.",
      "evidence": {
        "onset": {
          "end": "2026-09-21",
          "days": 2,
          "start": "2026-09-20",
          "total_mm": 42.6
        },
        "dry_run_days": 7,
        "p_rain_week1": 0.6381,
        "max_p_dry_weeks_1_3": 0.2645
      }
    },
    "…"
  ]
}
```


### GET /api/overview?date=
Dashboard KPIs: district alert counts, hazards by type, advisory counts by status (drafts =
pending review), farmers (mock), delivery funnel totals, feedback, week-1 forecast summary,
data freshness, and the top risk districts.

```http
GET /api/overview?date=2026-09-29
```
Response `200`:
```json
{
  "context": {
    "issue_date": "2026-09-29",
    "forecast_source": "mock",
    "scenario": "none",
    "forecast_issue_date": "2026-09-29",
    "model_version": "mock-gen-v1",
    "observed_through": "2026-09-28",
    "note": "MOCK forecasts (deterministic generator)",
    "hazard_run_id": 1
  },
  "districts": {
    "total": 38,
    "with_alerts": 14,
    "warning": 0,
    "watch": 14,
    "info_only": 22
  },
  "hazards": {
    "total": 65,
    "by_type": {
      "false_onset": {
        "districts": 10,
        "info": 0,
        "watch": 10,
        "warning": 0
      },
      "heavy_rain": {
        "districts": 4,
        "info": 0,
        "watch": 4,
        "warning": 0
      },
      "onset": {
        "districts": 25,
        "info": 25,
        "watch": 0,
        "warning": 0
      },
      "dry_spell": {
        "districts": 13,
        "info": 13,
        "watch": 0,
        "warning": 0
      },
      "revival": {
        "districts": 13,
        "info": 13,
        "watch": 0,
        "warning": 0
      }
    }
  },
  "advisories": {
    "by_status": {
      "draft": 123,
      "approved": 0,
      "rejected": 0,
      "sent": 0,
      "superseded": 0
    },
    "pending_review": 123,
    "by_severity": {
      "info": 53,
      "watch": 70
    },
    "farmers_covered_by_sent": 0
  },
  "farmers": {
    "registered_total": 4682993,
    "in_alert_districts": 1565940,
    "source": "mock"
  },
  "delivery": {
    "broadcasts": 0,
    "recipients": 0,
    "sent": 0,
    "delivered": 0,
    "read": 0,
    "delivery_rate": null,
    "read_rate": null,
    "mode": "simulated"
  },
  "feedback": {
    "total": 0,
    "positive_rate": null
  },
  "forecast_week1": {
    "mean_q50_mm": 36.0,
    "districts_above_normal_favoured": 23,
    "districts_below_normal_favoured": 10,
    "confidence_counts": {
      "Low": 89,
      "High": 33,
      "Medium": 30
    }
  },
  "data_freshness": {
    "last_rainfall_date": "2026-09-28",
    "rainfall_lag_days": 1,
    "observed_through": "2026-09-28"
  },
  "top_risk_districts": [
    {
      "region_id": 4,
      "district": "Coimbatore",
      "severity": "watch",
      "top_hazard": "false_onset",
      "top_probability": 1.0,
      "hazard_types": [
        "false_onset",
        "dry_spell",
        "…"
      ]
    },
    {
      "region_id": 7,
      "district": "Dindigul",
      "severity": "watch",
      "top_hazard": "false_onset",
      "top_probability": 1.0,
      "hazard_types": [
        "false_onset",
        "dry_spell",
        "…"
      ]
    },
    "…"
  ]
}
```


### GET /api/rainfall/{district}?days=30&end=
**Real** observed daily rain (Segment 1) with the 1991–2020 daily normal. `days` 1–366;
`end` defaults to the latest day in the database.

```http
GET /api/rainfall/chennai?days=5
```
Response `200`:
```json
{
  "district": {
    "id": 3,
    "name": "Chennai",
    "slug": "chennai"
  },
  "days": 5,
  "start": "2026-09-24",
  "end": "2026-09-28",
  "total_mm": 0.2,
  "normal_mm": 22.4,
  "percent_of_normal": 1.1,
  "wet_days": 0,
  "max_day_mm": 0.2,
  "source": "Segment 1 rainfall_daily (IMD 0.25° gridded, area-weighted); normal = climatology_daily.rain_mean 1991–2020",
  "series": [
    {
      "date": "2026-09-24",
      "rain_mm": 0.0,
      "source": "imd_realtime",
      "rain_sum_7d": 5.636,
      "anomaly_7d_pct": 18.8816,
      "consecutive_dry_days": 2,
      "normal_mm": 4.3393
    },
    {
      "date": "2026-09-25",
      "rain_mm": 0.0,
      "source": "imd_realtime",
      "rain_sum_7d": 5.636,
      "anomaly_7d_pct": 18.7414,
      "consecutive_dry_days": 3,
      "normal_mm": 4.4125
    },
    "…"
  ]
}
```


### GET /api/crop-calendar?district=&date=
The Segment 1 crop calendar (SAMPLE data); with `district`, also the crop stages on the
issue date (`stage: "sowing"` = inside the sowing window, before its middle).

```http
GET /api/crop-calendar?district=thanjavur&date=2026-09-29
```
Response `200`:
```json
{
  "calendar": [
    {
      "crop": "cotton",
      "season": "rainfed_winter",
      "district": "ALL",
      "sowing_start_doy": 244,
      "sowing_end_doy": 288,
      "stage_name": "emergence",
      "stage_start_day": 0,
      "stage_end_day": 20,
      "is_sample": true
    },
    {
      "crop": "cotton",
      "season": "rainfed_winter",
      "district": "ALL",
      "sowing_start_doy": 244,
      "sowing_end_doy": 288,
      "stage_name": "squaring",
      "stage_start_day": 21,
      "stage_end_day": 50,
      "is_sample": true
    },
    "…"
  ],
  "stages": [
    {
      "crop": "cotton",
      "season": "rainfed_winter",
      "stage": "emergence",
      "stage_group": "establishment",
      "days_after_sowing": 7,
      "typical_sowing_date": "2026-09-22",
      "sowing_window": [
        "2026-08-31",
        "2026-10-14"
      ],
      "calendar_district": "ALL",
      "is_sample": true
    },
    {
      "crop": "groundnut",
      "season": "kharif",
      "stage": "pod_development",
      "stage_group": "grain_fill",
      "days_after_sowing": 84,
      "typical_sowing_date": "2026-07-07",
      "sowing_window": [
        "2026-06-14",
        "2026-07-30"
      ],
      "calendar_district": "ALL",
      "is_sample": true
    },
    "…"
  ],
  "issue_date": "2026-09-29"
}
```


---

## Advisories (review queue)

Advisories are drafted automatically whenever the hazards of a context change: one per
district × crop (the most severe hazard wins). Text is English + Tamil (`tamil_reviewed`
is `false` until a reviewer sets it), with a `source_note` (SAMPLE guidance) and the
`hazard_why` that triggered it. `simple_text_en` is the LLM rewording (null without a key;
`rephrased_by` = `template` or `llm:<model>`).

### GET /api/advisories?status=&date=&district=&crop=&severity=&hazard_type=&all_contexts=false&limit=100&offset=0
Default: the current context, superseded hidden. Sorted warning → watch → info, then by
farmers reached. `status_counts` covers the same filters regardless of `status`.

```http
GET /api/advisories?date=2026-09-29&status=draft&limit=2
```
Response `200`:
```json
{
  "context": {
    "issue_date": "2026-09-29",
    "forecast_source": "mock",
    "scenario": "none",
    "forecast_issue_date": "2026-09-29",
    "model_version": "mock-gen-v1",
    "observed_through": "2026-09-28",
    "note": "MOCK forecasts (deterministic generator)",
    "hazard_run_id": 1
  },
  "total": 123,
  "limit": 2,
  "offset": 0,
  "status_counts": {
    "draft": 123
  },
  "advisories": [
    {
      "id": 14,
      "issue_date": "2026-09-29",
      "forecast_source": "mock",
      "scenario": "none",
      "region_id": 8,
      "district": "Erode",
      "crop": "paddy",
      "season": "samba",
      "stage": "tillering",
      "stage_group": "vegetative",
      "hazard_type": "false_onset",
      "hazard_subtype": null,
      "hazard_probability": 1.0,
      "hazard_lead_week": 0,
      "hazard_confidence": "High",
      "hazard_why": "False onset under way: 20.5 mm fell 20 Sep–21 Sep, and it has now been dry (< 2.5 mm/day) for 7 days since 22 Sep. Relief likely: 64% chance of ≥ 20 mm in week 1.",
      "rule_id": "FO-ANY",
      "severity": "watch",
      "title_en": "Rain not yet steady",
      "title_ta": "மழை இன்னும் நிலையாகவில்லை",
      "text_en": "Erode: the monsoon rain is not steady yet; a high chance of a dry spell in the coming days.",
      "text_ta": "ஈரோடு: பருவமழை இன்னும் நிலையாகவில்லை; வரும் நாட்களில் வறட்சி ஏற்பட அதிக வாய்ப்பு உள்ளது.",
      "action_en": "Conserve soil moisture: mulch and avoid deep ploughing.",
      "action_ta": "மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.",
      "simple_text_en": null,
      "rephrased_by": "template",
      "tamil_reviewed": false,
      "source_note": "Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: SAMPLE, not yet validated by agronomists.",
      "farmers_targeted": 69970,
      "status": "draft",
      "edited": false,
      "reviewer": null,
      "review_note": null,
      "created_at": "2026-09-29T14:56:22.726912+05:30",
      "updated_at": "2026-09-29T14:56:22.726912+05:30",
      "approved_at": null
    },
    {
      "id": 54,
      "issue_date": "2026-09-29",
      "forecast_source": "mock",
      "scenario": "none",
      "region_id": 10,
      "district": "Kancheepuram",
      "crop": "paddy",
      "season": "samba",
      "stage": "tillering",
      "stage_group": "vegetative",
      "hazard_type": "heavy_rain",
      "hazard_subtype": "very_heavy",
      "hazard_probability": 0.5377,
      "hazard_lead_week": 4,
      "hazard_confidence": "Low",
      "hazard_why": "54% chance of at least one day ≥ 64.5 mm in week 4 (21 Oct–27 Oct); week total median 84 mm, up to 344 mm (90th percentile).",
      "rule_id": "HR-PADDY",
      "severity": "watch",
      "title_en": "Heavy rain: drain paddy fields",
      "title_ta": "கனமழை: நெல் வயலில் நீரை வடிக்கவும்",
      "text_en": "Kancheepuram: 54% chance of heavy rain (≥ 64.5 mm in a day) in 21 Oct–27 Oct during tillering.",
      "text_ta": "காஞ்சிபுரம்: தூர் கட்டும் பருவத்தில் 21 அக்.–27 அக். காலத்தில் கனமழை (ஒரு நாளில் 64.5 மி.மீக்கு மேல்) பெய்ய 54% வாய்ப்பு.",
      "action_en": "Strengthen bunds, keep drainage open, and postpone urea top-dressing and sprays until the rain stops.",
      "action_ta": "வரப்புகளை வலுப்படுத்தவும், வடிகாலைத் திறந்து வைக்கவும், மழை நிற்கும் வரை யூரியா மேலுரம் மற்றும் தெளிப்புகளைத் தள்ளிப்போடவும்.",
      "simple_text_en": null,
      "rephrased_by": "template",
      "tamil_reviewed": false,
      "source_note": "Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: SAMPLE, not yet validated by agronomists.",
      "farmers_targeted": 68684,
      "status": "draft",
      "edited": false,
      "reviewer": null,
      "review_note": null,
      "created_at": "2026-09-29T14:56:22.726912+05:30",
      "updated_at": "2026-09-29T14:56:22.726912+05:30",
      "approved_at": null
    }
  ]
}
```


### GET /api/advisories/{id}
One advisory with its audit trail (`events`), per-channel message previews
(`channel_preview`) and its broadcasts.

```http
GET /api/advisories/14
```
Response `200`:
```json
{
  "id": 14,
  "issue_date": "2026-09-29",
  "forecast_source": "mock",
  "scenario": "none",
  "dedupe_key": "2026-09-29|mock|none|8|paddy|samba|false_onset",
  "region_id": 8,
  "district": "Erode",
  "crop": "paddy",
  "season": "samba",
  "stage": "tillering",
  "stage_group": "vegetative",
  "hazard_type": "false_onset",
  "hazard_subtype": null,
  "hazard_probability": 1.0,
  "hazard_lead_week": 0,
  "hazard_confidence": "High",
  "hazard_why": "False onset under way: 20.5 mm fell 20 Sep–21 Sep, and it has now been dry (< 2.5 mm/day) for 7 days since 22 Sep. Relief likely: 64% chance of ≥ 20 mm in week 1.",
  "rule_id": "FO-ANY",
  "severity": "watch",
  "title_en": "Rain not yet steady",
  "title_ta": "மழை இன்னும் நிலையாகவில்லை",
  "text_en": "Erode: the monsoon rain is not steady yet; a high chance of a dry spell in the coming days.",
  "text_ta": "ஈரோடு: பருவமழை இன்னும் நிலையாகவில்லை; வரும் நாட்களில் வறட்சி ஏற்பட அதிக வாய்ப்பு உள்ளது.",
  "action_en": "Conserve soil moisture: mulch and avoid deep ploughing.",
  "action_ta": "மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.",
  "simple_text_en": null,
  "rephrased_by": "template",
  "tamil_reviewed": false,
  "source_note": "Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: SAMPLE, not yet validated by agronomists.",
  "farmers_targeted": 69970,
  "status": "draft",
  "edited": false,
  "reviewer": null,
  "review_note": null,
  "created_at": "2026-09-29T14:56:22.726912+05:30",
  "updated_at": "2026-09-29T14:56:22.726912+05:30",
  "approved_at": null,
  "events": [
    {
      "action": "drafted",
      "actor": "system",
      "note": null,
      "payload": {
        "rule_id": "FO-ANY",
        "hazard_run_id": 1
      },
      "at": "2026-09-29T14:56:22.726912+05:30"
    }
  ],
  "channel_preview": {
    "app": {
      "en": "Rain not yet steady\nErode: the monsoon rain is not steady yet; a high chance of a dry spell in the coming days. Conserve soil moisture: mulch and avoid deep ploughing.",
      "ta": "மழை இன்னும் நிலையாகவில்லை\nஈரோடு: பருவமழை இன்னும் நிலையாகவில்லை; வரும் நாட்களில் வறட்சி ஏற்பட அதிக வாய்ப்பு உள்ளது. மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.",
      "chars_en": 167,
      "chars_ta": 178
    },
    "sms": {
      "en": "AgriVarsha Erode: Rain not yet steady. Conserve soil moisture: mulch and avoid deep ploughing.",
      "ta": "அக்ரிவர்ஷா ஈரோடு: மழை இன்னும் நிலையாகவில்லை. மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.",
      "chars_en": 94,
      "chars_ta": 108,
      "segments_en": 1,
      "segments_ta": 2
    },
    "whatsapp": {
      "en": "🌦️ *AgriVarsha advisory: Erode*\n*Rain not yet steady*\n\nErode: the monsoon rain is not steady yet; a high chance of a dry spell in the coming days.\n\n✅ *What to do:* Conserve soil moisture: mulch and avoid deep ploughing.\n\n_Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: SAMPLE, not yet validated by agronomists._\nWas this useful? Reply 👍 or 👎",
      "ta": "🌦️ *அக்ரிவர்ஷா ஆலோசனை: ஈரோடு*\n*மழை இன்னும் நிலையாகவில்லை*\n\nஈரோடு: பருவமழை இன்னும் நிலையாகவில்லை; வரும் நாட்களில் வறட்சி ஏற்பட அதிக வாய்ப்பு உள்ளது.\n\n✅ *செய்ய வேண்டியது:* மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.\n\nஇது பயனுள்ளதா? 👍 அல்லது 👎 என பதிலளிக்கவும்",
      "chars_en": 373,
      "chars_ta": 277
    },
    "ivr": {
      "en": "Vanakkam. This is the AgriVarsha weather advisory for Erode district. Erode: the monsoon rain is not steady yet; a high chance of a dry spell in the coming days. Conserve soil moisture: mulch and avoid deep ploughing. To hear this again, press 1. If this advice was useful, press 2. If not, press 3.",
      "ta": "வணக்கம். இது ஈரோடு மாவட்டத்திற்கான அக்ரிவர்ஷா வானிலை ஆலோசனை. ஈரோடு: பருவமழை இன்னும் நிலையாகவில்லை; வரும் நாட்களில் வறட்சி ஏற்பட அதிக வாய்ப்பு உள்ளது. மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம். மீண்டும் கேட்க 1-ஐ அழுத்தவும். இந்த ஆலோசனை பயனுள்ளதாக இருந்தால் 2-ஐயும், இல்லையென்றால் 3-ஐயும் அழுத்தவும்.",
      "chars_en": 299,
      "chars_ta": 320
    }
  },
  "broadcasts": []
}
```


### POST /api/advisories/{id}/edit
Body: any of `title_en, title_ta, text_en, text_ta, action_en, action_ta, severity,
tamil_reviewed`, plus optional `reviewer`, `note`. Returns the advisory, now `draft` with
`edited=true` (an approved advisory needs re-approval). Edited drafts are never overwritten
by auto-drafting.

```http
POST /api/advisories/14/edit
Content-Type: application/json

{"action_en": "Hold your seed until the soil is wet to 30 cm.", "reviewer": "officer.madurai", "note": "clearer action"}
```
Response `200`:
```json
{
  "id": 14,
  "issue_date": "2026-09-29",
  "forecast_source": "mock",
  "scenario": "none",
  "dedupe_key": "2026-09-29|mock|none|8|paddy|samba|false_onset",
  "region_id": 8,
  "district": "Erode",
  "crop": "paddy",
  "season": "samba",
  "stage": "tillering",
  "stage_group": "vegetative",
  "hazard_type": "false_onset",
  "hazard_subtype": null,
  "hazard_probability": 1.0,
  "hazard_lead_week": 0,
  "hazard_confidence": "High",
  "hazard_why": "False onset under way: 20.5 mm fell 20 Sep–21 Sep, and it has now been dry (< 2.5 mm/day) for 7 days since 22 Sep. Relief likely: 64% chance of ≥ 20 mm in week 1.",
  "rule_id": "FO-ANY",
  "severity": "watch",
  "title_en": "Rain not yet steady",
  "title_ta": "மழை இன்னும் நிலையாகவில்லை",
  "text_en": "Erode: the monsoon rain is not steady yet; a high chance of a dry spell in the coming days.",
  "text_ta": "ஈரோடு: பருவமழை இன்னும் நிலையாகவில்லை; வரும் நாட்களில் வறட்சி ஏற்பட அதிக வாய்ப்பு உள்ளது.",
  "action_en": "Hold your seed until the soil is wet to 30 cm.",
  "action_ta": "மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.",
  "simple_text_en": null,
  "rephrased_by": "template",
  "tamil_reviewed": false,
  "source_note": "Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: SAMPLE, not yet validated by agronomists.",
  "farmers_targeted": 69970,
  "status": "draft",
  "edited": true,
  "reviewer": "officer.madurai",
  "review_note": null,
  "created_at": "2026-09-29T14:56:22.726912+05:30",
  "updated_at": "2026-09-29T14:56:35.277268+05:30",
  "approved_at": null,
  "events": [
    {
      "action": "drafted",
      "actor": "system",
      "note": null,
      "payload": {
        "rule_id": "FO-ANY",
        "hazard_run_id": 1
      },
      "at": "2026-09-29T14:56:22.726912+05:30"
    },
    {
      "action": "edited",
      "actor": "officer.madurai",
      "note": "clearer action",
      "payload": {
        "after": {
          "action_en": "Hold your seed until the soil is wet to 30 cm."
        },
        "before": {
          "action_en": "Conserve soil moisture: mulch and avoid deep ploughing."
        },
        "previous_status": "draft"
      },
      "at": "2026-09-29T14:56:35.277268+05:30"
    }
  ]
}
```


### POST /api/advisories/{id}/approve
Body (optional): `{"reviewer": "...", "note": "..."}`. Only drafts can be approved.

```http
POST /api/advisories/14/approve
Content-Type: application/json

{"reviewer": "officer.madurai"}
```
Response `200`:
```json
{
  "id": 14,
  "issue_date": "2026-09-29",
  "forecast_source": "mock",
  "scenario": "none",
  "dedupe_key": "2026-09-29|mock|none|8|paddy|samba|false_onset",
  "region_id": 8,
  "district": "Erode",
  "crop": "paddy",
  "season": "samba",
  "stage": "tillering",
  "stage_group": "vegetative",
  "hazard_type": "false_onset",
  "hazard_subtype": null,
  "hazard_probability": 1.0,
  "hazard_lead_week": 0,
  "hazard_confidence": "High",
  "hazard_why": "False onset under way: 20.5 mm fell 20 Sep–21 Sep, and it has now been dry (< 2.5 mm/day) for 7 days since 22 Sep. Relief likely: 64% chance of ≥ 20 mm in week 1.",
  "rule_id": "FO-ANY",
  "severity": "watch",
  "title_en": "Rain not yet steady",
  "title_ta": "மழை இன்னும் நிலையாகவில்லை",
  "text_en": "Erode: the monsoon rain is not steady yet; a high chance of a dry spell in the coming days.",
  "text_ta": "ஈரோடு: பருவமழை இன்னும் நிலையாகவில்லை; வரும் நாட்களில் வறட்சி ஏற்பட அதிக வாய்ப்பு உள்ளது.",
  "action_en": "Hold your seed until the soil is wet to 30 cm.",
  "action_ta": "மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.",
  "simple_text_en": null,
  "rephrased_by": "template",
  "tamil_reviewed": false,
  "source_note": "Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: SAMPLE, not yet validated by agronomists.",
  "farmers_targeted": 69970,
  "status": "approved",
  "edited": true,
  "reviewer": "officer.madurai",
  "review_note": null,
  "created_at": "2026-09-29T14:56:22.726912+05:30",
  "updated_at": "2026-09-29T14:56:35.383648+05:30",
  "approved_at": "2026-09-29T14:56:35.383648+05:30",
  "events": [
    {
      "action": "drafted",
      "actor": "system",
      "note": null,
      "payload": {
        "rule_id": "FO-ANY",
        "hazard_run_id": 1
      },
      "at": "2026-09-29T14:56:22.726912+05:30"
    },
    {
      "action": "edited",
      "actor": "officer.madurai",
      "note": "clearer action",
      "payload": {
        "after": {
          "action_en": "Hold your seed until the soil is wet to 30 cm."
        },
        "before": {
          "action_en": "Conserve soil moisture: mulch and avoid deep ploughing."
        },
        "previous_status": "draft"
      },
      "at": "2026-09-29T14:56:35.277268+05:30"
    },
    "…"
  ]
}
```


409 when not a draft:

```http
POST /api/advisories/14/approve
Content-Type: application/json

{}
```
Response `409`:
```json
{
  "detail": "cannot approve an advisory with status 'approved'"
}
```


### POST /api/advisories/{id}/reject
Body (optional): `{"reviewer": "...", "reason": "..."}`. Allowed from draft or approved.

```http
POST /api/advisories/54/reject
Content-Type: application/json

{"reviewer": "officer", "reason": "duplicate"}
```
Response `200`:
```json
{
  "id": 54,
  "issue_date": "2026-09-29",
  "forecast_source": "mock",
  "scenario": "none",
  "dedupe_key": "2026-09-29|mock|none|10|paddy|samba|heavy_rain",
  "region_id": 10,
  "district": "Kancheepuram",
  "crop": "paddy",
  "season": "samba",
  "stage": "tillering",
  "stage_group": "vegetative",
  "hazard_type": "heavy_rain",
  "hazard_subtype": "very_heavy",
  "hazard_probability": 0.5377,
  "hazard_lead_week": 4,
  "hazard_confidence": "Low",
  "hazard_why": "54% chance of at least one day ≥ 64.5 mm in week 4 (21 Oct–27 Oct); week total median 84 mm, up to 344 mm (90th percentile).",
  "rule_id": "HR-PADDY",
  "severity": "watch",
  "title_en": "Heavy rain: drain paddy fields",
  "title_ta": "கனமழை: நெல் வயலில் நீரை வடிக்கவும்",
  "text_en": "Kancheepuram: 54% chance of heavy rain (≥ 64.5 mm in a day) in 21 Oct–27 Oct during tillering.",
  "text_ta": "காஞ்சிபுரம்: தூர் கட்டும் பருவத்தில் 21 அக்.–27 அக். காலத்தில் கனமழை (ஒரு நாளில் 64.5 மி.மீக்கு மேல்) பெய்ய 54% வாய்ப்பு.",
  "action_en": "Strengthen bunds, keep drainage open, and postpone urea top-dressing and sprays until the rain stops.",
  "action_ta": "வரப்புகளை வலுப்படுத்தவும், வடிகாலைத் திறந்து வைக்கவும், மழை நிற்கும் வரை யூரியா மேலுரம் மற்றும் தெளிப்புகளைத் தள்ளிப்போடவும்.",
  "simple_text_en": null,
  "rephrased_by": "template",
  "tamil_reviewed": false,
  "source_note": "Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: SAMPLE, not yet validated by agronomists.",
  "farmers_targeted": 68684,
  "status": "rejected",
  "edited": false,
  "reviewer": "officer",
  "review_note": "duplicate",
  "created_at": "2026-09-29T14:56:22.726912+05:30",
  "updated_at": "2026-09-29T14:56:37.518219+05:30",
  "approved_at": null,
  "events": [
    {
      "action": "drafted",
      "actor": "system",
      "note": null,
      "payload": {
        "rule_id": "HR-PADDY",
        "hazard_run_id": 1
      },
      "at": "2026-09-29T14:56:22.726912+05:30"
    },
    {
      "action": "rejected",
      "actor": "officer",
      "note": "duplicate",
      "payload": {},
      "at": "2026-09-29T14:56:37.518219+05:30"
    }
  ]
}
```


---

## Delivery (simulated)

### POST /api/broadcast/{advisory_id}
Body (optional): `{"channels": ["app","sms","whatsapp","ivr"]}` (default all four).
Only **approved** advisories (409 otherwise); the advisory becomes `sent`. Content is the
real advisory fitted per channel: SMS ≤ 160 characters per language (Tamil SMS is Unicode,
so `sms_segments_ta` > 1), WhatsApp full text, IVR a spoken script with keypad prompts, app
full text. Recipients = mock farmers × channel reach.

```http
POST /api/broadcast/14
Content-Type: application/json

{"channels": ["sms", "whatsapp", "ivr", "app"]}
```
Response `200`:
```json
{
  "broadcast_id": 1,
  "advisory_id": 14,
  "status": "in_progress",
  "delivery_mode": "simulated",
  "created_at": "2026-09-29T14:56:35.424149+05:30",
  "completed_at": null,
  "progress": 0.017,
  "duration_s": 1.5,
  "total_recipients": 137841,
  "totals": {
    "queued": 137841,
    "sent": 0,
    "delivered": 0,
    "read": 0,
    "failed": 0
  },
  "channels": [
    {
      "channel": "sms",
      "status": "queued",
      "recipients": 64372,
      "sent": 0,
      "delivered": 0,
      "read": 0,
      "failed": 0,
      "delivery_rate": 0.0,
      "read_rate": 0.0,
      "content_en": "AgriVarsha Erode: Rain not yet steady. Hold your seed until the soil is wet to 30 cm.",
      "content_ta": "அக்ரிவர்ஷா ஈரோடு: மழை இன்னும் நிலையாகவில்லை. மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.",
      "chars_en": 85,
      "chars_ta": 108,
      "sms_segments_en": 1,
      "sms_segments_ta": 2
    },
    {
      "channel": "whatsapp",
      "status": "queued",
      "recipients": 33586,
      "sent": 0,
      "delivered": 0,
      "read": 0,
      "failed": 0,
      "delivery_rate": 0.0,
      "read_rate": 0.0,
      "content_en": "🌦️ *AgriVarsha advisory: Erode*\n*Rain not yet steady*\n\nErode: the monsoon rain is not steady yet; a high chance of a dry spell in the coming days.\n\n✅ *What to do:* Hold your seed until the soil is wet to 30 cm.\n\n_Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: SAMPLE, not yet validated by agronomists._\nWas this useful? Reply 👍 or 👎",
      "content_ta": "🌦️ *அக்ரிவர்ஷா ஆலோசனை: ஈரோடு*\n*மழை இன்னும் நிலையாகவில்லை*\n\nஈரோடு: பருவமழை இன்னும் நிலையாகவில்லை; வரும் நாட்களில் வறட்சி ஏற்பட அதிக வாய்ப்பு உள்ளது.\n\n✅ *செய்ய வேண்டியது:* மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.\n\nஇது பயனுள்ளதா? 👍 அல்லது 👎 என பதிலளிக்கவும்",
      "chars_en": 364,
      "chars_ta": 277
    },
    "…"
  ],
  "as_of": "2026-09-29T09:26:35.462581+00:00"
}
```


### GET /api/broadcast/{id}/status
Poll every ~1 s. Counters move `queued → sent → delivered → read` over
`duration_s` (8 s by default) with realistic drop-off; channel `status` is `queued`,
`sending`, `delivering`, `reading` or `completed`. For IVR, delivered = call answered and
read = listened to the end. `failed = recipients − delivered` once completed. On completion
the simulator adds a few `simulated=true` farmer feedback rows.

Mid-way:

```http
GET /api/broadcast/1/status
```
Response `200`:
```json
{
  "broadcast_id": 1,
  "advisory_id": 14,
  "status": "in_progress",
  "delivery_mode": "simulated",
  "created_at": "2026-09-29T14:56:35.424149+05:30",
  "completed_at": null,
  "progress": 0.562,
  "duration_s": 1.5,
  "total_recipients": 137841,
  "totals": {
    "queued": 137841,
    "sent": 134732,
    "delivered": 104741,
    "read": 7936,
    "failed": 0
  },
  "channels": [
    {
      "channel": "sms",
      "status": "reading",
      "recipients": 64372,
      "sent": 62734,
      "delivered": 53350,
      "read": 3927,
      "failed": 0,
      "delivery_rate": 0.829,
      "read_rate": 0.074,
      "content_en": "AgriVarsha Erode: Rain not yet steady. Hold your seed until the soil is wet to 30 cm.",
      "content_ta": "அக்ரிவர்ஷா ஈரோடு: மழை இன்னும் நிலையாகவில்லை. மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.",
      "chars_en": 85,
      "chars_ta": 108,
      "sms_segments_en": 1,
      "sms_segments_ta": 2
    },
    {
      "channel": "whatsapp",
      "status": "reading",
      "recipients": 33586,
      "sent": 32773,
      "delivered": 25305,
      "read": 2088,
      "failed": 0,
      "delivery_rate": 0.753,
      "read_rate": 0.083,
      "content_en": "🌦️ *AgriVarsha advisory: Erode*\n*Rain not yet steady*\n\nErode: the monsoon rain is not steady yet; a high chance of a dry spell in the coming days.\n\n✅ *What to do:* Hold your seed until the soil is wet to 30 cm.\n\n_Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: SAMPLE, not yet validated by agronomists._\nWas this useful? Reply 👍 or 👎",
      "content_ta": "🌦️ *அக்ரிவர்ஷா ஆலோசனை: ஈரோடு*\n*மழை இன்னும் நிலையாகவில்லை*\n\nஈரோடு: பருவமழை இன்னும் நிலையாகவில்லை; வரும் நாட்களில் வறட்சி ஏற்பட அதிக வாய்ப்பு உள்ளது.\n\n✅ *செய்ய வேண்டியது:* மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.\n\nஇது பயனுள்ளதா? 👍 அல்லது 👎 என பதிலளிக்கவும்",
      "chars_en": 364,
      "chars_ta": 277
    },
    "…"
  ],
  "as_of": "2026-09-29T09:26:36.267781+00:00"
}
```


Completed:

```http
GET /api/broadcast/1/status
```
Response `200`:
```json
{
  "broadcast_id": 1,
  "advisory_id": 14,
  "status": "completed",
  "delivery_mode": "simulated",
  "created_at": "2026-09-29T14:56:35.424149+05:30",
  "completed_at": null,
  "progress": 1.0,
  "duration_s": 1.5,
  "total_recipients": 137841,
  "totals": {
    "queued": 137841,
    "sent": 134732,
    "delivered": 116313,
    "read": 73651,
    "failed": 21528
  },
  "channels": [
    {
      "channel": "sms",
      "status": "completed",
      "recipients": 64372,
      "sent": 62734,
      "delivered": 59244,
      "read": 36447,
      "failed": 5128,
      "delivery_rate": 0.92,
      "read_rate": 0.615,
      "content_en": "AgriVarsha Erode: Rain not yet steady. Hold your seed until the soil is wet to 30 cm.",
      "content_ta": "அக்ரிவர்ஷா ஈரோடு: மழை இன்னும் நிலையாகவில்லை. மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.",
      "chars_en": 85,
      "chars_ta": 108,
      "sms_segments_en": 1,
      "sms_segments_ta": 2
    },
    {
      "channel": "whatsapp",
      "status": "completed",
      "recipients": 33586,
      "sent": 32773,
      "delivered": 28101,
      "read": 19381,
      "failed": 5485,
      "delivery_rate": 0.837,
      "read_rate": 0.69,
      "content_en": "🌦️ *AgriVarsha advisory: Erode*\n*Rain not yet steady*\n\nErode: the monsoon rain is not steady yet; a high chance of a dry spell in the coming days.\n\n✅ *What to do:* Hold your seed until the soil is wet to 30 cm.\n\n_Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: SAMPLE, not yet validated by agronomists._\nWas this useful? Reply 👍 or 👎",
      "content_ta": "🌦️ *அக்ரிவர்ஷா ஆலோசனை: ஈரோடு*\n*மழை இன்னும் நிலையாகவில்லை*\n\nஈரோடு: பருவமழை இன்னும் நிலையாகவில்லை; வரும் நாட்களில் வறட்சி ஏற்பட அதிக வாய்ப்பு உள்ளது.\n\n✅ *செய்ய வேண்டியது:* மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்.\n\nஇது பயனுள்ளதா? 👍 அல்லது 👎 என பதிலளிக்கவும்",
      "chars_en": 364,
      "chars_ta": 277
    },
    "…"
  ],
  "as_of": "2026-09-29T09:26:37.505647+00:00"
}
```


### GET /api/broadcasts?limit=50
Recent broadcasts with their advisory.

```http
GET /api/broadcasts
```
Response `200`:
```json
{
  "broadcasts": [
    {
      "broadcast_id": 1,
      "advisory_id": 14,
      "status": "completed",
      "channels": [
        "sms",
        "whatsapp",
        "…"
      ],
      "total_recipients": 137841,
      "created_at": "2026-09-29T14:56:35.424149+05:30",
      "completed_at": "2026-09-29T14:56:37.481976+05:30",
      "district": "Erode",
      "crop": "paddy",
      "title_en": "Rain not yet steady",
      "severity": "watch"
    }
  ]
}
```


### POST /api/feedback
Body: `{"advisory_id": 12, "rating": "up"|"down" (or 1/-1, 👍/👎), "comment": "...",
"channel": "whatsapp", "broadcast_id": 3}` (comment/channel/broadcast optional). 201.

```http
POST /api/feedback
Content-Type: application/json

{"advisory_id": 14, "rating": "up", "comment": "Waited as advised", "channel": "whatsapp"}
```
Response `201`:
```json
{
  "id": 26,
  "advisory_id": 14,
  "broadcast_id": null,
  "channel": "whatsapp",
  "rating": 1,
  "comment": "Waited as advised",
  "simulated": false,
  "created_at": "2026-09-29T14:56:37.529520+05:30"
}
```


### GET /api/feedback/summary?advisory_id=&include_simulated=true
Totals (with `real` vs `simulated`), breakdowns by hazard type, district, channel and
advisory, and recent comments.

```http
GET /api/feedback/summary
```
Response `200`:
```json
{
  "totals": {
    "total": 26,
    "up": 24,
    "down": 2,
    "simulated": 25,
    "real": 1,
    "with_comment": 11,
    "positive_rate": 0.923
  },
  "by_hazard_type": [
    {
      "key": "false_onset",
      "total": 26,
      "up": 24,
      "down": 2,
      "positive_rate": 0.923
    }
  ],
  "by_district": [
    {
      "key": "Erode",
      "total": 26,
      "up": 24,
      "down": 2,
      "positive_rate": 0.923
    }
  ],
  "by_channel": [
    {
      "key": "whatsapp",
      "total": 11,
      "up": 11,
      "down": 0,
      "positive_rate": 1.0
    },
    {
      "key": "app",
      "total": 10,
      "up": 8,
      "down": 2,
      "positive_rate": 0.8
    },
    "…"
  ],
  "by_advisory": [
    {
      "key": 14,
      "total": 26,
      "up": 24,
      "down": 2,
      "positive_rate": 0.923
    }
  ],
  "recent_comments": [
    {
      "id": 26,
      "advisory_id": 14,
      "district": "Erode",
      "crop": "paddy",
      "hazard_type": "false_onset",
      "channel": "whatsapp",
      "rating": 1,
      "comment": "Waited as advised",
      "simulated": false,
      "created_at": "2026-09-29T14:56:37.529520+05:30"
    },
    {
      "id": 22,
      "advisory_id": 14,
      "district": "Erode",
      "crop": "paddy",
      "hazard_type": "false_onset",
      "channel": "ivr",
      "rating": 1,
      "comment": "Will follow this",
      "simulated": true,
      "created_at": "2026-09-29T14:56:37.481976+05:30"
    },
    "…"
  ],
  "note": "Rows with simulated=true come from the delivery simulator (MOCK farmer responses)."
}
```


---

## Pipeline and model (real)

### GET /api/pipeline/health
Segment 1/2 table row counts, rainfall freshness, forecast issue dates, the last 10
`pipeline_runs`, and the parsed quality report. `status`: `ok`, `ok_with_warnings`
(quality warnings or a recent failed run) or `degraded` (quality failure or rainfall > 3
days old).

```http
GET /api/pipeline/health
```
Response `200`:
```json
{
  "status": "ok_with_warnings",
  "table_counts": {
    "regions": 38,
    "region_grid_weights": 421,
    "rainfall_daily": 496090,
    "climate_indices_daily": 13421,
    "era5_daily": 0,
    "climatology_daily": 13908,
    "features_daily": 496090,
    "crop_calendar": 33,
    "pipeline_runs": 44,
    "forecasts": 152,
    "model_skill": 504
  },
  "rainfall": {
    "last_date": "2026-09-28",
    "lag_days": 1
  },
  "forecasts": {
    "issue_dates": [
      "2026-09-28"
    ],
    "latest_issue_date": "2026-09-28"
  },
  "recent_runs": [
    {
      "id": 69,
      "stage": "ml:predict",
      "status": "success",
      "started_at": "2026-09-29T12:30:10.551754+05:30",
      "finished_at": "2026-09-29T12:30:30.058049+05:30",
      "rows_written": 152,
      "message": "issue date 2026-09-28: 152 forecast rows (38 regions × 4 leads) | confidence Low 152 | model s2-lgbm-20260929-0304",
      "duration_s": 19.506295
    },
    {
      "id": 68,
      "stage": "ml:train",
      "status": "success",
      "started_at": "2026-09-29T03:28:41.043026+05:30",
      "finished_at": "2026-09-29T03:41:16.773388+05:30",
      "rows_written": 24,
      "message": "model_version s2-lgbm-20260929-0304: 24 models | top features: dmi_pub_prev, doy_cos, oni_pub_prev, oni_pub, dmi_pub | card: ml/artifacts/s2-lgbm-20260929-0304/model_card.md",
      "duration_s": 755.730362
    },
    "…"
  ],
  "quality": {
    "report_generated": "2026-09-29 01:20",
    "report_path": "backend/data/processed/quality_report.md",
    "summary": {
      "pass": 8,
      "warn": 1,
      "fail": 0
    },
    "checks": [
      {
        "check": "regions loaded",
        "status": "PASS",
        "detail": "38 active regions (district level)"
      },
      {
        "check": "missing rainfall dates per region",
        "status": "PASS",
        "detail": "0 of 38 regions have gaps in 1991-01-01..2026-09-28 (13055 days)"
      },
      "…"
    ],
    "latest_quality_run": {
      "id": 40,
      "stage": "quality",
      "status": "success",
      "finished_at": "2026-09-29T01:20:11.067621+05:30",
      "message": "9 checks: 8 pass, 1 warn, 0 fail | report: data/processed/quality_report.md"
    }
  }
}
```


### GET /api/model/skill?model_version=&target=&season=&lead_week=&metric=&model=
Segment 2 validation (`model_skill`) with 5–95% year-block bootstrap CIs; defaults to
`s2-lgbm-20260929-0304`. `headline` = the main score per target (tercile `rpss`,
heavy/dry `bss`, weekly total `qss`) for the calibrated model, with
`skillful` = CI lower bound > 0. Targets: `tercile`, `heavy_day`, `dry_week`,
`weekly_total_mm`; seasons `SWM` (Jun–Sep), `NEM` (Oct–Dec), `ALL`.

```http
GET /api/model/skill?target=tercile&season=ALL&model=lgbm
```
Response `200`:
```json
{
  "model_version": "s2-lgbm-20260929-0304",
  "meta": {
    "model_version": "s2-lgbm-20260929-0304",
    "trained": "2026-09-29T03:41:09",
    "train_years": [
      1991,
      2025
    ],
    "final_data_end": "2025-12-31",
    "n_features": 34
  },
  "model_card": "backend/ml/artifacts/s2-lgbm-20260929-0304/model_card.md",
  "note": "Skill scores are relative to climatology: > 0 beats climatology. CIs are 5–95% year-block bootstrap intervals. 'skillful' = CI lower bound > 0.",
  "headline": [
    {
      "target": "tercile",
      "lead_week": 1,
      "season": "ALL",
      "value": 0.029554080281843254,
      "ci_low": 0.00866079963780067,
      "ci_high": 0.0489452963456367,
      "metric": "rpss",
      "skillful": true
    },
    {
      "target": "tercile",
      "lead_week": 2,
      "season": "ALL",
      "value": -0.004246639014356068,
      "ci_low": -0.012669087073591535,
      "ci_high": 0.004319996604168689,
      "metric": "rpss",
      "skillful": false
    },
    "…"
  ],
  "count": 8,
  "rows": [
    {
      "target": "tercile",
      "lead_week": 1,
      "season": "ALL",
      "metric": "rps",
      "model": "lgbm",
      "value": 0.4243567995870205,
      "ci_low": null,
      "ci_high": null,
      "n_samples": 121714,
      "n_years": 15
    },
    {
      "target": "tercile",
      "lead_week": 1,
      "season": "ALL",
      "metric": "rpss",
      "model": "lgbm",
      "value": 0.029554080281843254,
      "ci_low": 0.00866079963780067,
      "ci_high": 0.0489452963456367,
      "n_samples": 121714,
      "n_years": 15
    },
    "…"
  ]
}
```


---

## Settings

### GET /api/settings/forecast-source

```http
GET /api/settings/forecast-source
```
Response `200`:
```json
{
  "source": "mock",
  "available": [
    "mock",
    "real"
  ],
  "env_default": "mock",
  "scenario": null,
  "real_issue_dates": [
    "2026-09-28"
  ],
  "demo_mode": true
}
```


### POST /api/settings/forecast-source?date=
Body `{"source": "mock"|"real"}`. Switches at runtime and immediately re-runs hazards →
advisories for the date; the response summarises the result. With `real`, forecasts come
from Segment 2's `forecasts` table (latest run on or before the date).

```http
POST /api/settings/forecast-source?date=2026-09-29
Content-Type: application/json

{"source": "real"}
```
Response `200`:
```json
{
  "source": "real",
  "available": [
    "mock",
    "real"
  ],
  "env_default": "mock",
  "scenario": null,
  "real_issue_dates": [
    "2026-09-28"
  ],
  "demo_mode": true,
  "context": {
    "issue_date": "2026-09-29",
    "forecast_source": "real",
    "scenario": "none",
    "forecast_issue_date": "2026-09-28",
    "model_version": "s2-lgbm-20260929-0304",
    "observed_through": "2026-09-28",
    "note": "No Segment 2 run for 2026-09-29; using the latest run, issued 2026-09-28 (1 day(s) earlier).",
    "hazard_run_id": 2
  },
  "hazards_by_type": {
    "false_onset": 10,
    "dry_spell": 13,
    "onset": 22
  },
  "hazard_count": 45
}
```


After switching, the same endpoints serve the model's rows — e.g. `GET /api/forecast/chennai`:

```http
GET /api/forecast/chennai?date=2026-09-29
```
Response `200`:
```json
{
  "context": {
    "issue_date": "2026-09-29",
    "forecast_source": "real",
    "scenario": "none",
    "forecast_issue_date": "2026-09-28",
    "model_version": "s2-lgbm-20260929-0304",
    "observed_through": "2026-09-28",
    "note": "No Segment 2 run for 2026-09-29; using the latest run, issued 2026-09-28 (1 day(s) earlier).",
    "hazard_run_id": 2
  },
  "district": {
    "id": 3,
    "code": "tn/chennai",
    "slug": "chennai",
    "name": "Chennai",
    "area_km2": 174.7121790005073,
    "lon": 80.24379967364806,
    "lat": 13.063499845351444,
    "coastal": true
  },
  "forecast": [
    {
      "lead_week": 1,
      "week_start": "2026-09-29",
      "week_end": "2026-10-05",
      "p_below": 0.3933,
      "p_normal": 0.3225,
      "p_above": 0.2842,
      "q10_mm": 0.48,
      "q50_mm": 16.82,
      "q90_mm": 70.08,
      "p_heavy": 0.0554,
      "p_dry_week": 0.248,
      "confidence": "Low",
      "model_version": "s2-lgbm-20260929-0304"
    },
    {
      "lead_week": 2,
      "week_start": "2026-10-06",
      "week_end": "2026-10-12",
      "p_below": 0.3246,
      "p_normal": 0.3411,
      "p_above": 0.3343,
      "q10_mm": 0.57,
      "q50_mm": 28.26,
      "q90_mm": 96.08,
      "p_heavy": 0.1068,
      "p_dry_week": 0.1984,
      "confidence": "Low",
      "model_version": "s2-lgbm-20260929-0304"
    },
    "…"
  ],
  "hazards": [],
  "crop_stages": [
    {
      "crop": "cotton",
      "season": "rainfed_winter",
      "stage": "emergence",
      "stage_group": "establishment",
      "days_after_sowing": 7,
      "typical_sowing_date": "2026-09-22",
      "sowing_window": [
        "2026-08-31",
        "2026-10-14"
      ],
      "calendar_district": "ALL",
      "is_sample": true
    },
    {
      "crop": "groundnut",
      "season": "kharif",
      "stage": "pod_development",
      "stage_group": "grain_fill",
      "days_after_sowing": 84,
      "typical_sowing_date": "2026-07-07",
      "sowing_window": [
        "2026-06-14",
        "2026-07-30"
      ],
      "calendar_district": "ALL",
      "is_sample": true
    },
    "…"
  ],
  "observed": {
    "through": "2026-09-28",
    "last_7_days_mm": 3.9,
    "last_30_days_mm": 54.0,
    "source": "Segment 1 rainfall_daily (IMD gridded, area-weighted)"
  }
}
```


---

## Chat

### POST /api/chat
Body: `{"message": "...", "district": "madurai" (optional; else detected in the message),
"date": "2026-09-29" (optional)}`. Response `text/event-stream`:

| event | data |
| --- | --- |
| `meta` | `{mode: "template"|"llm", intent, district, context, sources: [API paths the facts came from]}` |
| `token` | `{text}` — append to the answer |
| `done` | `{mode, answer?}` (`answer` = full text in template mode; `mode` `template_fallback` if the LLM failed) |
| `error` | `{detail}` |

Answers only use numbers from the current forecasts, hazards, advisories and observed
rain. Read it with `fetch()` + a stream reader (EventSource cannot POST):

```js
const res = await fetch('/api/chat', {method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({message})});
const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
let buf = '';
for (;;) {
  const {value, done} = await reader.read(); if (done) break;
  buf += value; let i;
  while ((i = buf.indexOf('\n\n')) >= 0) {
    const block = buf.slice(0, i); buf = buf.slice(i + 2);
    const ev = /event: (.*)/.exec(block)[1], data = JSON.parse(/data: (.*)/.exec(block)[1]);
    if (ev === 'token') appendText(data.text);
  }
}
```

Example stream (template mode, abridged):

```http
POST /api/chat
Content-Type: application/json

{"message": "Should I sow millets in Madurai this week?", "date": "2026-09-29"}
```
Response `200` (text/event-stream):
```text
event: meta
data: {"mode": "template", "intent": "sowing", "district": "Madurai", "context": {"issue_date": "2026-09-29", "forecast_source": "mock", "scenario": "none", "forecast_issue_date": "2026-09-29", "model_version": "mock-gen-v1", "observed_through": "2026-09-28", "note": "MOCK forecasts (deterministic generator)", "hazard_run_id": 1}, "sources": ["/api/forecast/madurai", "/api/rainfall/madurai", "/api/advisories?district=madurai", "/api/hazards", "/api/overview"]}

event: token
data: {"text": "Madurai: "}

event: token
data: {"text": "crops "}

event: token
data: {"text": "in "}

event: token
data: {"text": "their "}

…

event: done
data: {"mode": "template", "answer": "Madurai: crops in their sowing window now: millets, pulses. Wait a few days before sowing. False onset under way: 42.0 mm fell 20 Sep–21 Sep, and it has now been dry (< 2.5 mm/day) for 7 days since 22 Sep. Relief likely: 59% chance of ≥ 20 mm in week 1.\nObserved: 1.6 mm in the last 7 days and 135.7 mm in the last 30 days (to 2026-09-28).\n(Source: MOCK forecast issued 2026-09-29; observed rain from IMD data through 2026-09-28.)"}
```


---

## Demo scenarios (mock forecasts)

### GET /api/demo/scenarios

```http
GET /api/demo/scenarios
```
Response `200`:
```json
{
  "active": null,
  "scenarios": [
    {
      "name": "false_onset_trap",
      "title": "False onset trap",
      "description": "Heavy early rain in Madurai next week, then a ~10-day dry spell. Early sowing would fail, so the advice is: don't sow yet.",
      "demo_date": "2026-09-29",
      "focus_districts": [
        "Madurai"
      ]
    },
    {
      "name": "ne_monsoon_surge",
      "title": "NE monsoon surge",
      "description": "A strong northeast-monsoon pulse brings heavy-rain alerts to Chennai, Cuddalore and Nagapattinam in weeks 1–2.",
      "demo_date": "2026-10-20",
      "focus_districts": [
        "Chennai",
        "Cuddalore",
        "…"
      ]
    },
    "…"
  ]
}
```


### POST /api/demo/scenario/{name}
Activates a scenario: switches the source to `mock`, sets the default date to the
scenario's `demo_date` (so plain requests without `?date=` show it), recomputes hazards and
drafts advisories. Returns the focus districts' hazards and advisories.

| name | demo date | what happens |
| --- | --- | --- |
| `false_onset_trap` | today | Heavy week-1 rain in Madurai then a dry weeks 2–3 → `false_onset` warning, "Don't sow … yet" advisories |
| `ne_monsoon_surge` | 2026-10-20 | `heavy_rain` **warnings** in Chennai, Cuddalore, Nagapattinam (weeks 1–2); neighbours active phase |
| `mid_season_break` | 2026-08-14 | Groundnut belt dry for 2 weeks at flowering/pegging → 14-day `dry_spell` warnings, then `revival` |
| `normal_season` | today | Forecast signals damped: no forecast-based watch/warning (observed-only hazards may remain) |


```http
POST /api/demo/scenario/false_onset_trap
```
Response `200`:
```json
{
  "scenario": {
    "name": "false_onset_trap",
    "title": "False onset trap",
    "description": "Heavy early rain in Madurai next week, then a ~10-day dry spell. Early sowing would fail, so the advice is: don't sow yet.",
    "demo_date": "2026-09-29",
    "focus_districts": [
      "Madurai"
    ]
  },
  "switched_source_to_mock": false,
  "context": {
    "issue_date": "2026-09-29",
    "forecast_source": "mock",
    "scenario": "false_onset_trap",
    "forecast_issue_date": "2026-09-29",
    "model_version": "mock-gen-v1",
    "observed_through": "2026-09-28",
    "note": "MOCK forecasts (deterministic generator)",
    "hazard_run_id": 3
  },
  "hazard_count": 66,
  "hazards_by_type": {
    "false_onset": 10,
    "dry_spell": 13,
    "heavy_rain": 5,
    "onset": 25,
    "revival": 13
  },
  "focus_hazards": [
    {
      "id": 112,
      "region_id": 14,
      "district": "Madurai",
      "hazard_type": "false_onset",
      "subtype": null,
      "severity": "warning",
      "probability": 1.0,
      "lead_week": 0,
      "window_start": "2026-09-20",
      "window_end": "2026-09-28",
      "confidence": "High",
      "basis": "observed",
      "why": "False onset under way: 42.0 mm fell 20 Sep–21 Sep, and it has now been dry (< 2.5 mm/day) for 7 days since 22 Sep.",
      "evidence": {
        "onset": {
          "end": "2026-09-21",
          "days": 2,
          "start": "2026-09-20",
          "total_mm": 42.0
        },
        "dry_run_days": 7,
        "p_rain_week1": 0.8603,
        "max_p_dry_weeks_1_3": 0.8
      }
    },
    {
      "id": 116,
      "region_id": 14,
      "district": "Madurai",
      "hazard_type": "dry_spell",
      "subtype": "14d",
      "severity": "warning",
      "probability": 0.548,
      "lead_week": 2,
      "window_start": "2026-10-07",
      "window_end": "2026-10-20",
      "confidence": "Medium",
      "basis": "forecast",
      "why": "14-day dry spell risk 55%: week 2 (7 Oct–13 Oct) is dry with 80% chance and week 3 with 55% (dry weeks tend to persist; assumed persistence 0.3).",
      "evidence": {
        "p_14d": 0.548,
        "p_dry_weeks": [
          0.8,
          0.55
        ],
        "persistence_rho": 0.3
      }
    },
    "…"
  ],
  "focus_advisories": [
    {
      "id": 238,
      "district": "Madurai",
      "crop": "cotton",
      "stage": "emergence",
      "hazard_type": "false_onset",
      "severity": "warning",
      "title_en": "Young cotton at risk from dry spell",
      "status": "draft"
    },
    {
      "id": 239,
      "district": "Madurai",
      "crop": "groundnut",
      "stage": "pod_development",
      "hazard_type": "dry_spell",
      "severity": "warning",
      "title_en": "Groundnut pods need water",
      "status": "draft"
    },
    "…"
  ]
}
```


`ne_monsoon_surge`:

```http
POST /api/demo/scenario/ne_monsoon_surge
```
Response `200`:
```json
{
  "scenario": {
    "name": "ne_monsoon_surge",
    "title": "NE monsoon surge",
    "description": "A strong northeast-monsoon pulse brings heavy-rain alerts to Chennai, Cuddalore and Nagapattinam in weeks 1–2.",
    "demo_date": "2026-10-20",
    "focus_districts": [
      "Chennai",
      "Cuddalore",
      "…"
    ]
  },
  "switched_source_to_mock": false,
  "context": {
    "issue_date": "2026-10-20",
    "forecast_source": "mock",
    "scenario": "ne_monsoon_surge",
    "forecast_issue_date": "2026-10-20",
    "model_version": "mock-gen-v1",
    "observed_through": "2026-09-28",
    "note": "MOCK forecasts (deterministic generator)",
    "hazard_run_id": 4
  },
  "hazard_count": 49,
  "hazards_by_type": {
    "heavy_rain": 3,
    "dry_spell": 1,
    "onset": 36,
    "active_phase": 9
  },
  "focus_hazards": [
    {
      "id": 177,
      "region_id": 3,
      "district": "Chennai",
      "hazard_type": "heavy_rain",
      "subtype": "very_heavy",
      "severity": "warning",
      "probability": 0.85,
      "lead_week": 1,
      "window_start": "2026-10-21",
      "window_end": "2026-10-27",
      "confidence": "High",
      "basis": "forecast",
      "why": "85% chance of at least one day ≥ 64.5 mm in week 1 (21 Oct–27 Oct); week total median 140 mm, up to 320 mm (90th percentile).",
      "evidence": {
        "q50_mm": 140.0,
        "q90_mm": 320.0,
        "p_heavy": 0.85,
        "weeks_over_threshold": [
          1,
          2,
          "…"
        ]
      }
    },
    {
      "id": 178,
      "region_id": 5,
      "district": "Cuddalore",
      "hazard_type": "heavy_rain",
      "subtype": "very_heavy",
      "severity": "warning",
      "probability": 0.85,
      "lead_week": 1,
      "window_start": "2026-10-21",
      "window_end": "2026-10-27",
      "confidence": "High",
      "basis": "forecast",
      "why": "85% chance of at least one day ≥ 64.5 mm in week 1 (21 Oct–27 Oct); week total median 140 mm, up to 320 mm (90th percentile).",
      "evidence": {
        "q50_mm": 140.0,
        "q90_mm": 320.0,
        "p_heavy": 0.85,
        "weeks_over_threshold": [
          1,
          2,
          "…"
        ]
      }
    },
    "…"
  ],
  "focus_advisories": [
    {
      "id": 357,
      "district": "Chennai",
      "crop": "groundnut",
      "stage": "maturity",
      "hazard_type": "heavy_rain",
      "severity": "warning",
      "title_en": "Harvest groundnut before heavy rain",
      "status": "draft"
    },
    {
      "id": 362,
      "district": "Cuddalore",
      "crop": "groundnut",
      "stage": "maturity",
      "hazard_type": "heavy_rain",
      "severity": "warning",
      "title_en": "Harvest groundnut before heavy rain",
      "status": "draft"
    },
    "…"
  ]
}
```


`mid_season_break`:

```http
POST /api/demo/scenario/mid_season_break
```
Response `200`:
```json
{
  "scenario": {
    "name": "mid_season_break",
    "title": "Mid-season break",
    "description": "A two-week dry spell over the groundnut belt during flowering/pegging, with rain returning in week 3.",
    "demo_date": "2026-08-14",
    "focus_districts": [
      "Tiruvannamalai",
      "Viluppuram",
      "…"
    ]
  },
  "switched_source_to_mock": false,
  "context": {
    "issue_date": "2026-08-14",
    "forecast_source": "mock",
    "scenario": "mid_season_break",
    "forecast_issue_date": "2026-08-14",
    "model_version": "mock-gen-v1",
    "observed_through": "2026-08-13",
    "note": "MOCK forecasts (deterministic generator)",
    "hazard_run_id": 5
  },
  "hazard_count": 42,
  "hazards_by_type": {
    "dry_spell": 26,
    "active_phase": 4,
    "revival": 12
  },
  "focus_hazards": [
    {
      "id": 227,
      "region_id": 6,
      "district": "Dharmapuri",
      "hazard_type": "dry_spell",
      "subtype": "14d",
      "severity": "warning",
      "probability": 0.5138,
      "lead_week": 1,
      "window_start": "2026-08-15",
      "window_end": "2026-08-28",
      "confidence": "Medium",
      "basis": "forecast",
      "why": "14-day dry spell risk 51%: week 1 (15 Aug–21 Aug) is dry with 70% chance and week 2 with 62% (dry weeks tend to persist; assumed persistence 0.3).",
      "evidence": {
        "p_14d": 0.5138,
        "p_dry_weeks": [
          0.7,
          0.62
        ],
        "persistence_rho": 0.3
      }
    },
    {
      "id": 228,
      "region_id": 9,
      "district": "Kallakurichi",
      "hazard_type": "dry_spell",
      "subtype": "14d",
      "severity": "warning",
      "probability": 0.5138,
      "lead_week": 1,
      "window_start": "2026-08-15",
      "window_end": "2026-08-28",
      "confidence": "Medium",
      "basis": "forecast",
      "why": "14-day dry spell risk 51%: week 1 (15 Aug–21 Aug) is dry with 70% chance and week 2 with 62% (dry weeks tend to persist; assumed persistence 0.3).",
      "evidence": {
        "p_14d": 0.5138,
        "p_dry_weeks": [
          0.7,
          0.62
        ],
        "persistence_rho": 0.3
      }
    },
    "…"
  ],
  "focus_advisories": [
    {
      "id": 390,
      "district": "Dharmapuri",
      "crop": "groundnut",
      "stage": "flowering_pegging",
      "hazard_type": "dry_spell",
      "severity": "warning",
      "title_en": "Critical: groundnut flowering needs water",
      "status": "draft"
    },
    {
      "id": 392,
      "district": "Kallakurichi",
      "crop": "groundnut",
      "stage": "flowering_pegging",
      "hazard_type": "dry_spell",
      "severity": "warning",
      "title_en": "Critical: groundnut flowering needs water",
      "status": "draft"
    },
    "…"
  ]
}
```


### POST /api/demo/reset?purge=false
Clears the scenario and returns the source to its `.env` default. `purge=true` also empties
the backend tables (hazards, advisories, broadcasts, feedback); Segment 1/2 data is never
touched.

```http
POST /api/demo/reset
```
Response `200`:
```json
{
  "reset": true,
  "purged_tables": [],
  "source": "mock",
  "available": [
    "mock",
    "real"
  ],
  "env_default": "mock",
  "scenario": null,
  "real_issue_dates": [
    "2026-09-28"
  ],
  "demo_mode": true,
  "context": {
    "issue_date": "2026-09-29",
    "forecast_source": "mock",
    "scenario": "none",
    "forecast_issue_date": "2026-09-29",
    "model_version": "mock-gen-v1",
    "observed_through": "2026-09-28",
    "note": "MOCK forecasts (deterministic generator)",
    "hazard_run_id": 1
  }
}
```

