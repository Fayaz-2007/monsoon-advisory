"""Advisory rule table (Segment 4): crop × stage × hazard → advice in English and Tamil.

Selection: every rule matching the hazard type (and subtype, if the rule sets one) is scored
by specificity — exact stage +6, stage group +3, exact crop +2, wildcards 0 — and the highest
score wins (ties: first in the table). Stage beats crop, so a generic "don't sow yet" rule
outranks a crop-wide rule written for crops already in the field. No matching rule → no advisory for that crop.

Texts are templates filled with real numbers from the hazard. The guidance is a SAMPLE
drawn from public TNAU Agritech / ICAR-CRIDA contingency-plan practices and must be reviewed
by agronomists before use; the Tamil text is pre-written and flagged ``tamil_reviewed=false``.
"""

from __future__ import annotations

from dataclasses import dataclass

SOURCE_NOTE = ("Based on TNAU Agritech Portal / ICAR-CRIDA district contingency-plan guidance: "
               "SAMPLE, not yet validated by agronomists.")

CROP_NAMES = {
    "paddy": ("paddy", "நெல்"),
    "groundnut": ("groundnut", "நிலக்கடலை"),
    "cotton": ("cotton", "பருத்தி"),
    "millets": ("millets", "சிறுதானியங்கள்"),
    "pulses": ("pulses", "பயறு வகைகள்"),
}
STAGE_NAMES = {
    "sowing": ("sowing", "விதைப்பு"),
    "nursery": ("nursery", "நாற்றங்கால்"),
    "emergence": ("emergence", "முளைப்பு"),
    "tillering": ("tillering", "தூர் கட்டும்"),
    "vegetative": ("vegetative", "வளர்ச்சி"),
    "squaring": ("squaring", "சப்பை உருவாகும்"),
    "panicle_initiation": ("panicle initiation", "கதிர் உருவாகும்"),
    "flowering": ("flowering", "பூக்கும்"),
    "flowering_pegging": ("flowering and pegging", "பூத்தல் மற்றும் விழுது இறங்கும்"),
    "pod_development": ("pod development", "காய் உருவாகும்"),
    "boll_development": ("boll development", "காய் வளர்ச்சி"),
    "grain_filling_maturity": ("grain filling", "மணி நிரம்பும்"),
    "pod_filling_maturity": ("pod filling", "காய் நிரம்பும்"),
    "maturity": ("maturity", "முதிர்ச்சி"),
}
TA_DISTRICTS = {
    "Ariyalur": "அரியலூர்", "Chengalputtu": "செங்கல்பட்டு", "Chennai": "சென்னை",
    "Coimbatore": "கோயம்புத்தூர்", "Cuddalore": "கடலூர்", "Dharmapuri": "தருமபுரி",
    "Dindigul": "திண்டுக்கல்", "Erode": "ஈரோடு", "Kallakurichi": "கள்ளக்குறிச்சி",
    "Kancheepuram": "காஞ்சிபுரம்", "Kanniyakumari": "கன்னியாகுமரி", "Karur": "கரூர்",
    "Krishnagiri": "கிருஷ்ணகிரி", "Madurai": "மதுரை", "Mayiladuthurai": "மயிலாடுதுறை",
    "Nagapattinam": "நாகப்பட்டினம்", "Namakkal": "நாமக்கல்", "Perambalur": "பெரம்பலூர்",
    "Pudukkottai": "புதுக்கோட்டை", "Ramanathapuram": "இராமநாதபுரம்", "Ranipet": "இராணிப்பேட்டை",
    "Salem": "சேலம்", "Sivaganga": "சிவகங்கை", "Tenkasi": "தென்காசி", "Thanjavur": "தஞ்சாவூர்",
    "The Nilgiris": "நீலகிரி", "Theni": "தேனி", "Thiruvallur": "திருவள்ளூர்",
    "Thiruvarur": "திருவாரூர்", "Thoothukkudi": "தூத்துக்குடி",
    "Tiruchirappalli": "திருச்சிராப்பள்ளி", "Tirunelveli": "திருநெல்வேலி",
    "Tirupathur": "திருப்பத்தூர்", "Tiruppur": "திருப்பூர்", "Tiruvannamalai": "திருவண்ணாமலை",
    "Vellore": "வேலூர்", "Viluppuram": "விழுப்புரம்", "Virudhunagar": "விருதுநகர்",
}


@dataclass(frozen=True)
class AdviceRule:
    rule_id: str
    crop: str            # crop name or "*"
    stage: str           # exact stage, stage group, or "*"
    hazard_type: str
    severity: str        # info | watch | warning
    title_en: str
    title_ta: str
    text_en: str
    text_ta: str
    action_en: str
    action_ta: str
    subtype: str | None = None


R = AdviceRule
# Placeholders: {district} {district_ta} {crop} {crop_ta} {stage} {stage_ta} {window} {prob}
RULES: list[AdviceRule] = [
    # ---------------- false onset ----------------
    R("FO-SOW", "*", "sowing", "false_onset", "warning",
      "Don't sow {crop} yet", "இப்போது {crop_ta} விதைக்க வேண்டாம்",
      "{district}: the rain so far is a false start. There is a {prob} chance of a dry spell "
      "in {window}. Seeds sown now may dry out. Wait until the soil is wet to about 30 cm "
      "(around 50–60 mm of rain in total) before sowing {crop}.",
      "{district_ta}: இதுவரை பெய்த மழை நிலையான பருவமழைத் தொடக்கம் அல்ல. {window} காலத்தில் "
      "வறட்சி நிலவ {prob} வாய்ப்பு உள்ளது. இப்போது விதைத்தால் விதைகள் காய்ந்துவிடலாம். மண் "
      "சுமார் 30 செ.மீ ஆழம் வரை ஈரமான பிறகு (மொத்தம் 50–60 மி.மீ மழை) {crop_ta} விதைக்கவும்.",
      "Hold your seed. Prepare the land and keep seed and fertiliser ready; sow after the "
      "next good rain.",
      "விதைகளைப் பாதுகாத்து வைக்கவும். நிலத்தைத் தயார் செய்து, அடுத்த நல்ல மழைக்குப் பின் விதைக்கவும்."),
    R("FO-EST", "*", "establishment", "false_onset", "warning",
      "Young {crop} at risk from dry spell", "இளம் {crop_ta} பயிருக்கு வறட்சி அபாயம்",
      "{district}: after the first rains, a dry spell is likely in {window} ({prob} chance). "
      "Young {crop} plants may wilt.",
      "{district_ta}: முதல் மழைக்குப் பின் {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு "
      "உள்ளது. இளம் {crop_ta} செடிகள் வாடக்கூடும்.",
      "Give one life-saving irrigation if water is available, mulch between rows, and "
      "gap-fill once rain returns.",
      "தண்ணீர் இருந்தால் ஒரு உயிர்காக்கும் பாசனம் கொடுக்கவும், வரிசைகளுக்கு இடையே மூடாக்கு "
      "இடவும், மழை திரும்பியதும் இடைவெளிகளை நிரப்பவும்."),
    R("FO-ANY", "*", "*", "false_onset", "watch",
      "Rain not yet steady", "மழை இன்னும் நிலையாகவில்லை",
      "{district}: the monsoon rain is not steady yet; {prob} chance of a dry spell in "
      "{window}.",
      "{district_ta}: பருவமழை இன்னும் நிலையாகவில்லை; {window} காலத்தில் வறட்சி ஏற்பட {prob} "
      "வாய்ப்பு உள்ளது.",
      "Conserve soil moisture: mulch and avoid deep ploughing.",
      "மண் ஈரத்தைப் பாதுகாக்கவும்: மூடாக்கு இடவும், ஆழமாக உழ வேண்டாம்."),

    # ---------------- onset ----------------
    R("ON-SOW-PADDY", "paddy", "sowing", "onset", "info",
      "Prepare the paddy nursery", "நெல் நாற்றங்கால் தயார் செய்யவும்",
      "{district}: onset rain in {window} ({prob} chance). Good time to prepare the paddy "
      "nursery.",
      "{district_ta}: {window} காலத்தில் பருவமழை தொடங்க {prob} வாய்ப்பு. நெல் நாற்றங்கால் "
      "தயார் செய்ய ஏற்ற நேரம்.",
      "Prepare nursery beds and treat seed (e.g. Pseudomonas 10 g/kg) before sowing.",
      "நாற்றங்கால் படுக்கைகளைத் தயார் செய்து, விதைக்கும் முன் விதை நேர்த்தி செய்யவும் "
      "(எ.கா. சூடோமோனாஸ் 10 கி/கிலோ)."),
    R("ON-SOW", "*", "sowing", "onset", "info",
      "Sowing rain expected for {crop}", "{crop_ta} விதைப்புக்கு மழை எதிர்பார்ப்பு",
      "{district}: onset rain in {window} ({prob} chance). Get ready to sow {crop} once the "
      "soil is moist to about 30 cm.",
      "{district_ta}: {window} காலத்தில் பருவமழை தொடங்க {prob} வாய்ப்பு. மண் சுமார் 30 செ.மீ "
      "ஈரமானதும் {crop_ta} விதைக்கத் தயாராகவும்.",
      "Keep treated seed and basal fertiliser ready; sow within 2–3 days of good rain.",
      "நேர்த்தி செய்த விதையும் அடியுரமும் தயாராக வைக்கவும்; நல்ல மழைக்குப் பின் 2–3 நாட்களுக்குள் விதைக்கவும்."),

    # ---------------- dry spell ----------------
    R("DS-SOW", "*", "sowing", "dry_spell", "watch",
      "Delay sowing {crop}", "{crop_ta} விதைப்பைத் தள்ளிப்போடவும்",
      "{district}: {prob} chance of a dry spell in {window}. Sowing {crop} now is risky.",
      "{district_ta}: {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு. இப்போது {crop_ta} "
      "விதைப்பது அபாயம்.",
      "Wait for the dry spell to pass; sow when the soil is moist.",
      "வறட்சி முடியும் வரை காத்திருந்து, மண் ஈரமானதும் விதைக்கவும்."),
    R("DS-EST-PADDY", "paddy", "establishment", "dry_spell", "warning",
      "Protect the paddy nursery", "நெல் நாற்றங்காலைப் பாதுகாக்கவும்",
      "{district}: {prob} chance of a dry spell in {window} during the {stage} stage.",
      "{district_ta}: {stage_ta} பருவத்தில் {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு.",
      "Keep nursery beds moist; delay transplanting until enough water is available.",
      "நாற்றங்காலை ஈரமாக வைக்கவும்; போதுமான தண்ணீர் கிடைக்கும் வரை நடவைத் தள்ளிப்போடவும்."),
    R("DS-EST", "*", "establishment", "dry_spell", "warning",
      "Dry spell: protect young {crop}", "வறட்சி: இளம் {crop_ta} பயிரைப் பாதுகாக்கவும்",
      "{district}: {prob} chance of a dry spell in {window} while {crop} is at {stage}.",
      "{district_ta}: {crop_ta} {stage_ta} பருவத்தில் இருக்கும்போது {window} காலத்தில் "
      "வறட்சி ஏற்பட {prob} வாய்ப்பு.",
      "Give a light protective irrigation, mulch with crop residue, and remove weeds.",
      "லேசான பாதுகாப்புப் பாசனம் கொடுக்கவும், பயிர்க் கழிவுகளால் மூடாக்கு இடவும், களை எடுக்கவும்."),
    R("DS-VEG-PADDY", "paddy", "vegetative", "dry_spell", "watch",
      "Save water in paddy", "நெல் வயலில் நீரைச் சேமிக்கவும்",
      "{district}: {prob} chance of a dry spell in {window} during tillering.",
      "{district_ta}: தூர் கட்டும் பருவத்தில் {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு.",
      "Use alternate wetting and drying; keep about 2.5 cm of water when irrigating.",
      "மாற்று நனைத்தல்-காய்தல் முறையைப் பின்பற்றவும்; பாசனத்தின்போது சுமார் 2.5 செ.மீ நீர் வைக்கவும்."),
    R("DS-FLOW-PADDY", "paddy", "flowering", "dry_spell", "warning",
      "Critical: water paddy at {stage}", "முக்கியம்: {stage_ta} பருவ நெல்லுக்கு நீர்",
      "{district}: {prob} chance of a dry spell in {window} at {stage}. Water stress now "
      "causes the biggest yield loss.",
      "{district_ta}: {stage_ta} பருவத்தில் {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு. "
      "இப்போது நீர்ப் பற்றாக்குறை அதிக மகசூல் இழப்பை ஏற்படுத்தும்.",
      "Keep about 5 cm of standing water through flowering; give priority to this field.",
      "பூக்கும் பருவம் முழுவதும் சுமார் 5 செ.மீ நீர் நிறுத்தவும்; இந்த வயலுக்கு முன்னுரிமை கொடுக்கவும்."),
    R("DS-FLOW-GN", "groundnut", "flowering_pegging", "dry_spell", "warning",
      "Critical: groundnut flowering needs water", "முக்கியம்: பூக்கும் நிலக்கடலைக்கு நீர் தேவை",
      "{district}: {prob} chance of a dry spell in {window} during flowering and pegging. "
      "Pegs cannot enter dry soil and pods will not form.",
      "{district_ta}: பூத்தல் மற்றும் விழுது இறங்கும் பருவத்தில் {window} காலத்தில் வறட்சி ஏற்பட "
      "{prob} வாய்ப்பு. காய்ந்த மண்ணில் விழுதுகள் இறங்காது, காய்கள் உருவாகாது.",
      "Give protective irrigation now. Apply gypsum (400 kg/ha) only when the soil is moist; "
      "do not disturb the soil around plants.",
      "இப்போதே பாதுகாப்புப் பாசனம் கொடுக்கவும். மண் ஈரமாக இருக்கும்போது மட்டும் ஜிப்சம் "
      "(எக்டருக்கு 400 கிலோ) இடவும்; செடிகளைச் சுற்றி மண்ணைக் கிளற வேண்டாம்."),
    R("DS-FILL-GN", "groundnut", "grain_fill", "dry_spell", "warning",
      "Groundnut pods need water", "நிலக்கடலை காய்களுக்கு நீர் தேவை",
      "{district}: {prob} chance of a dry spell in {window} during pod development.",
      "{district_ta}: காய் உருவாகும் பருவத்தில் {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு.",
      "Irrigate lightly to keep the pod zone moist; this protects pod filling.",
      "காய் பகுதியை ஈரமாக வைக்க லேசாகப் பாசனம் செய்யவும்; இது காய் நிரம்புவதைப் பாதுகாக்கும்."),
    R("DS-FLOW-COTTON", "cotton", "flowering", "dry_spell", "warning",
      "Cotton: prevent flower and boll shedding", "பருத்தி: பூ, காய் உதிர்வைத் தடுக்கவும்",
      "{district}: {prob} chance of a dry spell in {window} at flowering.",
      "{district_ta}: பூக்கும் பருவத்தில் {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு.",
      "Irrigate if possible and spray 2% DAP with 1% KCl to reduce shedding.",
      "முடிந்தால் பாசனம் செய்து, உதிர்வைக் குறைக்க 2% டிஏபி மற்றும் 1% பொட்டாஷ் கரைசல் தெளிக்கவும்."),
    R("DS-FLOW-PULSES", "pulses", "flowering", "dry_spell", "warning",
      "Pulses: protect flowering", "பயறு: பூக்களைப் பாதுகாக்கவும்",
      "{district}: {prob} chance of a dry spell in {window} at flowering.",
      "{district_ta}: பூக்கும் பருவத்தில் {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு.",
      "Spray 2% DAP at flowering and give one irrigation if water is available.",
      "பூக்கும் பருவத்தில் 2% டிஏபி தெளித்து, தண்ணீர் இருந்தால் ஒரு பாசனம் கொடுக்கவும்."),
    R("DS-MILLETS", "millets", "*", "dry_spell", "watch",
      "Millets: conserve moisture", "சிறுதானியங்கள்: ஈரத்தைச் சேமிக்கவும்",
      "{district}: {prob} chance of a dry spell in {window}. Millets tolerate short dry "
      "spells but lose yield at {stage}.",
      "{district_ta}: {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு. சிறுதானியங்கள் குறுகிய "
      "வறட்சியைத் தாங்கும், ஆனால் {stage_ta} பருவத்தில் மகசூல் குறையும்.",
      "Do inter-cultivation to break the soil crust and mulch between rows.",
      "மண் மேலோட்டை உடைக்க இடை உழவு செய்து, வரிசைகளுக்கு இடையே மூடாக்கு இடவும்."),
    R("DS-VEG", "*", "vegetative", "dry_spell", "watch",
      "Dry spell: conserve moisture in {crop}", "வறட்சி: {crop_ta} வயலில் ஈரத்தைச் சேமிக்கவும்",
      "{district}: {prob} chance of a dry spell in {window} at {stage}.",
      "{district_ta}: {stage_ta} பருவத்தில் {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு.",
      "Weed and mulch; a 1% potash (KCl) spray helps plants tolerate dry weather.",
      "களை எடுத்து மூடாக்கு இடவும்; 1% பொட்டாஷ் கரைசல் தெளிப்பது வறட்சியைத் தாங்க உதவும்."),
    R("DS-FLOW", "*", "flowering", "dry_spell", "warning",
      "Critical: dry spell at {stage}", "முக்கியம்: {stage_ta} பருவத்தில் வறட்சி",
      "{district}: {prob} chance of a dry spell in {window} while {crop} is at {stage}.",
      "{district_ta}: {crop_ta} {stage_ta} பருவத்தில் இருக்கும்போது {window} காலத்தில் "
      "வறட்சி ஏற்பட {prob} வாய்ப்பு.",
      "Give protective irrigation now; flowering is the most sensitive stage.",
      "இப்போதே பாதுகாப்புப் பாசனம் கொடுக்கவும்; பூக்கும் பருவமே மிக உணர்திறன் வாய்ந்தது."),
    R("DS-FILL", "*", "grain_fill", "dry_spell", "watch",
      "Dry spell during {stage}", "{stage_ta} பருவத்தில் வறட்சி",
      "{district}: {prob} chance of a dry spell in {window} during {stage}.",
      "{district_ta}: {stage_ta} பருவத்தில் {window} காலத்தில் வறட்சி ஏற்பட {prob} வாய்ப்பு.",
      "Irrigate if water is available to protect grain and pod filling.",
      "மணி/காய் நிரம்புவதைப் பாதுகாக்க, தண்ணீர் இருந்தால் பாசனம் செய்யவும்."),
    R("DS-MAT", "*", "maturity", "dry_spell", "info",
      "Dry weather: good for harvest", "வறண்ட வானிலை: அறுவடைக்கு ஏற்றது",
      "{district}: dry weather likely in {window} ({prob} chance), good for harvesting "
      "mature {crop}.",
      "{district_ta}: {window} காலத்தில் வறண்ட வானிலை ({prob} வாய்ப்பு); முதிர்ந்த {crop_ta} "
      "அறுவடைக்கு ஏற்றது.",
      "Harvest at maturity and dry the produce well before storage.",
      "முதிர்ந்ததும் அறுவடை செய்து, சேமிப்பதற்கு முன் நன்றாக உலர்த்தவும்."),

    # ---------------- heavy rain ----------------
    R("HR-SOW", "*", "sowing", "heavy_rain", "watch",
      "Postpone sowing: heavy rain", "கனமழை: விதைப்பைத் தள்ளிப்போடவும்",
      "{district}: {prob} chance of heavy rain (≥ 64.5 mm in a day) in {window}. Fresh seed "
      "can wash away or rot.",
      "{district_ta}: {window} காலத்தில் கனமழை (ஒரு நாளில் 64.5 மி.மீக்கு மேல்) பெய்ய {prob} "
      "வாய்ப்பு. புதிதாக விதைத்த விதைகள் அடித்துச் செல்லப்படலாம் அல்லது அழுகலாம்.",
      "Sow after the heavy rain passes; open drainage channels in the field first.",
      "கனமழை முடிந்த பின் விதைக்கவும்; முதலில் வயலில் வடிகால் வாய்க்கால்களைத் திறக்கவும்."),
    R("HR-MAT-PADDY", "paddy", "maturity", "heavy_rain", "warning",
      "Harvest ready paddy before heavy rain", "கனமழைக்கு முன் முதிர்ந்த நெல்லை அறுவடை செய்யவும்",
      "{district}: {prob} chance of heavy rain in {window}. Mature paddy may lodge and "
      "grains may sprout.",
      "{district_ta}: {window} காலத்தில் கனமழை பெய்ய {prob} வாய்ப்பு. முதிர்ந்த நெல் சாயலாம், "
      "மணிகள் முளைக்கலாம்.",
      "Harvest mature fields early and move grain to dry storage. If lodged panicles get "
      "wet, a 5% common-salt spray limits sprouting.",
      "முதிர்ந்த வயல்களை முன்கூட்டியே அறுவடை செய்து தானியத்தை உலர்ந்த இடத்தில் சேமிக்கவும். "
      "சாய்ந்த கதிர்கள் நனைந்தால், 5% உப்புக் கரைசல் தெளிப்பது முளைப்பைக் குறைக்கும்."),
    R("HR-MAT", "*", "maturity", "heavy_rain", "warning",
      "Harvest {crop} before heavy rain", "கனமழைக்கு முன் {crop_ta} அறுவடை செய்யவும்",
      "{district}: {prob} chance of heavy rain in {window} while {crop} is mature.",
      "{district_ta}: {crop_ta} முதிர்ந்த நிலையில் {window} காலத்தில் கனமழை பெய்ய {prob} வாய்ப்பு.",
      "Harvest early and store the produce in a dry, covered place.",
      "முன்கூட்டியே அறுவடை செய்து, விளைபொருளை உலர்ந்த, மூடிய இடத்தில் சேமிக்கவும்."),
    R("HR-PADDY", "paddy", "*", "heavy_rain", "watch",
      "Heavy rain: drain paddy fields", "கனமழை: நெல் வயலில் நீரை வடிக்கவும்",
      "{district}: {prob} chance of heavy rain (≥ 64.5 mm in a day) in {window} during "
      "{stage}.",
      "{district_ta}: {stage_ta} பருவத்தில் {window} காலத்தில் கனமழை (ஒரு நாளில் 64.5 "
      "மி.மீக்கு மேல்) பெய்ய {prob} வாய்ப்பு.",
      "Strengthen bunds, keep drainage open, and postpone urea top-dressing and sprays "
      "until the rain stops.",
      "வரப்புகளை வலுப்படுத்தவும், வடிகாலைத் திறந்து வைக்கவும், மழை நிற்கும் வரை யூரியா மேலுரம் "
      "மற்றும் தெளிப்புகளைத் தள்ளிப்போடவும்."),
    R("HR-GN", "groundnut", "*", "heavy_rain", "watch",
      "Heavy rain: drain groundnut fields", "கனமழை: நிலக்கடலை வயலில் நீரை வடிக்கவும்",
      "{district}: {prob} chance of heavy rain in {window}. Waterlogging causes pod and "
      "root rot.",
      "{district_ta}: {window} காலத்தில் கனமழை பெய்ய {prob} வாய்ப்பு. நீர் தேங்கினால் காய் "
      "மற்றும் வேர் அழுகல் ஏற்படும்.",
      "Open drainage furrows before the rain; do not irrigate this week.",
      "மழைக்கு முன் வடிகால் சால்களைத் திறக்கவும்; இந்த வாரம் பாசனம் செய்ய வேண்டாம்."),
    R("HR-COTTON", "cotton", "*", "heavy_rain", "watch",
      "Heavy rain: protect cotton", "கனமழை: பருத்தியைப் பாதுகாக்கவும்",
      "{district}: {prob} chance of heavy rain in {window}. Wet conditions raise the risk "
      "of boll rot.",
      "{district_ta}: {window} காலத்தில் கனமழை பெய்ய {prob} வாய்ப்பு. ஈரப்பதம் காய் அழுகல் "
      "அபாயத்தை அதிகரிக்கும்.",
      "Drain the field and postpone fertiliser and pesticide sprays until after the rain.",
      "வயலில் நீரை வடித்து, மழைக்குப் பின் வரை உரம் மற்றும் பூச்சிக்கொல்லி தெளிப்பைத் தள்ளிப்போடவும்."),
    R("HR-ANY", "*", "*", "heavy_rain", "watch",
      "Heavy rain expected", "கனமழை எதிர்பார்ப்பு",
      "{district}: {prob} chance of heavy rain (≥ 64.5 mm in a day) in {window}.",
      "{district_ta}: {window} காலத்தில் கனமழை (ஒரு நாளில் 64.5 மி.மீக்கு மேல்) பெய்ய {prob} வாய்ப்பு.",
      "Clear drainage channels and postpone fertiliser and pesticide application.",
      "வடிகால் வாய்க்கால்களைச் சுத்தம் செய்து, உரம் மற்றும் பூச்சிக்கொல்லி இடுவதைத் தள்ளிப்போடவும்."),

    # ---------------- active phase ----------------
    R("AP-SOW", "*", "sowing", "active_phase", "info",
      "Good conditions to sow {crop}", "{crop_ta} விதைக்க நல்ல சூழல்",
      "{district}: an active monsoon spell is likely in {window} ({prob} chance of "
      "above-normal rain).",
      "{district_ta}: {window} காலத்தில் பருவமழை தீவிரமாக இருக்க வாய்ப்பு (இயல்பை விட அதிக "
      "மழைக்கு {prob} வாய்ப்பு).",
      "Sow {crop} with treated seed between downpours, once the soil is moist.",
      "மண் ஈரமானதும், மழை இடைவேளையில் நேர்த்தி செய்த விதையுடன் {crop_ta} விதைக்கவும்."),
    R("AP-VEG", "*", "vegetative", "active_phase", "info",
      "Use the wet spell for {crop}", "{crop_ta} பயிருக்கு ஈரமான காலத்தைப் பயன்படுத்தவும்",
      "{district}: above-normal rain favoured in {window} ({prob} chance).",
      "{district_ta}: {window} காலத்தில் இயல்பை விட அதிக மழைக்கு {prob} வாய்ப்பு.",
      "Apply top-dressing in a dry gap between rains; keep drainage open.",
      "மழைகளுக்கு இடையிலான வறண்ட இடைவேளையில் மேலுரம் இடவும்; வடிகாலைத் திறந்து வைக்கவும்."),

    # ---------------- revival ----------------
    R("RV-SOW", "*", "sowing", "revival", "info",
      "Rain returning: plan {crop} sowing", "மழை திரும்புகிறது: {crop_ta} விதைப்பைத் திட்டமிடவும்",
      "{district}: useful rain (≥ 20 mm) is likely to return in {window} ({prob} chance).",
      "{district_ta}: {window} காலத்தில் பயனுள்ள மழை (20 மி.மீக்கு மேல்) திரும்ப {prob} வாய்ப்பு.",
      "Keep seed ready and sow {crop} once the soil is moist after this rain.",
      "விதையைத் தயாராக வைத்து, இந்த மழைக்குப் பின் மண் ஈரமானதும் {crop_ta} விதைக்கவும்."),
    R("RV-FLOW-GN", "groundnut", "flowering_pegging", "revival", "info",
      "Rain returning: apply gypsum", "மழை திரும்புகிறது: ஜிப்சம் இடவும்",
      "{district}: rain is likely to return in {window} ({prob} chance) after the dry spell.",
      "{district_ta}: வறட்சிக்குப் பின் {window} காலத்தில் மழை திரும்ப {prob} வாய்ப்பு.",
      "Once the soil is moist, apply gypsum (400 kg/ha) and do earthing up to help pegging.",
      "மண் ஈரமானதும் ஜிப்சம் (எக்டருக்கு 400 கிலோ) இட்டு, விழுது இறங்க மண் அணைக்கவும்."),
    R("RV-CROP", "*", "vegetative", "revival", "info",
      "Rain returning: feed the crop", "மழை திரும்புகிறது: பயிருக்கு உரமிடவும்",
      "{district}: rain is likely to return in {window} ({prob} chance) after the dry spell.",
      "{district_ta}: வறட்சிக்குப் பின் {window} காலத்தில் மழை திரும்ப {prob} வாய்ப்பு.",
      "Apply the pending fertiliser dose after the rain and gap-fill where plants died.",
      "மழைக்குப் பின் நிலுவையிலுள்ள உர அளவை இட்டு, செடிகள் இறந்த இடங்களை நிரப்பவும்."),
    R("RV-EST", "*", "establishment", "revival", "info",
      "Rain returning: gap-fill {crop}", "மழை திரும்புகிறது: {crop_ta} இடைவெளியை நிரப்பவும்",
      "{district}: rain is likely to return in {window} ({prob} chance).",
      "{district_ta}: {window} காலத்தில் மழை திரும்ப {prob} வாய்ப்பு.",
      "Gap-fill or resow patches where seedlings failed, right after the rain.",
      "மழைக்குப் பின் உடனே, நாற்றுகள் முளைக்காத இடங்களில் மீண்டும் விதைக்கவும்."),
]


def _stage_score(rule_stage: str, stage: str, group: str) -> int | None:
    if rule_stage == stage:
        return 6
    if rule_stage == group:
        return 3
    if rule_stage == "*":
        return 0
    return None


def select_rule(crop: str, stage: str, stage_group: str, hazard_type: str,
                subtype: str | None = None, rules: list[AdviceRule] | None = None) -> AdviceRule | None:
    """Most specific rule for crop × stage × hazard (pure; tested)."""
    best: tuple[int, int, AdviceRule] | None = None
    for i, r in enumerate(rules if rules is not None else RULES):
        if r.hazard_type != hazard_type:
            continue
        if r.subtype is not None and r.subtype != subtype:
            continue
        if r.crop not in ("*", crop):
            continue
        s = _stage_score(r.stage, stage, stage_group)
        if s is None:
            continue
        score = s + (2 if r.crop == crop else 0)
        if best is None or score > best[0]:
            best = (score, i, r)
    return best[2] if best else None
