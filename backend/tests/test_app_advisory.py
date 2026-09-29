"""Advisory selection, crop stages, rendering and channel formatting (pure; no database)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.advisory.engine import render, resolve_conflicts
from app.advisory.rules import RULES, select_rule
from app.advisory.stages import stages_from_calendar
from app.delivery.channels import SMS_MAX, format_message, sms_segments
from app.delivery.simulator import progress


def cal_rows(crop, season, district, s, e, stages):
    return [dict(crop=crop, season=season, district=district, sowing_start_doy=s,
                 sowing_end_doy=e, stage_name=n, stage_start_day=a, stage_end_day=b,
                 is_sample=True, source="test") for n, a, b in stages]


@pytest.fixture
def calendar() -> pd.DataFrame:
    rows = []
    rows += cal_rows("groundnut", "kharif", "ALL", 166, 212,
                     [("emergence", 0, 15), ("vegetative", 16, 35), ("flowering_pegging", 36, 60),
                      ("pod_development", 61, 90), ("maturity", 91, 110)])
    rows += cal_rows("millets", "rabi_ne_monsoon", "ALL", 258, 304,
                     [("emergence", 0, 15), ("tillering", 16, 35), ("flowering", 36, 55),
                      ("grain_filling_maturity", 56, 85)])
    rows += cal_rows("paddy", "samba", "ALL", 213, 274,
                     [("nursery", 0, 25), ("tillering", 26, 70), ("panicle_initiation", 71, 100),
                      ("flowering", 101, 125), ("maturity", 126, 150)])
    rows += cal_rows("paddy", "samba", "Thanjavur", 213, 258,
                     [("nursery", 0, 25), ("tillering", 26, 70), ("panicle_initiation", 71, 100),
                      ("flowering", 101, 125), ("maturity", 126, 150)])
    return pd.DataFrame(rows)


# ---------------- stages ----------------

def test_stage_sowing_window_before_midpoint(calendar):
    st = {s.crop: s for s in stages_from_calendar(calendar, "Madurai", date(2026, 9, 29))}
    assert st["millets"].stage == "sowing" and st["millets"].days_after_sowing is None
    assert st["paddy"].stage == "tillering"
    assert st["groundnut"].stage == "pod_development"  # typical sowing ~8 Jul
    assert st["groundnut"].days_after_sowing == 84    # Segment 1's 366-day calendar


def test_stage_groundnut_flowering_mid_august(calendar):
    st = {s.crop: s for s in stages_from_calendar(calendar, "Salem", date(2026, 8, 14))}
    assert st["groundnut"].stage == "flowering_pegging"
    assert st["groundnut"].stage_group == "flowering"


def test_district_rows_override_all(calendar):
    tj = [s for s in stages_from_calendar(calendar, "Thanjavur", date(2026, 9, 29)) if s.crop == "paddy"]
    assert len(tj) == 1 and tj[0].calendar_district == "Thanjavur"


# ---------------- rule selection ----------------

@pytest.mark.parametrize("crop,stage,group,hazard,expected", [
    ("millets", "sowing", "sowing", "false_onset", "FO-SOW"),
    ("pulses", "sowing", "sowing", "false_onset", "FO-SOW"),
    ("groundnut", "flowering_pegging", "flowering", "dry_spell", "DS-FLOW-GN"),
    ("paddy", "flowering", "flowering", "dry_spell", "DS-FLOW-PADDY"),
    ("cotton", "flowering", "flowering", "dry_spell", "DS-FLOW-COTTON"),
    ("millets", "sowing", "sowing", "dry_spell", "DS-SOW"),       # stage beats crop-wide rule
    ("millets", "tillering", "vegetative", "dry_spell", "DS-MILLETS"),
    ("paddy", "maturity", "maturity", "heavy_rain", "HR-MAT-PADDY"),
    ("paddy", "tillering", "vegetative", "heavy_rain", "HR-PADDY"),
    ("pulses", "vegetative", "vegetative", "heavy_rain", "HR-ANY"),
    ("paddy", "sowing", "sowing", "heavy_rain", "HR-SOW"),
    ("paddy", "sowing", "sowing", "onset", "ON-SOW-PADDY"),
    ("groundnut", "flowering_pegging", "flowering", "revival", "RV-FLOW-GN"),
])
def test_select_rule(crop, stage, group, hazard, expected):
    assert select_rule(crop, stage, group, hazard).rule_id == expected


def test_no_rule_means_no_advisory():
    assert select_rule("cotton", "maturity", "maturity", "onset") is None
    assert select_rule("paddy", "maturity", "maturity", "active_phase") is None


def test_every_rule_has_both_languages():
    for r in RULES:
        for f in ("title_en", "title_ta", "text_en", "text_ta", "action_en", "action_ta"):
            assert getattr(r, f).strip(), (r.rule_id, f)
        assert r.severity in ("info", "watch", "warning")
        assert any("஀" <= ch <= "௿" for ch in r.text_ta), r.rule_id  # Tamil script


# ---------------- rendering ----------------

def _stage(calendar, crop, d=date(2026, 9, 29), district="Madurai"):
    return next(s for s in stages_from_calendar(calendar, district, d) if s.crop == crop)


def test_render_forecast_hazard_quotes_numbers(calendar):
    h = dict(district="Madurai", probability=0.9332, lead_week=2,
             window_start=date(2026, 10, 7), window_end=date(2026, 10, 13))
    out = render(select_rule("millets", "sowing", "sowing", "false_onset"), h, _stage(calendar, "millets"))
    assert out["title_en"] == "Don't sow millets yet"
    assert "93%" in out["text_en"] and "7 Oct–13 Oct" in out["text_en"]
    assert "மதுரை" in out["text_ta"] and "93%" in out["text_ta"] and "அக்." in out["text_ta"]


def test_render_observed_hazard_has_no_fake_probability(calendar):
    h = dict(district="Madurai", probability=1.0, lead_week=0,
             window_start=date(2026, 9, 15), window_end=date(2026, 9, 28))
    out = render(select_rule("millets", "sowing", "sowing", "false_onset"), h, _stage(calendar, "millets"))
    assert "100%" not in out["text_en"] and "high chance" in out["text_en"]
    assert "the coming days" in out["text_en"]
    assert "காலத்தில் காலத்தில்" not in out["text_ta"]


def test_resolve_conflicts_keeps_most_severe():
    base = dict(region_id=1, crop="millets", season="rabi")
    drafts = [dict(base, severity="info", hazard_type="revival", hazard_probability=0.9),
              dict(base, severity="warning", hazard_type="false_onset", hazard_probability=0.6),
              dict(base, severity="watch", hazard_type="dry_spell", hazard_probability=0.7),
              dict(base, crop="paddy", severity="info", hazard_type="onset", hazard_probability=0.5)]
    out = resolve_conflicts(drafts)
    assert len(out) == 2
    assert next(d for d in out if d["crop"] == "millets")["hazard_type"] == "false_onset"


# ---------------- channels ----------------

ADV = dict(district="Madurai", title_en="Don't sow millets yet", title_ta="இப்போது சிறுதானியங்கள் விதைக்க வேண்டாம்",
           text_en="Madurai: the rain so far is a false start. There is a 93% chance of a dry "
                   "spell in 7 Oct–13 Oct. Seeds sown now may dry out.",
           text_ta="மதுரை: இதுவரை பெய்த மழை நிலையான பருவமழைத் தொடக்கம் அல்ல. 7 அக்.–13 அக். "
                   "காலத்தில் வறட்சி நிலவ 93% வாய்ப்பு உள்ளது.",
           action_en="Hold your seed. Prepare the land and keep seed and fertiliser ready; sow "
                     "after the next good rain (at least 50–60 mm in total, soil wet to 30 cm).",
           action_ta="விதைகளைப் பாதுகாத்து வைக்கவும். நிலத்தைத் தயார் செய்து, அடுத்த நல்ல மழைக்குப் பின் விதைக்கவும்.",
           source_note="SAMPLE", simple_text_en=None)


def test_sms_is_trimmed_and_ascii():
    en, ta = format_message(ADV, "sms")
    assert len(en) <= SMS_MAX and len(ta) <= SMS_MAX
    en.encode("ascii")
    assert en.startswith("AgriVarsha Madurai: Don't sow millets yet")
    assert sms_segments(en) == 1 and sms_segments(ta) >= 1


def test_whatsapp_and_ivr_carry_full_text():
    wa_en, wa_ta = format_message(ADV, "whatsapp")
    assert ADV["text_en"] in wa_en and ADV["action_en"] in wa_en and "👍" in wa_en
    assert ADV["text_ta"] in wa_ta
    ivr_en, ivr_ta = format_message(ADV, "ivr")
    assert "press 1" in ivr_en and "93%" in ivr_en and "1-ஐ" in ivr_ta
    with pytest.raises(ValueError):
        format_message(ADV, "fax")


# ---------------- simulator funnel ----------------

def test_progress_is_monotonic_and_ordered():
    targets = (970, 900, 500)
    prev = None
    for i in range(0, 13):
        p = progress(i / 10, 1000, targets)
        assert p["sent"] >= p["delivered"] >= p["read"]
        if prev:
            for k in ("sent", "delivered", "read"):
                assert p[k] >= prev[k]
        prev = p
    assert progress(0.0, 1000, targets)["status"] == "queued"
    done = progress(1.2, 1000, targets)
    assert done["status"] == "completed"
    assert (done["sent"], done["delivered"], done["read"], done["failed"]) == (970, 900, 500, 100)
