from scripts.chat import parse_command


def test_ordinary_messages_are_not_commands():
    assert parse_command("I am a farmer in Bihar") is None
    assert parse_command("मैं किसान हूँ") is None
    assert parse_command("my income is 5000/month") is None


def test_commands():
    assert parse_command("/reset") == ("reset", "")
    assert parse_command("  /PROFILE  ") == ("profile", "")
    assert parse_command("/quit") == ("quit", "")
    assert parse_command("/exit") == ("quit", "")
    assert parse_command("/lang hi") == ("lang", "hi")
    assert parse_command("/lang EN") == ("lang", "en")
    assert parse_command("/lang auto") == ("lang", "auto")


def test_bad_commands_are_reported_not_sent_to_the_agent():
    assert parse_command("/lang klingon")[0] == "error"
    assert parse_command("/lang")[0] == "error"
    assert parse_command("/delete everything")[0] == "error"
    assert parse_command("/reset now")[0] == "error"
