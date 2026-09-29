"""Current crop stage per district from Segment 1's ``crop_calendar``.

The calendar gives a sowing window (day-of-year) and stage offsets in days after sowing.
We take the middle of the sowing window as the typical sowing date:

* date inside the sowing window and before its middle → stage ``sowing`` (most farmers are
  deciding whether to sow; this is where "don't sow yet" advice applies);
* otherwise days-after-sowing = date − typical sowing date → the matching calendar stage;
* beyond the last stage (or before the window) → the crop is not in the field.

District-specific calendar rows override the ``ALL`` rows for the same crop and season.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

import pandas as pd

from app.segment1 import crop_calendar, doy_of

STAGE_GROUPS = {
    "sowing": "sowing",
    "nursery": "establishment", "emergence": "establishment",
    "tillering": "vegetative", "vegetative": "vegetative", "squaring": "vegetative",
    "panicle_initiation": "flowering", "flowering": "flowering", "flowering_pegging": "flowering",
    "pod_development": "grain_fill", "boll_development": "grain_fill",
    "grain_filling_maturity": "grain_fill", "pod_filling_maturity": "grain_fill",
    "maturity": "maturity",
}


@dataclass
class CropStage:
    crop: str
    season: str
    stage: str
    stage_group: str
    days_after_sowing: int | None
    typical_sowing_date: date
    sowing_window: tuple[date, date]
    calendar_district: str
    is_sample: bool

    def as_dict(self) -> dict:
        d = asdict(self)
        d["sowing_window"] = [self.sowing_window[0], self.sowing_window[1]]
        return d


def _doy_to_date(doy: int, year: int) -> date:
    # Segment 1's 366-day calendar: doy 60 = Feb 29, so non-leap years skip it.
    base = date(year, 1, 1) + timedelta(days=doy - 1)
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return base if leap or doy <= 59 else base - timedelta(days=1)


def stages_from_calendar(cal: pd.DataFrame, district: str, d: date) -> list[CropStage]:
    """Pure function (tested): crop stages active in ``district`` on ``d``."""
    x = doy_of(d)
    out: list[CropStage] = []
    for (crop, season), g in cal.groupby(["crop", "season"], sort=True):
        rows = g[g["district"] == district]
        if rows.empty:
            rows = g[g["district"] == "ALL"]
        if rows.empty:
            continue
        rows = rows.sort_values("stage_start_day")
        start, end = int(rows["sowing_start_doy"].iloc[0]), int(rows["sowing_end_doy"].iloc[0])
        mid = (start + end) // 2
        year = d.year if x >= start else d.year - 1
        window = (_doy_to_date(start, year), _doy_to_date(end, year))
        typical = _doy_to_date(mid, year)
        common = dict(crop=crop, season=season, typical_sowing_date=typical, sowing_window=window,
                      calendar_district=str(rows["district"].iloc[0]),
                      is_sample=bool(rows["is_sample"].all()))
        if start <= x < mid:
            out.append(CropStage(stage="sowing", stage_group="sowing", days_after_sowing=None, **common))
            continue
        das = (x - mid) % 366
        hit = rows[(rows["stage_start_day"] <= das) & (rows["stage_end_day"] >= das)]
        if hit.empty:
            continue
        stage = str(hit["stage_name"].iloc[0])
        out.append(CropStage(stage=stage, stage_group=STAGE_GROUPS.get(stage, "vegetative"),
                             days_after_sowing=int(das), **common))
    return out


def current_stages(district: str, d: date) -> list[CropStage]:
    return stages_from_calendar(crop_calendar(), district, d)
