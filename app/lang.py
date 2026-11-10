"""Language detection and the fixed strings used when no LLM is available."""
import re

LANGUAGES = {
    "en": "English", "hi": "Hindi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu",
    "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam",
    "pa": "Punjabi", "or": "Odia", "ur": "Urdu",
}
_SCRIPTS = [  # (first code point, last code point, language)
    (0x0900, 0x097F, "hi"), (0x0980, 0x09FF, "bn"), (0x0A00, 0x0A7F, "pa"),
    (0x0A80, 0x0AFF, "gu"), (0x0B00, 0x0B7F, "or"), (0x0B80, 0x0BFF, "ta"),
    (0x0C00, 0x0C7F, "te"), (0x0C80, 0x0CFF, "kn"), (0x0D00, 0x0D7F, "ml"),
    (0x0600, 0x06FF, "ur"),
]
_MARATHI = re.compile(r"आहे|आहेत|माझ|मला|आणि|शेतकरी|मुलगी|मुलगा")
_HINGLISH = re.compile(
    r"\b(hai|hain|hoon|hun|hu|mera|meri|mere|mujhe|kisan|chahiye|kya|aur|mein|main|"
    r"beti|beta|saal|gaon|yojana|ke liye|karta|karti|rehta|rehti)\b", re.I)


def detect_language(text: str) -> str:
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for lo, hi, lang in _SCRIPTS:
            if lo <= cp <= hi:
                counts[lang] = counts.get(lang, 0) + 1
                break
    if counts:
        lang = max(counts, key=counts.get)
        return "mr" if lang == "hi" and _MARATHI.search(text) else lang
    return "hi" if len(_HINGLISH.findall(text)) >= 2 else "en"


# ---- Template strings (English and Hindi). Other languages need the LLM. ----
T = {
    "en": {
        "welcome": ("Namaste! I help you find government schemes you can claim.\n\n"
                    "Tell me about yourself in one message - your *state*, *age*, *work*, "
                    "*family income*, land, and your children's age or class.\n\n"
                    "Example: _I am a farmer in UP with 2 acres and a daughter in Class 10._\n\n"
                    "Send *reset* to start again."),
        "reset": "Done - I have deleted what you told me. Tell me about yourself to start again.",
        "eligible": "✅ *You look eligible for {n} scheme(s):*",
        "possible": "🟡 *You may also qualify for these (I need a little more information):*",
        "none": "I could not match any scheme yet. Please tell me more about yourself.",
        "why": "Why", "docs": "Documents", "apply": "Apply", "for": "For your {who}",
        "more": "… and {n} more. Ask me about any scheme by name.",
        "ask": "To check more schemes, please tell me: {q}",
        "disclaimer": "ℹ️ This is guidance, not a final decision. Rules change - please confirm on the official website before applying.",
        "no_answer": "I could not find a scheme matching that. Try the scheme's name, or tell me about yourself and I will find schemes for you.",
        "voice_off": "Sorry, voice messages are not switched on here yet. Please type your message.",
        "error": "Sorry, something went wrong on my side. Please try again in a minute.",
        "who": {"daughter": "daughter", "son": "son", "child": "child"},
        "q": {
            "age": "your age", "gender": "whether you are a man or a woman", "state": "your state",
            "occupation": "what work you do", "annual_income": "your family's yearly income",
            "caste": "your category (General / OBC / SC / ST)",
            "residence": "whether you live in a village or a city",
            "bpl": "whether you have a BPL or ration card", "owns_land": "whether you own farmland",
            "land_acres": "how much land you have", "is_student": "whether you are a student",
            "education": "which class or course is being studied",
            "marital_status": "whether you are married, single or widowed",
            "has_pucca_house": "whether you have a pucca house",
        },
        "r": {
            "state": "you live in {state}", "occupation": "your occupation qualifies",
            "gender": "it is open to {gender} applicants", "min_age": "age is above the minimum",
            "max_age": "age is within the limit", "max_income": "family income is within the limit",
            "caste": "category ({caste}) qualifies", "residence": "you live in a {residence} area",
            "bpl": "you have a BPL / ration card", "owns_land": "you own farmland",
            "max_land_acres": "landholding is within the limit", "is_student": "currently studying",
            "education": "the class / course level qualifies", "marital": "marital status qualifies",
            "no_pucca_house": "no pucca house", "disability": "person with disability",
            "widow": "you are a widow", "pregnant": "pregnant or new mother",
            "minority": "minority community",
        },
    },
    "hi": {
        "welcome": ("नमस्ते! मैं आपको वे सरकारी योजनाएँ खोजने में मदद करता हूँ जिनका लाभ आप ले सकते हैं।\n\n"
                    "एक संदेश में अपने बारे में बताइए - आपका *राज्य*, *उम्र*, *काम*, "
                    "*परिवार की आय*, ज़मीन, और बच्चों की उम्र या कक्षा।\n\n"
                    "उदाहरण: _मैं यूपी का किसान हूँ, मेरे पास 2 एकड़ ज़मीन है और मेरी बेटी कक्षा 10 में पढ़ती है।_\n\n"
                    "दोबारा शुरू करने के लिए *reset* भेजें।"),
        "reset": "ठीक है - आपकी दी हुई जानकारी हटा दी गई है। फिर से शुरू करने के लिए अपने बारे में बताइए।",
        "eligible": "✅ *आप इन {n} योजनाओं के लिए पात्र लगते हैं:*",
        "possible": "🟡 *इन योजनाओं का लाभ भी मिल सकता है (थोड़ी और जानकारी चाहिए):*",
        "none": "अभी कोई योजना नहीं मिली। कृपया अपने बारे में थोड़ा और बताइए।",
        "why": "क्यों", "docs": "ज़रूरी दस्तावेज़", "apply": "आवेदन", "for": "आपके {who} के लिए",
        "more": "… और {n} योजनाएँ। किसी भी योजना का नाम लिखकर पूछिए।",
        "ask": "और योजनाएँ जाँचने के लिए कृपया बताइए: {q}",
        "disclaimer": "ℹ️ यह केवल मार्गदर्शन है, अंतिम निर्णय नहीं। नियम बदलते रहते हैं - आवेदन से पहले आधिकारिक वेबसाइट पर ज़रूर जाँच लें।",
        "no_answer": "इससे मिलती कोई योजना नहीं मिली। योजना का नाम लिखिए, या अपने बारे में बताइए और मैं आपके लिए योजनाएँ खोजूँगा।",
        "voice_off": "माफ़ कीजिए, यहाँ अभी वॉइस मैसेज चालू नहीं है। कृपया लिखकर भेजिए।",
        "error": "माफ़ कीजिए, कुछ गड़बड़ हो गई। कृपया थोड़ी देर बाद फिर कोशिश करें।",
        "who": {"daughter": "बेटी", "son": "बेटे", "child": "बच्चे"},
        "q": {
            "age": "आपकी उम्र", "gender": "आप पुरुष हैं या महिला", "state": "आपका राज्य",
            "occupation": "आप क्या काम करते हैं", "annual_income": "परिवार की सालाना आय",
            "caste": "आपका वर्ग (सामान्य / ओबीसी / एससी / एसटी)",
            "residence": "आप गाँव में रहते हैं या शहर में",
            "bpl": "क्या आपके पास बीपीएल या राशन कार्ड है", "owns_land": "क्या आपके पास खेती की ज़मीन है",
            "land_acres": "आपके पास कितनी ज़मीन है", "is_student": "क्या आप पढ़ाई कर रहे हैं",
            "education": "कौन सी कक्षा या कोर्स की पढ़ाई चल रही है",
            "marital_status": "आप विवाहित हैं, अविवाहित हैं या विधवा",
            "has_pucca_house": "क्या आपके पास पक्का मकान है",
        },
        "r": {
            "state": "आप {state} में रहते हैं", "occupation": "आपका काम पात्रता में आता है",
            "gender": "यह योजना आपके लिए खुली है", "min_age": "उम्र न्यूनतम सीमा से ऊपर है",
            "max_age": "उम्र सीमा के भीतर है", "max_income": "परिवार की आय सीमा के भीतर है",
            "caste": "आपका वर्ग पात्र है", "residence": "आपका निवास क्षेत्र पात्र है",
            "bpl": "आपके पास बीपीएल / राशन कार्ड है", "owns_land": "आपके पास खेती की ज़मीन है",
            "max_land_acres": "ज़मीन सीमा के भीतर है", "is_student": "पढ़ाई जारी है",
            "education": "कक्षा / कोर्स पात्र है", "marital": "वैवाहिक स्थिति पात्र है",
            "no_pucca_house": "पक्का मकान नहीं है", "disability": "दिव्यांग व्यक्ति",
            "widow": "आप विधवा हैं", "pregnant": "गर्भवती या नई माँ",
            "minority": "अल्पसंख्यक समुदाय",
        },
    },
}


def strings(lang: str) -> dict:
    return T["hi" if lang == "hi" else "en"]
