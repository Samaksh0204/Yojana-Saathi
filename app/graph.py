"""The agent, as a LangGraph state machine.

    understand ──► match ──► compose              (user described themself)
        │
        ├────────► retrieve ──► answer            (question about a scheme: RAG)
        ├────────► smalltalk                      (greeting / unrelated)
        └────────► reset                          (forget me)

`understand` uses Claude when configured and a rule-based extractor otherwise,
so the whole pipeline also runs offline (English/Hindi) for tests and demos.
"""
import logging
import re
from functools import lru_cache
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from . import llm
from .catalog import load_schemes
from .config import get_settings
from .extract import extract_profile, normalise_state
from .lang import LANGUAGES, detect_language, strings
from .respond import llm_payload, scheme_card, template_matches
from .retriever import Doc, get_retriever
from .rules import follow_up_fields, match_schemes, shown
from .schemas import Match, UserProfile
from .sessions import get_store

log = logging.getLogger(__name__)

RESET_WORDS = {"reset", "restart", "start over", "delete my data", "रीसेट", "नया", "फिर से शुरू"}
GREETINGS = re.compile(r"^\W*(hi+|hello|hey|namaste|namaskar|start|help|menu|thanks|thank you|"
                       r"नमस्ते|नमस्कार|धन्यवाद|हेलो|हाय)\W*$", re.I)
YES = re.compile(r"^\W*(yes|ha+n?|haa?n ji|ji|y|हाँ|हां|जी|है)\W*$", re.I)
NO = re.compile(r"^\W*(no|nahi+n?|nope|n|नहीं|नही|ना)\W*$", re.I)
QUESTION = re.compile(r"\?|\b(what|how|which|when|where|documents?|apply|kya|kaise|kaun|kab|kitna|kitni)\b|"
                      r"क्या|कैसे|कौन|कब|कितन|दस्तावेज़|दस्तावेज|आवेदन", re.I)
ABOUT_ME = re.compile(r"\b(i am|i'm|i have|my|we|main|mai|mein|mera|meri|mere|mujhe|hum)\b|"
                      r"मैं|मेरा|मेरी|मेरे|मुझे|हम", re.I)
BOOLEAN_FIELDS = {"bpl", "owns_land", "is_student", "has_pucca_house"}


class AgentState(TypedDict, total=False):
    session_id: str
    text: str
    channel: str
    lang_hint: Optional[str]
    language: str
    intent: str
    profile: UserProfile
    asked: list[str]  # fields the assistant asked about in its previous reply
    search_query: str
    matches: list[Match]
    followups: list[str]
    hits: list[tuple[Doc, float]]
    reply: str
    engine: str  # "claude" or "rules" - which path wrote the reply


def _short_answer(text: str, asked: list[str]) -> UserProfile:
    """Offline handling of terse replies ("45", "haan") to the question we just asked."""
    update = UserProfile()
    if not asked:
        return update
    field = asked[0]
    number = re.fullmatch(r"\W*(\d+(?:\.\d+)?)\W*", text)
    if number and field == "age":
        update.age = int(float(number.group(1)))
    elif number and field == "annual_income":
        update.annual_income = int(float(number.group(1)))
    elif number and field == "land_acres":
        update.land_acres = float(number.group(1))
    elif field in BOOLEAN_FIELDS and (YES.match(text) or NO.match(text)):
        setattr(update, field, bool(YES.match(text)))
    return update


def understand(state: AgentState) -> AgentState:
    settings = get_settings()
    text = state["text"].strip()
    profile, asked, saved_language = get_store().load(state["session_id"])
    hint = state.get("lang_hint") if state.get("lang_hint") in LANGUAGES else None

    if text.lower() in RESET_WORDS:
        return {"intent": "reset", "language": hint or saved_language or detect_language(text),
                "profile": profile, "asked": asked}

    parsed = llm.understand(text, profile, asked) if settings.llm_enabled else None
    if parsed:
        update = parsed.profile
        update.state = normalise_state(update.state) or update.state
        language, intent, query = parsed.language, parsed.intent, parsed.search_query or text
    else:
        update = extract_profile(text).merged_with(_short_answer(text, asked))
        has_letters = any(ch.isalpha() for ch in text)
        language = detect_language(text) if has_letters else (saved_language or "en")
        if QUESTION.search(text) and not ABOUT_ME.search(text):
            intent, update = "scheme_question", UserProfile()  # "PM Kisan ke liye kya chahiye?"
        elif update.known_fields():
            intent = "eligibility"
        elif GREETINGS.match(text):
            intent = "other"
        else:
            intent = "scheme_question"
        query = text

    return {"language": hint or language, "intent": intent, "search_query": query,
            "profile": profile.merged_with(update), "asked": asked}


def route(state: AgentState) -> str:
    return state["intent"]


def match(state: AgentState) -> AgentState:
    profile = state["profile"]
    matches = match_schemes(profile, load_schemes())
    followups = follow_up_fields(matches)
    # State and age unlock the most schemes, so always ask for them first if missing.
    basics = [f for f in ("state", "age") if getattr(profile, f) is None]
    followups = list(dict.fromkeys(basics + followups))[:3]
    return {"matches": shown(matches), "followups": followups}


def compose(state: AgentState) -> AgentState:
    profile, matches, followups = state["profile"], state["matches"], state["followups"]
    reply = None
    if get_settings().llm_enabled:
        reply = llm.compose_matches(state["language"], state["text"],
                                    llm_payload(matches, followups, profile), state["channel"])
    if reply:
        return {"reply": reply, "engine": "claude"}
    return {"reply": template_matches(matches, followups, profile, state["language"], state["channel"]),
            "engine": "rules"}


def retrieve(state: AgentState) -> AgentState:
    return {"hits": get_retriever().search(state["search_query"], k=4)}


def answer(state: AgentState) -> AgentState:
    hits, language = state["hits"], state["language"]
    t = strings(language)
    if hits and get_settings().llm_enabled:
        reply = llm.answer_question(language, state["text"], [doc.text for doc, _ in hits])
        if reply:
            return {"reply": reply, "engine": "claude", "followups": []}
    # Offline: show the best-matching scheme card if the keyword match is convincing.
    best = next(((doc, score) for doc, score in hits if doc.scheme_id), None)
    if best and best[1] >= 0.5:
        from .catalog import schemes_by_id
        return {"reply": scheme_card(schemes_by_id()[best[0].scheme_id], language) + "\n\n" + t["disclaimer"],
                "engine": "rules", "followups": []}
    known = state["profile"].known_fields()
    return {"reply": t["no_answer"] if known else t["welcome"], "engine": "rules", "followups": []}


def smalltalk(state: AgentState) -> AgentState:
    language = state["language"]
    reply = None
    if get_settings().llm_enabled:
        reply = llm.small_talk(language, state["text"], strings("en")["welcome"])
    return {"reply": reply or strings(language)["welcome"], "engine": "claude" if reply else "rules",
            "followups": []}


def reset(state: AgentState) -> AgentState:
    get_store().delete(state["session_id"])
    return {"reply": strings(state["language"])["reset"], "engine": "rules",
            "profile": UserProfile(), "followups": []}


@lru_cache
def build_graph():
    graph = StateGraph(AgentState)
    for name, node in [("understand", understand), ("match", match), ("compose", compose),
                       ("retrieve", retrieve), ("answer", answer), ("smalltalk", smalltalk),
                       ("reset", reset)]:
        graph.add_node(name, node)
    graph.add_edge(START, "understand")
    graph.add_conditional_edges("understand", route, {
        "eligibility": "match", "scheme_question": "retrieve", "other": "smalltalk", "reset": "reset"})
    graph.add_edge("match", "compose")
    graph.add_edge("retrieve", "answer")
    for last in ("compose", "answer", "smalltalk", "reset"):
        graph.add_edge(last, END)
    return graph.compile()


def run_agent(text: str, session_id: str, channel: str = "web", lang_hint: Optional[str] = None) -> dict:
    state = build_graph().invoke({"text": text, "session_id": session_id, "channel": channel,
                                  "lang_hint": lang_hint})
    profile: UserProfile = state["profile"]
    if state["intent"] != "reset":
        # Keep the previous question open if this turn did not ask a new one.
        asked = state.get("followups") or state.get("asked", [])
        get_store().save(session_id, profile, asked, state["language"])
    log.info("turn channel=%s intent=%s engine=%s matches=%d", channel, state["intent"],
             state.get("engine"), len(state.get("matches", [])))
    return {
        "reply": state["reply"], "language": state["language"], "intent": state["intent"],
        "engine": state.get("engine", "rules"), "profile": profile.known_fields(),
        "matches": [m.model_dump() for m in state.get("matches", [])],
    }
