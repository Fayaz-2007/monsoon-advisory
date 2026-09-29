# AgriVarsha — 5-minute demo script

**Before you start (2 min, off-stage):** double-click `run_demo.bat`, wait for the browser, open
the Demo panel (**D**) and click **Reset scenario & source** so you start from *Mock · today*.
Use a wide window (≥ 1280 px). Numbers below are from the 29 Sep 2026 database; the real
observed-rain numbers only change when the pipeline pulls new IMD data.

---

## 0:00 — The hook: a real false onset, from last week's data (60 s)

1. Landing page → **Officer Dashboard**. "38 districts of Tamil Nadu, one screen."
2. On the **risk map**, hover **Madurai** → tooltip shows *False onset*. Click it.
3. In **Hazard timeline** point at the first item with the green **Observed data** badge:
   > *False onset under way: 42.0 mm fell 20 Sep–21 Sep, and it has now been dry for 7 days since 22 Sep.*

   Say: **"This isn't a scenario — it's last week's real IMD rainfall.** Farmers who sowed on
   that first 42 mm have now had a week with no rain. That's exactly the loss we want to prevent."
4. Scroll to **Last 30 days of rain** (also badged *Observed data*): the two tall bars on
   20–21 Sep, then nothing. "Real IMD 0.25° grid, averaged over the district."
5. Point at **Crops in the field**: millets and pulses are in their sowing window right now.

## 1:00 — Scenarios: what the system does next (75 s)

Press **D** → Demo controls.

1. **False onset trap** (today). Back on Madurai: the forecast now shows heavy rain in week 1 and a
   dry week 2 (80% chance of a fully dry week) → *False onset* **Warning** and a 14-day dry spell.
   "A farmer would see week-1 rain and sow. The system says: don't."
2. **NE monsoon surge** (date jumps to **20 Oct**). Watch the map colours tween. Overview KPIs:
   3 warnings: **Chennai, Cuddalore, Nagapattinam**: 85% chance of a ≥ 64.5 mm day, week
   total up to 320 mm. Alerts feed shows the *why* sentence for each.
3. **Mid-season break** (date jumps to **14 Aug**). The groundnut belt (Salem, Namakkal,
   Tiruvannamalai, Viluppuram…) turns red: 14-day dry spell during **flowering and pegging**,
   with rain revival in week 3. Optional: click **▶ Play season** for a few seconds to show the
   map animate through the season, then pause.

## 2:15 — Officer workflow: approve → broadcast → phones (75 s)

1. Sidebar → **Advisory queue** (still in *Mid-season break*). Filter *Warning*, type
   `Salem` in the search box and open **"Critical: groundnut flowering needs water"**.
2. Flip **English / தமிழ்** tabs. Point at *Why this advisory* (the hazard's numbers) and
   *SAMPLE* source note: "Every advisory cites its rule and its data."
3. **Edit** → tweak the action text → Save (it goes back to draft; the **Audit trail** records
   who changed what). **Approve** → **Broadcast** → keep all 4 channels → **Send**.
4. Live delivery: counters tick from *Queued → Sent → Delivered → Read* per channel.
5. **Open delivery monitor**: three phones: the **SMS** (≤ 160 chars), the **WhatsApp** message
   with ticks turning blue, the **IVR call** with its spoken script. Toggle **தமிழ்**.
   "Same advisory, fitted to each channel. The gateway is simulated; the text is real."

## 3:30 — The farmer's view (45 s)

1. Sidebar → **Farmer app** (opens in a phone frame). It starts in **தமிழ்**.
2. Pick your district and crop (e.g. **Salem · groundnut**). Big weekly tiles with icons, today's advice.
3. Tap **🔊 கேளுங்கள் (Listen)**. If the laptop has no Tamil voice, it reads in English and
   says so on screen.
4. Tap **👍**, type a short comment, **அனுப்பு (Send)**. Switch back to the dashboard
   **Overview**: the *Farmer feedback · live* card shows it within seconds, tagged **app**.

## 4:15 — Real model and validated skill (45 s)

1. Demo panel → **Reset scenario & source**. In the header, click **Real model**.
   The subtitle changes to *Real model s2-lgbm-20260929-0304 · run of 28 Sep*; hazards and
   advisories are recomputed from the real forecast.
2. Sidebar → **System health**:
   - pipeline stage dots, 4.96 lakh daily rainfall rows, freshness (1 day), 8 of 9 quality checks passing;
   - **Validated model skill**: week-1 tercile RPSS **+0.030** (CI 0.009–0.049) overall,
     **+0.052** in the SW monsoon: skill above climatology, proven by the CI. Weeks 2–4 sit
     at or below zero.
   Say: "We show the model's honest skill, with confidence intervals. Where it has no skill,
   the forecasts are labelled *Low confidence* and never trigger a warning on their own."

## Close (15 s)

"Real observations catch false onsets today; forecasts extend that to 4 weeks as the model
improves. Officers stay in control, and farmers get it in Tamil, by voice, on any phone."

---

## Likely judge questions

**How accurate is it?**
Validated on 2011–2025 with year-block bootstrap CIs (System health). Week-1 tercile
skill is positive and significant (RPSS +0.03 overall, +0.05 in the SW monsoon); weeks 2–4 are
near climatology, like most operational extended-range forecasts over South India. The design
is honest about this. Confidence levels follow the validated lower bound, low-confidence
forecasts cannot raise warnings alone, and the strongest alerts come from **observed** rain
(false onsets, dry spells), which needs no forecast skill at all. The rules and
thresholds are unit-tested (126 tests).

**Is this real data or a mock-up?**
Boundaries, 35 years of IMD rainfall, climatology, the crop calendar, the pipeline status and
the model skill are real. The forecasts are mock by default for a smooth demo and switch to the
real model with one click (*Real model*). Farmer counts and the SMS/WhatsApp/IVR gateway are
simulated, each behind a named switch (see *Demo mode vs real mode* in the README).

**Does it scale?**
All of Tamil Nadu (38 districts) is computed in a few seconds per date, and the rules run per
district independently. The pipeline already supports block-level boundaries (`regions.level =
block`) and another state by changing its `.env` region settings. Delivery would go through
any bulk SMS / WhatsApp Business / IVR provider API that reports delivery receipts.

**What does it cost to run?**
The data is open: IMD gridded rainfall, NOAA/BoM climate indices, geoBoundaries. The stack is
open source (PostgreSQL/PostGIS, Python, LightGBM, React) and runs on one small server. The
LLM is optional (templates work without it). The main running cost would be messaging.
Bulk SMS and voice minutes are priced per message by the provider, so that cost grows with the
number of farmers reached (get quotes from a DLT-registered provider).

**Where does the advice come from?**
A crop × stage × hazard rule table, drafted from TNAU Agritech and ICAR-CRIDA contingency-plan
practice. It is marked **SAMPLE** until agronomists validate it. The Tamil text is pre-written and
flagged `tamil_reviewed = false` until a reviewer ticks it in the edit dialog. Nothing reaches
farmers without an officer's approval.

**What if the model is wrong?**
Every alert shows its probability, confidence and a plain *why* with the numbers. Officers
review before sending, and farmers' 👍/👎 comes back to the dashboard. Forecasts are re-issued
daily and advisories re-draft automatically when hazards change.
