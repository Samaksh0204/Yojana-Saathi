import base64
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from app import whatsapp
from app.main import app

client = TestClient(app)


def chat(message: str, session: str = "test-session-1", **extra):
    response = client.post("/api/chat", json={"message": message, "session_id": session, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_health():
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["schemes"] >= 70 and body["llm"] is False


def test_eligibility_conversation_remembers_the_profile():
    first = chat("I'm a farmer in UP with 2 acres and a daughter in Class 10", "conv-00001")
    assert first["intent"] == "eligibility"
    assert "PM-KISAN" in first["reply"] and "pmkisan.gov.in" in first["reply"]
    assert first["profile"]["state"] == "Uttar Pradesh"

    second = chat("45", "conv-00001")  # short answer to the follow-up question about age
    assert second["profile"]["age"] == 45 and second["profile"]["occupation"] == "farmer"
    assert any(m["scheme_id"] == "kcc" and m["status"] == "eligible" for m in second["matches"])


def test_hindi_gets_a_hindi_reply():
    result = chat("मैं बिहार की विधवा हूँ, उम्र 52 साल, मेरे पास राशन कार्ड है", "conv-00002")
    assert result["language"] == "hi"
    assert "विधवा पेंशन" in result["reply"]


def test_scheme_question_uses_retrieval():
    result = chat("PM Kisan ke liye kya documents chahiye?", "conv-00003")
    assert result["intent"] == "scheme_question"
    assert "pmkisan.gov.in" in result["reply"]
    assert result["profile"] == {}  # asking about a farmer scheme does not make you a farmer


def test_reset_forgets_the_profile():
    chat("I am a 30 year old woman in Odisha", "conv-00004")
    assert chat("reset", "conv-00004")["profile"] == {}
    assert chat("hello", "conv-00004")["profile"] == {}


def test_input_validation():
    assert client.post("/api/chat", json={"message": "", "session_id": "conv-00005"}).status_code == 422
    assert client.post("/api/chat", json={"message": "hi", "session_id": "bad id!"}).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 5000, "session_id": "conv-00005"}).status_code == 422


def test_schemes_endpoint_hides_internal_rules():
    schemes = client.get("/api/schemes").json()
    assert len(schemes) >= 70 and "rules" not in schemes[0] and schemes[0]["url"].startswith("https://")


def test_voice_endpoint_reports_when_speech_is_not_configured():
    response = client.post("/api/voice", data={"session_id": "conv-00006"},
                           files={"audio": ("voice.webm", b"\x00" * 100, "audio/webm")})
    assert response.status_code == 503


def _sign(url: str, params: dict[str, str], token: str = "test-token") -> str:
    payload = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()


def test_whatsapp_webhook_rejects_unsigned_requests():
    response = client.post("/webhooks/whatsapp", data={"From": "whatsapp:+910000000000", "Body": "hi"})
    assert response.status_code == 403


def test_whatsapp_webhook_replies_through_twilio(monkeypatch: pytest.MonkeyPatch):
    sent = []
    monkeypatch.setattr(whatsapp, "send", lambda to, body: sent.append((to, body)))
    form = {"From": "whatsapp:+910000000000", "Body": "I am a farmer in Bihar with 3 acres", "NumMedia": "0"}
    response = client.post("/webhooks/whatsapp", data=form,
                           headers={"X-Twilio-Signature": _sign("http://testserver/webhooks/whatsapp", form)})
    assert response.status_code == 200 and "<Response>" in response.text
    assert len(sent) == 1 and sent[0][0] == form["From"] and "PM-KISAN" in sent[0][1]


def test_long_replies_are_split_for_whatsapp():
    text = "\n\n".join(f"Scheme {n}: " + "x" * 400 for n in range(8))
    parts = whatsapp.chunk(text)
    assert len(parts) > 1 and all(len(p) <= whatsapp.MAX_BODY for p in parts)
    assert "\n\n".join(parts) == text


def test_short_answers_fill_the_right_field_and_keep_the_language():
    chat("मैं किसान हूँ, मेरे पास 2 एकड़ ज़मीन है", "conv-00010")  # asks for state and age
    second = chat("45", "conv-00010")
    assert second["profile"]["age"] == 45 and second["language"] == "hi"
    third = chat("200000", "conv-00010")
    assert third["profile"]["annual_income"] == 200000 and third["profile"]["age"] == 45


def test_question_mark_does_not_discard_what_the_person_said_about_themself():
    result = chat("kisan hoon Bihar se, 3 acre zameen, kya milega?", "conv-00011")
    assert result["intent"] == "eligibility" and result["profile"]["occupation"] == "farmer"


@pytest.mark.parametrize("junk", ["   ", "😀😀", "?", "12345678901234567890", "<script>alert(1)</script>"])
def test_odd_input_never_crashes(junk):
    assert chat(junk, "conv-00012")["reply"]


def test_security_headers_and_rate_limit(monkeypatch: pytest.MonkeyPatch):
    from app import main
    from app.ratelimit import RateLimiter
    assert client.get("/").headers["x-content-type-options"] == "nosniff"
    monkeypatch.setattr(main, "api_limiter", RateLimiter(2))
    codes = [client.get("/api/schemes", headers={"X-Forwarded-For": f"10.0.0.{n}"}).status_code for n in range(4)]
    assert codes == [200, 200, 429, 429]  # a forged X-Forwarded-For does not reset the limit


def test_whatsapp_ignores_twilio_retries_of_the_same_message(monkeypatch: pytest.MonkeyPatch):
    sent = []
    monkeypatch.setattr(whatsapp, "send", lambda to, body: sent.append(body))
    form = {"From": "whatsapp:+910000000001", "Body": "I am a farmer in Bihar", "MessageSid": "SM123"}
    whatsapp.handle_incoming(form)
    whatsapp.handle_incoming(form)
    assert len(sent) == 1


def test_media_is_only_downloaded_from_twilio():
    with pytest.raises(ValueError):
        whatsapp._download("https://evil.example/voice.ogg")
    with pytest.raises(ValueError):
        whatsapp._download("http://api.twilio.com/voice.ogg")


def test_dotenv_values_reach_the_process_environment(tmp_path, monkeypatch: pytest.MonkeyPatch):
    import os

    from dotenv import load_dotenv
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=test-value\n")
    load_dotenv(tmp_path / ".env")
    assert os.environ.pop("ANTHROPIC_API_KEY") == "test-value"
