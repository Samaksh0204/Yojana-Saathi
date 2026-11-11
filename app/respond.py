"""Builds replies: the structured payload for Claude, and template text when there is no LLM."""
from .catalog import schemes_by_id
from .lang import strings
from .schemas import Match, Scheme, UserProfile


def _reasons(match: Match, profile: UserProfile, lang: str) -> list[str]:
    phrases = strings(lang)["r"]
    values = {"state": profile.state, "caste": (profile.caste or "").upper(), "residence": profile.residence}
    return [phrases[key].format(**values) for key in dict.fromkeys(match.passed)
            if key in phrases and key != "gender"]


def _name(scheme: Scheme, lang: str) -> str:
    return scheme.name_hi if lang == "hi" and scheme.name_hi else scheme.name


def llm_payload(matches: list[Match], followups: list[str], profile: UserProfile) -> dict:
    """English facts for Claude to rewrite in the user's language."""
    en = strings("en")
    items = []
    for m in matches[:12]:
        s = schemes_by_id()[m.scheme_id]
        items.append({
            "name": s.name, "local_name": s.name_hi, "status": m.status, "beneficiary": m.beneficiary,
            "benefit": s.benefit, "who_it_is_for": s.summary, "important_note": s.note,
            "why_they_qualify": _reasons(m, profile, "en"),
            "depends_on": [en["q"][f] for f in m.missing],
            "documents": s.documents, "official_link": s.url,
        })
    return {"schemes": items, "total_matches": len(matches),
            "follow_up_questions": [en["q"][f] for f in followups]}


def scheme_card(scheme: Scheme, lang: str) -> str:
    t = strings(lang)
    lines = [f"*{_name(scheme, lang)}*", scheme.summary, f"💰 {scheme.benefit}"]
    if scheme.note:
        lines.append(f"ℹ️ {scheme.note}")
    lines += [f"📄 {t['docs']}: {', '.join(scheme.documents)}", f"🔗 {t['apply']}: {scheme.url}"]
    return "\n".join(lines)


def template_matches(matches: list[Match], followups: list[str], profile: UserProfile,
                     lang: str, channel: str) -> str:
    t = strings(lang)
    limit_sure, limit_maybe = (5, 3) if channel == "whatsapp" else (8, 5)
    sure = [m for m in matches if m.status == "eligible"]
    maybe = [m for m in matches if m.status == "possible"]
    out: list[str] = []

    if sure:
        out.append(t["eligible"].format(n=len(sure)))
        for n, m in enumerate(sure[:limit_sure], 1):
            s = schemes_by_id()[m.scheme_id]
            who = f" ({t['for'].format(who=t['who'][m.beneficiary])})" if m.beneficiary != "self" else ""
            block = [f"{n}. *{_name(s, lang)}*{who}", f"💰 {s.benefit}"]
            reasons = _reasons(m, profile, lang)
            if reasons:
                block.append(f"✔️ {t['why']}: {'; '.join(reasons)}")
            block += [f"📄 {t['docs']}: {', '.join(s.documents)}", f"🔗 {t['apply']}: {s.url}"]
            out.append("\n".join(block))
        if len(sure) > limit_sure:
            out.append(t["more"].format(n=len(sure) - limit_sure))
    if maybe:
        out.append(t["possible"])
        lines = []
        for m in maybe[:limit_maybe]:
            s = schemes_by_id()[m.scheme_id]
            who = f" ({t['for'].format(who=t['who'][m.beneficiary])})" if m.beneficiary != "self" else ""
            lines.append(f"• *{_name(s, lang)}*{who} - {s.benefit}")
        out.append("\n".join(lines))
    if not matches:
        out.append(t["none"])
    if followups:
        out.append(t["ask"].format(q="; ".join(t["q"][f] for f in followups) + "?"))
    if matches:
        out.append(t["disclaimer"])
    return "\n\n".join(out)


# ---- Structured output for the web page (cards and one-tap answers) ----

# field -> [(value, English label, Hindi label)]. Only facts with a small fixed set of answers.
QUICK_ANSWERS: dict[str, list[tuple[object, str, str]]] = {
    "gender": [("female", "Woman", "महिला"), ("male", "Man", "पुरुष")],
    "residence": [("rural", "Village", "गाँव"), ("urban", "City / town", "शहर")],
    "bpl": [(True, "Yes", "हाँ"), (False, "No", "नहीं")],
    "owns_land": [(True, "Yes", "हाँ"), (False, "No", "नहीं")],
    "is_student": [(True, "Yes", "हाँ"), (False, "No", "नहीं")],
    "has_pucca_house": [(True, "Yes", "हाँ"), (False, "No", "नहीं")],
    "caste": [("general", "General", "सामान्य"), ("obc", "OBC", "ओबीसी"), ("sc", "SC", "एससी"),
              ("st", "ST", "एसटी"), ("ews", "EWS", "ईडब्ल्यूएस")],
    "marital_status": [("single", "Single", "अविवाहित"), ("married", "Married", "विवाहित"),
                       ("widowed", "Widowed", "विधवा / विधुर"), ("divorced", "Divorced", "तलाकशुदा")],
    "occupation": [("farmer", "Farmer", "किसान"), ("unorganised_worker", "Labourer", "मज़दूर"),
                   ("street_vendor", "Street vendor", "रेहड़ी-पटरी"), ("artisan", "Artisan", "कारीगर"),
                   ("self_employed", "Own business", "अपना काम"), ("salaried", "Salaried job", "नौकरी"),
                   ("student", "Student", "विद्यार्थी"), ("homemaker", "Homemaker", "गृहिणी"),
                   ("unemployed", "Unemployed", "बेरोज़गार")],
}


def cards(matches: list[Match], profile: UserProfile, lang: str) -> list[dict]:
    t = strings(lang)
    out = []
    for m in matches:
        s = schemes_by_id()[m.scheme_id]
        out.append({
            "id": s.id, "name": _name(s, lang), "status": m.status, "category": s.category,
            "for": t["for"].format(who=t["who"][m.beneficiary]) if m.beneficiary != "self" else None,
            "benefit": s.benefit, "summary": s.summary, "note": s.note,
            "reasons": _reasons(m, profile, lang), "needs": [t["q"][f] for f in m.missing],
            "documents": s.documents, "url": s.url,
        })
    return out


def info_card(scheme: Scheme, lang: str) -> dict:
    return {"id": scheme.id, "name": _name(scheme, lang), "status": "info", "category": scheme.category,
            "for": None, "benefit": scheme.benefit, "summary": scheme.summary, "note": scheme.note,
            "reasons": [], "needs": [], "documents": scheme.documents, "url": scheme.url}


def follow_up_prompts(fields: list[str], lang: str) -> list[dict]:
    t, hindi = strings(lang), lang == "hi"
    return [{"field": f, "question": t["q"][f],
             "options": [{"value": value, "label": hi if hindi else en}
                         for value, en, hi in QUICK_ANSWERS.get(f, [])]} for f in fields]


def headline(matches: list[Match], lang: str) -> str:
    t = strings(lang)
    sure = sum(m.status == "eligible" for m in matches)
    maybe = len(matches) - sure
    parts = []
    if sure:
        parts.append(t["head_eligible"].format(n=sure))
    if maybe:
        parts.append(t["head_possible"].format(n=maybe))
    return " ".join(parts) or t["none"]
