"""Claude integration: understanding the user's message and writing the reply.

Claude does the language work (any Indian language in, same language out).
It never decides eligibility - that is app/rules.py - and it is told to use
only the scheme facts it is handed.
"""
import json
import logging
from functools import lru_cache
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, Field

from .config import get_settings
from .lang import LANGUAGES
from .schemas import UserProfile

log = logging.getLogger(__name__)


class Understanding(BaseModel):
    language: str = Field(description="ISO 639-1 code of the language the user wrote in, e.g. hi, en, bn, ta, te, mr")
    intent: Literal["eligibility", "scheme_question", "reset", "other"]
    profile: UserProfile = Field(description="Only facts stated in this message; leave everything else null")
    search_query: str = Field(description="Short English search query for the scheme or topic asked about; empty if none")


UNDERSTAND_SYSTEM = """You are the intake step of a government-scheme eligibility assistant for India. \
People write or speak in Hindi, English, Hinglish, Bengali, Tamil, Telugu, Marathi and other Indian languages, \
often informally and with speech-to-text mistakes.

Read the user's latest message and return:
- language: the language they wrote in. Romanised Hindi counts as "hi".
- intent:
  - "eligibility" if they describe themselves or their family, answer one of the assistant's questions, or ask what schemes they can get.
  - "scheme_question" if they ask about a specific scheme or topic (documents, how to apply, benefit amount) without giving new facts about themselves.
  - "reset" if they ask to start over or delete their information.
  - "other" for greetings, thanks and anything unrelated.
- profile: facts about the person stated in THIS message. Never guess; leave a field null unless the message supports it.
  - annual_income is the family's yearly income in rupees (multiply a monthly figure by 12; 1 lakh = 100000).
  - land_acres in acres (1 hectare = 2.47 acres; 1 bigha is roughly 0.62 acre).
  - state is the full English name, e.g. "Uttar Pradesh" for UP.
  - children: one entry per child mentioned, with gender, age and the level they study in. If only the class is given, estimate age as class + 5.
  - education and is_student describe the person themself, not their children.
  - Infer gender only from clear evidence (words like widow, husband, or gendered verb forms in Hindi).
- search_query: for "scheme_question", an English query naming the scheme or topic.

The already-known profile is provided so you can interpret short answers such as "45" or "haan" to the assistant's previous question."""

COMPOSE_SYSTEM = """You write the reply for a government-scheme assistant used by ordinary people in India, \
many with little formal education, mostly on WhatsApp.

Rules:
- Write in {language}, in the script and register the user used. Use simple everyday words and short sentences. Keep scheme names recognisable (you may add the local-language name).
- Use ONLY the facts in the JSON you are given. Do not add schemes, amounts, dates or conditions from memory. If something is not in the data, do not state it.
- Eligibility has already been decided by a rules engine. Present "eligible" schemes as ones the person looks eligible for, and "possible" schemes as ones that depend on the missing details. Never promise approval.
- If a scheme is for a family member (beneficiary is daughter/son/child), say so.
- For each scheme give: name, the benefit in one line, why they qualify in a few words, documents to carry, and the link.
- List at most {max_schemes} schemes, most relevant first, and say how many more there are if you leave some out.
- If follow_up_questions is not empty, end by asking those questions in a friendly way.
- Finish with one short line telling them to confirm on the official website before applying.
- Formatting for WhatsApp: *single asterisks* for bold, plain line breaks, no markdown headings, tables or nested bullets. Stay under {max_words} words."""

ANSWER_SYSTEM = """You answer questions about Indian government schemes for ordinary people, mostly on WhatsApp.

Rules:
- Write in {language}, in the script and register the user used. Simple words, short sentences.
- Answer ONLY from the scheme passages provided. If they do not contain the answer, say you do not have that information and point to the scheme's official link if one is given.
- Mention the official link for any scheme you describe.
- Formatting for WhatsApp: *single asterisks* for bold, plain line breaks, no markdown headings or tables. Stay under 180 words."""


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(timeout=get_settings().llm_timeout_seconds, max_retries=2)


def _text(response) -> Optional[str]:
    if response.stop_reason == "refusal":
        log.warning("Claude declined the request: %s", response.stop_details)
        return None
    return "".join(b.text for b in response.content if b.type == "text").strip() or None


def _call(system: str, user: str, max_tokens: int = 4000) -> Optional[str]:
    try:
        response = _client().messages.create(
            model=get_settings().anthropic_model,
            max_tokens=max_tokens,
            output_config={"effort": "low"},  # short, factual rewrites: speed matters on WhatsApp
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return _text(response)
    except anthropic.APIConnectionError as exc:
        log.error("Could not reach the Claude API: %s", exc)
    except anthropic.RateLimitError:
        log.error("Claude API rate limit hit")
    except anthropic.APIStatusError as exc:
        log.error("Claude API error %s: %s", exc.status_code, exc.message)
    except Exception:  # e.g. missing credentials: fall back to templates rather than fail the turn
        log.exception("Claude call failed")
    return None


def understand(message: str, known: UserProfile, last_questions: list[str]) -> Optional[Understanding]:
    """Returns None on any failure so the caller can fall back to the rule-based extractor."""
    context = {"known_profile": known.known_fields(), "assistant_last_asked_about": last_questions}
    try:
        response = _client().messages.parse(
            model=get_settings().anthropic_model,
            max_tokens=4000,
            output_config={"effort": "low"},
            system=UNDERSTAND_SYSTEM,
            messages=[{"role": "user", "content":
                       f"<context>{json.dumps(context, ensure_ascii=False)}</context>\n\n"
                       f"<user_message>{message}</user_message>"}],
            output_format=Understanding,
        )
        if response.stop_reason == "refusal":
            log.warning("Claude declined to parse a message: %s", response.stop_details)
            return None
        return response.parsed_output
    except anthropic.APIConnectionError as exc:
        log.error("Could not reach the Claude API: %s", exc)
    except anthropic.RateLimitError:
        log.error("Claude API rate limit hit")
    except anthropic.APIStatusError as exc:
        log.error("Claude API error %s: %s", exc.status_code, exc.message)
    except Exception:  # schema/validation problems must never take the bot down
        log.exception("Could not parse Claude's structured output")
    return None


def _language_name(code: str) -> str:
    return LANGUAGES.get(code, code)


def compose_matches(language: str, user_message: str, payload: dict, channel: str) -> Optional[str]:
    system = COMPOSE_SYSTEM.format(language=_language_name(language),
                                   max_schemes=5 if channel == "whatsapp" else 8,
                                   max_words=260 if channel == "whatsapp" else 420)
    user = (f"<user_message>{user_message}</user_message>\n\n"
            f"<results>{json.dumps(payload, ensure_ascii=False)}</results>")
    return _call(system, user)


def answer_question(language: str, question: str, passages: list[str]) -> Optional[str]:
    system = ANSWER_SYSTEM.format(language=_language_name(language))
    docs = "\n\n".join(f"<passage>{p}</passage>" for p in passages)
    return _call(system, f"<passages>\n{docs}\n</passages>\n\n<question>{question}</question>", max_tokens=2000)


def small_talk(language: str, message: str, welcome: str) -> Optional[str]:
    system = (f"You are a friendly government-scheme assistant for India. Reply in {_language_name(language)}, "
              "in the user's script, in under 80 words. Respond briefly to the message, then explain what you do "
              "and what the person should tell you, based on this English reference text (translate it, keep the "
              f"*bold* markers and the example):\n\n{welcome}")
    return _call(system, message, max_tokens=1500)
