"""Channel formatting (Segment 7): the REAL advisory text, fitted to each channel.

* ``sms``      ≤ 160 characters per language (English is GSM-7-safe ASCII; Tamil needs
               Unicode SMS, so 160 Tamil characters = 3 concatenated segments)
* ``whatsapp`` full text with title, action and source note
* ``ivr``      a spoken script with keypad prompts (1 repeat, 2 useful, 3 not useful)
* ``app``      full text (title, advice, action)
"""

from __future__ import annotations

import math
from typing import Any

from app.advisory.rules import TA_DISTRICTS

CHANNELS = ("app", "sms", "whatsapp", "ivr")
SMS_MAX = 160

_ASCII = {"≥": ">=", "≤": "<=", "–": "-", "—": "-", "’": "'", "‘": "'", "“": '"', "”": '"',
          "…": "...", "°": " deg", "×": "x"}


def ascii_safe(s: str) -> str:
    for k, v in _ASCII.items():
        s = s.replace(k, v)
    return s.encode("ascii", "ignore").decode()


def trim(s: str, limit: int) -> str:
    s = " ".join(s.split())
    if len(s) <= limit:
        return s
    cut = s[: limit - 3]
    if " " in cut[limit // 2:]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:.") + "..."


def sms_segments(text: str) -> int:
    """Concatenated SMS segments: GSM-7 153 chars/segment (160 if single), UCS-2 67 (70)."""
    try:
        text.encode("ascii")
        single, multi = 160, 153
    except UnicodeEncodeError:
        single, multi = 70, 67
    return 1 if len(text) <= single else math.ceil(len(text) / multi)


def format_message(adv: dict[str, Any], channel: str) -> tuple[str, str]:
    """(English, Tamil) content for one channel."""
    district = adv["district"]
    district_ta = TA_DISTRICTS.get(district, district)
    text_en = adv.get("simple_text_en") or f"{adv['text_en']} {adv['action_en']}"
    if channel == "sms":
        en = trim(ascii_safe(f"AgriVarsha {district}: {adv['title_en']}. {adv['action_en']}"), SMS_MAX)
        ta = trim(f"அக்ரிவர்ஷா {district_ta}: {adv['title_ta']}. {adv['action_ta']}", SMS_MAX)
        return en, ta
    if channel == "whatsapp":
        en = (f"🌦️ *AgriVarsha advisory: {district}*\n*{adv['title_en']}*\n\n{adv['text_en']}\n\n"
              f"✅ *What to do:* {adv['action_en']}\n\n_{adv['source_note']}_\n"
              "Was this useful? Reply 👍 or 👎")
        ta = (f"🌦️ *அக்ரிவர்ஷா ஆலோசனை: {district_ta}*\n*{adv['title_ta']}*\n\n{adv['text_ta']}\n\n"
              f"✅ *செய்ய வேண்டியது:* {adv['action_ta']}\n\n"
              "இது பயனுள்ளதா? 👍 அல்லது 👎 என பதிலளிக்கவும்")
        return en, ta
    if channel == "ivr":
        en = (f"Vanakkam. This is the AgriVarsha weather advisory for {district} district. "
              f"{ascii_safe(text_en)} "
              "To hear this again, press 1. If this advice was useful, press 2. If not, press 3.")
        ta = (f"வணக்கம். இது {district_ta} மாவட்டத்திற்கான அக்ரிவர்ஷா வானிலை ஆலோசனை. "
              f"{adv['text_ta']} {adv['action_ta']} "
              "மீண்டும் கேட்க 1-ஐ அழுத்தவும். இந்த ஆலோசனை பயனுள்ளதாக இருந்தால் 2-ஐயும், "
              "இல்லையென்றால் 3-ஐயும் அழுத்தவும்.")
        return en, ta
    if channel == "app":
        en = f"{adv['title_en']}\n{text_en}"
        ta = f"{adv['title_ta']}\n{adv['text_ta']} {adv['action_ta']}"
        return en, ta
    raise ValueError(f"unknown channel {channel!r}; use one of {', '.join(CHANNELS)}")


def preview(adv: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for ch in CHANNELS:
        en, ta = format_message(adv, ch)
        item: dict[str, Any] = {"en": en, "ta": ta, "chars_en": len(en), "chars_ta": len(ta)}
        if ch == "sms":
            item["segments_en"], item["segments_ta"] = sms_segments(en), sms_segments(ta)
        out[ch] = item
    return out
