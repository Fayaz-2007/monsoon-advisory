"""MOCK farmer registry: registered farmers per district × crop, and channel reach.

Behind FARMER_COUNT_SOURCE=mock. Replace ``farmer_counts`` with a query against a real
registry (e.g. the state's farmer database) to go live; its callers only need the numbers.
Counts are deterministic: district area × a density × a crop share that reflects the
main growing belts of Tamil Nadu, with ±15% seeded jitter.
"""

from __future__ import annotations

import hashlib

CROPS = ("paddy", "groundnut", "cotton", "millets", "pulses")

# Registered farmers per km² of district area (all crops).
_DENSITY = 38.0

_BASE_SHARE = {"paddy": 0.30, "groundnut": 0.14, "cotton": 0.06, "millets": 0.10, "pulses": 0.10}
_BELTS = {
    "paddy": {"Thanjavur", "Thiruvarur", "Nagapattinam", "Mayiladuthurai", "Tiruchirappalli",
              "Cuddalore", "Viluppuram", "Kancheepuram", "Thiruvallur", "Chengalputtu"},
    "groundnut": {"Tiruvannamalai", "Viluppuram", "Vellore", "Ranipet", "Kallakurichi",
                  "Salem", "Namakkal", "Pudukkottai", "Krishnagiri", "Dharmapuri"},
    "cotton": {"Virudhunagar", "Perambalur", "Salem", "Thoothukkudi", "Madurai", "Theni",
               "Ramanathapuram", "Tirunelveli", "Ariyalur"},
    "millets": {"Dharmapuri", "Krishnagiri", "Salem", "Madurai", "Virudhunagar", "Theni",
                "Dindigul", "Tiruppur", "Coimbatore", "Namakkal"},
    "pulses": {"Viluppuram", "Cuddalore", "Thoothukkudi", "Virudhunagar", "Tirunelveli",
               "Pudukkottai", "Thiruvarur", "Nagapattinam"},
}
_LOW_AGRI = {"Chennai": 0.05, "The Nilgiris": 0.25}

# Share of registered farmers reachable on each channel (MOCK).
CHANNEL_REACH = {"app": 0.22, "sms": 0.92, "whatsapp": 0.48, "ivr": 0.35}


def _jitter(*parts: object) -> float:
    h = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return 0.85 + 0.30 * (int.from_bytes(h[:4], "little") / 2**32)


def farmer_counts(district: str, area_km2: float, crop: str) -> int:
    """Registered farmers growing ``crop`` in ``district`` (MOCK)."""
    share = _BASE_SHARE.get(crop, 0.05) * (2.4 if district in _BELTS.get(crop, set()) else 1.0)
    factor = _LOW_AGRI.get(district, 1.0)
    return int(round(area_km2 * _DENSITY * share * factor * _jitter(district, crop)))


def district_total(district: str, area_km2: float) -> int:
    return sum(farmer_counts(district, area_km2, c) for c in CROPS)
