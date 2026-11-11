"""The Claude layer, exercised with a fake client: no network, no API key."""
import json
from types import SimpleNamespace

import pytest

from app import llm
from app.config import get_settings
from app.graph import run_agent
from app.schemas import UserProfile


class FakeClaude:
    """Returns the queued replies in order and records every request."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **request):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(stop_reason="end_turn", stop_details=None,
                               content=[SimpleNamespace(type="text", text=reply)])


@pytest.fixture
def claude(monkeypatch: pytest.MonkeyPatch):
    def install(*replies):
        fake = FakeClaude(*replies)
        monkeypatch.setattr(llm, "_client", lambda: fake)
        monkeypatch.setattr(get_settings(), "llm_mode", "on")
        return fake
    return install


GOOD = json.dumps({"language": "hi", "intent": "eligibility", "search_query": "",
                   "profile": {"occupation": "farmer", "state": "Bihar", "land_acres": 3}})


def test_valid_json_becomes_a_typed_understanding(claude):
    claude(f"```json\n{GOOD}\n```")  # a code fence around the JSON is tolerated
    result = llm.understand("मैं बिहार का किसान हूँ", UserProfile(), [])
    assert result.language == "hi" and result.profile.occupation == "farmer" and result.profile.land_acres == 3


def test_invalid_json_gets_one_corrective_retry(claude):
    bad = json.dumps({"language": "hi", "intent": "eligibility", "search_query": "",
                      "profile": {"occupation": "astronaut", "age": "forty"}})
    fake = claude(bad, GOOD)
    result = llm.understand("...", UserProfile(), [])
    assert result.profile.occupation == "farmer"
    assert len(fake.requests) == 2
    correction = fake.requests[1]["messages"][-1]["content"]
    assert "profile.occupation" in correction and "profile.age" in correction
    assert "astronaut" not in correction and "forty" not in correction  # rejected values are not echoed


def test_two_bad_replies_give_up(claude):
    fake = claude("I cannot help with that.", '{"language": "hi"}')
    assert llm.understand("...", UserProfile(), []) is None
    assert len(fake.requests) == 2


def test_api_failure_returns_none(claude):
    claude(RuntimeError("network down"))
    assert llm.understand("...", UserProfile(), []) is None
    assert llm.compose_matches("en", "hello", {"schemes": []}, "web") is None


def test_agent_falls_back_to_offline_mode_when_claude_fails(claude):
    claude(RuntimeError("down"), RuntimeError("down"))
    result = run_agent("I am a farmer in Bihar with 3 acres", "web:llm-fallback-test", "web")
    assert result["engine"] == "rules" and result["profile"]["occupation"] == "farmer"
    assert "PM-KISAN" in result["reply"]


def test_claude_writes_the_reply_but_the_rules_engine_picks_the_schemes(claude):
    fake = claude(GOOD, "आप पीएम-किसान के लिए पात्र लगते हैं।")
    result = run_agent("मैं बिहार का किसान हूँ, 3 एकड़ ज़मीन", "web:llm-compose-test", "web")
    assert result["engine"] == "claude" and result["reply"].startswith("आप")
    assert any(m["scheme_id"] == "pm-kisan" for m in result["matches"])
    payload = fake.requests[1]["messages"][0]["content"]  # what Claude was given to rewrite
    assert "PM-KISAN" in payload and "pmkisan.gov.in" in payload


def test_model_output_cannot_add_an_eligibility_decision(claude):
    # Extra keys such as a made-up "eligible_schemes" list are simply not part of the schema.
    sneaky = json.dumps({"language": "en", "intent": "eligibility", "search_query": "",
                         "profile": {"age": 30}, "eligible_schemes": ["pm-kisan"]})
    claude(sneaky, "ok")
    result = run_agent("I am 30", "web:llm-sneaky-test", "web")
    assert all(m["scheme_id"] != "pm-kisan" for m in result["matches"])


def test_harmless_gaps_in_model_output_do_not_cost_a_retry(claude):
    fake = claude(json.dumps({"language": "en", "intent": "other", "search_query": None,
                              "profile": {"children": None, "age": "45"}}))
    result = llm.understand("hello", UserProfile(), [])
    assert result.search_query == "" and result.profile.children == [] and result.profile.age == 45
    assert len(fake.requests) == 1
