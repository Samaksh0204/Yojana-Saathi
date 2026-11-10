"""Rule-based profile extraction for English, Hindi and Hinglish.

This is the offline fallback (and the test baseline) used when no LLM is
configured. With Claude enabled, app/llm.py does this job for every language.
"""
import re
from typing import Optional

from .schemas import Child, UserProfile

STATES = {
    "Andhra Pradesh": ["andhra", "आंध्र"], "Arunachal Pradesh": ["arunachal", "अरुणाचल"],
    "Assam": ["assam", "असम"], "Bihar": ["bihar", "बिहार"],
    "Chhattisgarh": ["chhattisgarh", "chattisgarh", "छत्तीसगढ़"], "Goa": ["goa", "गोवा"],
    "Gujarat": ["gujarat", "गुजरात"], "Haryana": ["haryana", "हरियाणा"],
    "Himachal Pradesh": ["himachal", "हिमाचल"], "Jharkhand": ["jharkhand", "झारखंड"],
    "Karnataka": ["karnataka", "कर्नाटक"], "Kerala": ["kerala", "केरल"],
    "Madhya Pradesh": ["madhya pradesh", "मध्य प्रदेश", "एमपी"],
    "Maharashtra": ["maharashtra", "महाराष्ट्र"], "Manipur": ["manipur", "मणिपुर"],
    "Meghalaya": ["meghalaya", "मेघालय"], "Mizoram": ["mizoram", "मिजोरम"],
    "Nagaland": ["nagaland", "नागालैंड"], "Odisha": ["odisha", "orissa", "ओडिशा", "उड़ीसा"],
    "Punjab": ["punjab", "पंजाब"], "Rajasthan": ["rajasthan", "राजस्थान"],
    "Sikkim": ["sikkim", "सिक्किम"], "Tamil Nadu": ["tamil nadu", "tamilnadu", "तमिलनाडु"],
    "Telangana": ["telangana", "तेलंगाना"], "Tripura": ["tripura", "त्रिपुरा"],
    "Uttar Pradesh": ["uttar pradesh", "उत्तर प्रदेश", "यूपी"],
    "Uttarakhand": ["uttarakhand", "उत्तराखंड"],
    "West Bengal": ["west bengal", "bengal", "पश्चिम बंगाल", "बंगाल"],
    "Delhi": ["delhi", "दिल्ली"], "Jammu and Kashmir": ["jammu", "kashmir", "जम्मू", "कश्मीर"],
    "Ladakh": ["ladakh", "लद्दाख"], "Puducherry": ["puducherry", "pondicherry"],
    "Chandigarh": ["chandigarh", "चंडीगढ़"],
}
_STATE_RE = [(name, re.compile(r"(?<![a-z])(?:" + "|".join(map(re.escape, alts)) + r")(?![a-z])"))
             for name, alts in STATES.items()]


# "UP" and "MP" are only trusted in capitals, or right after "in"/"from" ("up to 2 lakh" is not a state).
_ABBREVIATIONS = [("Uttar Pradesh", re.compile(r"\bU\.?P\b|\b(?:in|from)\s+up\b")),
                  ("Madhya Pradesh", re.compile(r"\bM\.?P\b|\b(?:in|from)\s+mp\b"))]


def normalise_state(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    for name, pattern in _ABBREVIATIONS:
        if pattern.search(value):
            return name
    text = value.strip().lower()
    for name, pattern in _STATE_RE:
        if text == name.lower() or pattern.search(text):
            return name
    return None


OCCUPATIONS = [  # first match wins, so specific jobs come before general ones
    ("agri_labourer", r"farm labou?r|agricultural labou?r|khet majdoor|khet mazdoor|खेत मजदूर|खेतिहर"),
    ("farmer", r"farmer|farming|kisan|kisaan|kheti|किसान|खेती|कृषक|cultivat"),
    ("fisher", r"fisher|machhuara|मछुआरा|मछली पालन|fish farm"),
    ("street_vendor", r"street vendor|hawker|thela|rehdi|redi|ठेला|रेहड़ी|फेरी|vendor"),
    ("construction_worker", r"construction|mason|mistri|raj ?mistri|राजमिस्त्री|निर्माण|मिस्त्री"),
    ("artisan", r"carpenter|blacksmith|potter|tailor|cobbler|weaver|barber|goldsmith|artisan|"
                r"badhai|lohar|kumhar|darzi|mochi|बढ़ई|लोहार|कुम्हार|दर्जी|मोची|बुनकर|नाई|कारीगर"),
    ("unorganised_worker", r"labou?rer|daily wage|majdoor|mazdoor|मजदूर|मज़दूर|दिहाड़ी|"
                           r"domestic (help|worker)|maid|driver|rickshaw|रिक्शा|gig worker|delivery"),
    ("self_employed", r"shop ?keeper|own (a )?(shop|business)|small business|dukaan|dukan|दुकान|"
                      r"व्यापार|self[- ]employed|business"),
    ("unemployed", r"unemployed|jobless|no job|berozgar|बेरोजगार|बेरोज़गार"),
    ("homemaker", r"housewife|homemaker|grihini|गृहिणी|गृहणी"),
    ("salaried", r"salaried|private job|office job|government employee|govt employee|sarkari naukri|"
                 r"सरकारी नौकरी|सरकारी कर्मचारी|नौकरी करत"),
    ("student", r"\bstudent|छात्र|विद्यार्थी|i study|i am studying|padhai kar|पढ़ाई कर|पढ़ता हूँ|पढ़ती हूँ"),
]
_CHILD = re.compile(r"daughter|\bsons?\b|child|\bkids?\b|beti|\bbet[ae]\b|bachch|बेटी|बेटियाँ|बेटियां|बेटा|बेटे|बच्च|पुत्र")
# "ladki" / "girl" only means a child when possessed ("meri ladki"); "main ek ladki hoon" is the user.
_POSSESSED_CHILD = re.compile(r"(?:\bmy|\bour|\bmer[ie]|\bhamar[ie]|मेरी|मेरा|मेरे|हमारी|हमारा|हमारे)\s+(?:\S+\s+)?"
                              r"(?:ladk[ia]|लड़की|लड़का|लड़के|girl|boy)")
_GIRL = re.compile(r"daughter|beti|ladki|बेटी|बेटियाँ|बेटियां|लड़की|पुत्री|girl")
_BOY = re.compile(r"\bsons?\b|\bbet[ae]\b|ladka|बेटा|बेटे|लड़का|लड़के|पुत्र(?!ी)|\bboy\b")
_NEG = re.compile(r"\b(no|not|don'?t|do not|without|never|nahi|nahin)\b|नहीं|नही")
_NUM = r"(\d+(?:\.\d+)?)"
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _class_level(n: int) -> Optional[str]:
    if 1 <= n <= 8:
        return "below_class_9"
    if 9 <= n <= 10:
        return "class_9_10"
    if 11 <= n <= 12:
        return "class_11_12"
    return None


def _class_number(text: str) -> Optional[int]:
    m = (re.search(r"(?:class|std|standard|grade|कक्षा|क्लास)\s*[-:]?\s*(\d{1,2})", text)
         or re.search(r"(\d{1,2})\s*(?:st|nd|rd|th|वीं|वी|वें)\s*(?:class|std|standard|grade|कक्षा|क्लास)?", text))
    return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 12 else None


def _education(text: str) -> Optional[str]:
    n = _class_number(text)
    if n:
        return _class_level(n)
    if re.search(r"post ?grad|\bm\.?a\b|\bm\.?sc\b|\bm\.?tech\b|\bmba\b|\bm\.?com\b|स्नातकोत्तर", text):
        return "postgraduate"
    if re.search(r"diploma|polytechnic|\biti\b|डिप्लोमा|आईटीआई", text):
        return "diploma"
    if re.search(r"college|graduat|\bb\.?a\b|\bb\.?sc\b|\bb\.?tech\b|\bb\.?com\b|degree|engineering|"
                 r"कॉलेज|स्नातक|university|विश्वविद्यालय", text):
        return "undergraduate"
    return None


def _age(text: str) -> Optional[int]:
    # "10 साल से खेती" / "for 10 years" is a duration, not an age.
    m = (re.search(r"(?<!for )(?<!last )(?<!since )(\d{1,3})\s*(?:years?|yrs?|साल|वर्ष|saal|sal\b)"
                   r"(?!\s*(?:se\b|से|ago|पहले|of |experience))", text)
         or re.search(r"(?:age|aged|umar|umra|उम्र|आयु)\D{0,12}(\d{1,3})", text)
         or re.search(r"(?:\bi am|\bi'm|\bis)\s+(\d{1,2})\b(?!\s*(?:acre|lakh|th\b|st\b|nd\b|rd\b|k\b|[,.]?\d))", text)
         or re.search(r"(?:^|,)\s*(\d{2})\s*(?=,|$)", text))  # a bare number between commas: "widow, 45, UP"
    if m and 0 < int(m.group(1)) < 120:
        return int(m.group(1))
    return None


def _income(text: str) -> Optional[int]:
    m = re.search(_NUM + r"\s*(lakh|lac|लाख|thousand|hazar|hajar|हजार|हज़ार|k\b)", text)
    if m:
        amount = float(m.group(1)) * (100_000 if m.group(2) in ("lakh", "lac", "लाख") else 1_000)
    else:
        m = (re.search(r"(?:₹|rs\.?|inr|रु\.?|रुपये|रुपए)\s*([\d,]+)", text)
             or re.search(r"([\d,]{4,})\s*(?:₹|rs\.?|rupees|रुपये|रुपए|rupaye)", text)
             or re.search(r"(?:income|earn|kamai|kamata|kamati|आय|आमदनी|कमाई|कमात)\D{0,25}([\d,]{4,})", text))
        if not m:
            return None
        amount = float(m.group(1).replace(",", "") or 0)
    tail = text[m.end(): m.end() + 30] + text[max(0, m.start() - 15): m.start()]
    if re.search(r"month|mahin|maheen|महीन|माह|मासिक", tail):
        amount *= 12
    return int(amount) if amount > 0 else None


def _land(text: str) -> Optional[float]:
    m = re.search(_NUM + r"\s*(acres?|एकड़|ekad|ekar|hectares?|हेक्टेयर|bigha|बीघा)", text)
    if not m:
        return None
    unit = m.group(2)
    # 1 hectare = 2.47 acres. Bigha varies by region; 0.62 acre is the common UP/Bihar value.
    factor = 2.47 if unit.startswith(("hect", "हेक्ट")) else 0.62 if unit in ("bigha", "बीघा") else 1.0
    return round(float(m.group(1)) * factor, 2)


def _flag(text: str, pattern: str) -> Optional[bool]:
    m = re.search(pattern, text)
    if not m:
        return None
    # English negates before ("no ration card"), Hindi after ("राशन कार्ड नहीं है") - but only
    # within the same clause, so "a BPL card and no house" stays positive.
    before = re.split(r",|\band\b|\baur\b|और", text[max(0, m.start() - 20): m.start()])[-1]
    after = re.split(r",|\band\b|\baur\b|और", text[m.end(): m.end() + 14])[0]
    return not (_NEG.search(before) or _NEG.search(after))


def extract_profile(message: str) -> UserProfile:
    text = message.lower().translate(_DEVANAGARI_DIGITS)
    # Split into clauses, but not inside "1.5 lakh", "80,000" or "B.Sc".
    clauses = [c.strip() for c in re.split(r",(?!\d)|\.(?=\s|$)|[;।\n]|\band\b|\baur\b|और|\bbut\b|लेकिन", text)
               if c.strip()]
    p = UserProfile()
    own_clauses: list[str] = []
    last_gender, in_class_list = None, False  # for "daughters in class 9 and 11"

    for clause in clauses:
        if _CHILD.search(clause) or _POSSESSED_CHILD.search(clause):
            in_class_list = False
            if _NEG.search(clause) and not re.search(r"\d", clause):
                continue  # "I have no children"
            grade = _class_number(clause)
            age, edu = _age(clause), _education(clause)
            if age is None and grade:
                age = grade + 5
            last_gender = "female" if _GIRL.search(clause) else "male" if _BOY.search(clause) else None
            p.children.append(Child(gender=last_gender, age=age, education=edu))
            in_class_list = grade is not None
        elif in_class_list and re.fullmatch(r"\d{1,2}", clause) and _class_level(int(clause)):
            p.children.append(Child(gender=last_gender, age=int(clause) + 5, education=_class_level(int(clause))))
        else:
            in_class_list = False
            own_clauses.append(clause)
    own = " , ".join(own_clauses)

    p.state = normalise_state(message)
    p.age = _age(own)
    p.annual_income = _income(own)
    p.land_acres = _land(text)
    for name, pattern in OCCUPATIONS:
        if re.search(pattern, own):
            p.occupation = name
            break
    finished = re.search(r"\bpass(ed)?\b|studied (till|up ?to)|पास|तक पढ़", own)  # "10th pass" is not a student
    p.education = _education(own) if p.occupation in (None, "student") and not finished else None
    if p.education:
        p.occupation, p.is_student = "student", True
    if p.land_acres:
        p.owns_land = True
    elif re.search(r"landless|no land|bhoomiheen|भूमिहीन", own):
        p.owns_land = False

    # (?<![.\w]) keeps "B.Sc" and "M.Sc" from being read as the SC category.
    for caste, pattern in [("sc", r"(?<![.\w])sc\b|scheduled caste|अनुसूचित जाति|dalit|दलित|एससी"),
                           ("st", r"(?<![.\w])st\b(?!\.)|scheduled tribe|अनुसूचित जनजाति|adivasi|आदिवासी|tribal|एसटी"),
                           ("obc", r"\bobc\b|backward class|पिछड़ा|ओबीसी"),
                           ("ews", r"\bews\b|ईडब्ल्यूएस"),
                           ("general", r"general category|general caste|सामान्य वर्ग")]:
        if re.search(pattern, text):
            p.caste = caste
            break
    if re.search(r"village|gaon|gaanv|गाँव|गांव|rural|ग्रामीण", text):
        p.residence = "rural"
    elif re.search(r"\bcity\b|shahar|sheher|शहर|urban|\btown\b|नगर", text):
        p.residence = "urban"

    if re.search(r"widow|विधवा|vidhwa|husband (has )?(died|passed|expired)|पति की मृत्यु|पति नहीं रहे", own):
        p.marital_status, p.gender = "widowed", "female"
    elif re.search(r"divorc|तलाक", own):
        p.marital_status = "divorced"
    elif re.search(r"unmarried|\bsingle\b|अविवाहित|कुंवार", own):
        p.marital_status = "single"
    elif re.search(r"married|shaadi ?shuda|विवाहित|शादीशुदा|my husband|my wife|मेरे पति|मेरी पत्नी", text):
        p.marital_status = "married"
    if re.search(r"pregnan|गर्भवती|garbhvati|expecting a (baby|child)", own):
        p.pregnant, p.gender = True, "female"
    if p.gender is None:
        if re.search(r"woman|female|mahila|महिला|aurat|औरत|housewife|गृहिणी|my husband|मेरे पति|"
                     r"ती हूँ|ती हूं|रही हूँ|रही हूं|ti hoon|ti hun|ti hu\b|rahi (hoon|hun|hu)\b|"
                     r"i am a mother|i'm a mother|ladki|लड़की|\bgirl\b", own):
            p.gender = "female"
        elif re.search(r"\bman\b|\bmale\b|पुरुष|aadmi|आदमी|my wife|मेरी पत्नी|"
                       r"ता हूँ|ता हूं|रहा हूँ|रहा हूं|ta hoon|ta hun|ta hu\b|raha (hoon|hun|hu)\b|"
                       r"i am a father|i'm a father|ladka|लड़का|\bboy\b", own):
            p.gender = "male"

    p.bpl = _flag(text, r"\bbpl\b|ration card|राशन कार्ड|गरीबी रेखा|antyodaya|अंत्योदय|below poverty|बीपीएल")
    p.disability = _flag(own, r"disab|divyang|दिव्यांग|विकलांग|handicap|\bblind\b|\bdeaf\b") or None
    p.minority = _flag(text, r"muslim|christian|\bsikh\b|buddhist|\bjain\b|parsi|minority|"
                             r"मुस्लिम|मुसलमान|ईसाई|सिख|बौद्ध|जैन|अल्पसंख्यक") or None
    p.pays_income_tax = _flag(own, r"income tax|tax ?payer|आयकर|इनकम टैक्स")
    if re.search(r"government employee|govt\.? (employee|job)|sarkari naukri|सरकारी नौकरी|सरकारी कर्मचारी", own):
        p.is_govt_employee = True
    if re.search(r"kutcha|kachcha|kaccha|कच्चा (मकान|घर)|homeless|बेघर|no (pucca |pakka )?house|"
                 r"(घर|मकान) नहीं", text):
        p.has_pucca_house = False
    elif re.search(r"pucca house|pakka (ghar|makan)|पक्का (मकान|घर)", text):
        p.has_pucca_house = _flag(text, r"pucca house|pakka (ghar|makan)|पक्का (मकान|घर)")
    return p
