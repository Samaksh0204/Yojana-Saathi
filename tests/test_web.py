"""The structured data the web page draws from: cards, headline and one-tap answers."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def chat(message: str, session: str, **extra) -> dict:
    response = client.post("/api/chat", json={"message": message, "session_id": session, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_eligibility_reply_carries_cards_headline_and_questions():
    data = chat("I'm a farmer in UP with 2 acres and a daughter in Class 10", "web-cards-01")
    assert "eligible for" in data["headline"]
    by_id = {c["id"]: c for c in data["cards"]}
    kisan = by_id["pm-kisan"]
    assert kisan["status"] == "eligible" and kisan["url"] == "https://pmkisan.gov.in"
    assert kisan["reasons"] and kisan["documents"] and kisan["for"] is None
    sumangala = by_id["up-kanya-sumangala"]
    assert sumangala["status"] == "possible" and sumangala["for"] == "For your daughter" and sumangala["needs"]
    assert [c["id"] for c in data["cards"]] == [m["scheme_id"] for m in data["matches"]]  # same order as the engine
    fields = {f["field"]: f for f in data["followups"]}
    assert "age" in fields and fields["age"]["options"] == []  # free-text answer


def test_one_tap_answers_update_the_profile_without_parsing_text():
    chat("I am a 30 year old woman in Jharkhand", "web-cards-02")
    data = chat("Yes", "web-cards-02", facts={"bpl": True})
    assert data["profile"]["bpl"] is True and data["intent"] == "eligibility"
    assert any(c["id"] == "jh-maiyan-samman" and c["status"] == "eligible" for c in data["cards"])
    data = chat("Village", "web-cards-02", facts={"residence": "rural"})
    assert data["profile"]["residence"] == "rural" and data["profile"]["bpl"] is True


def test_one_tap_answers_are_offered_in_the_conversation_language():
    data = chat("मैं 40 साल की महिला हूँ, झारखंड से", "web-cards-03")
    options = {f["field"]: [o["label"] for o in f["options"]] for f in data["followups"]}
    hindi_first = ("हाँ", "गाँव", "किसान", "सामान्य", "अविवाहित")
    assert any(labels and labels[0] in hindi_first for labels in options.values())
    tapped = chat("हाँ", "web-cards-03", facts={"bpl": True})
    assert tapped["language"] == "hi" and tapped["headline"].startswith("आप")


def test_facts_are_validated():
    wrong = ({"age": 30}, {"residence": "moon"}, {"bpl": "maybe"}, {}, {"children": []}, {"is_govt_employee": False})
    for bad in wrong:
        response = client.post("/api/chat", json={"message": "x", "session_id": "web-cards-04", "facts": bad})
        assert response.status_code == 422, bad


def test_scheme_question_returns_an_info_card():
    data = chat("PM Kisan ke liye kya documents chahiye?", "web-cards-05")
    assert [c["status"] for c in data["cards"]] == ["info"] and data["cards"][0]["id"] == "pm-kisan"
    assert data["followups"] == [] and data["headline"] is None


def test_greeting_has_no_cards():
    data = chat("hello", "web-cards-06")
    assert data["cards"] == [] and data["followups"] == []


def test_page_is_served_with_its_markup():
    page = client.get("/")
    assert page.status_code == 200 and 'id="thread"' in page.text and "/api/chat" in page.text
