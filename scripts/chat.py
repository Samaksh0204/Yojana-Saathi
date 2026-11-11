"""Chat with the assistant in the terminal. Uses the same run_agent() as the web app and WhatsApp.

    python -m scripts.chat                      # new conversation
    python -m scripts.chat --session my-test    # continue a named conversation

Commands: /reset  /profile  /lang hi|en|auto  /quit
"""
import argparse
import json
import logging
import sys
import uuid

from app.graph import run_agent
from app.lang import LANGUAGES
from app.sessions import get_store, session_key

HELP = "Commands: /reset (forget me)  /profile (what you know about me)  /lang hi|en|auto  /quit"


def parse_command(line: str) -> tuple[str, str] | None:
    """('reset', ''), ('lang', 'hi') ... or None when the line is an ordinary message.

    Unknown or malformed commands come back as ('error', explanation) rather than being sent to the agent.
    """
    line = line.strip()
    if not line.startswith("/"):
        return None
    name, _, argument = line[1:].partition(" ")
    name, argument = name.lower(), argument.strip().lower()
    if name in ("reset", "profile", "quit", "help") and not argument:
        return name, ""
    if name == "exit" and not argument:
        return "quit", ""
    if name == "lang":
        if argument == "auto" or argument in LANGUAGES:
            return "lang", argument
        return "error", "Use /lang followed by a language code such as hi or en, or /lang auto."
    return "error", f"Unknown command '{line}'. {HELP}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", default=None, help="conversation name; reuse it to continue later")
    parser.add_argument("--channel", choices=["web", "whatsapp"], default="web",
                        help="reply style to preview (WhatsApp replies are shorter)")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stdin):
        stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)

    session = session_key("cli", args.session or uuid.uuid4().hex)
    language: str | None = None
    print(f"Yojana Saathi terminal chat. Tell me about yourself in English or Hindi.\n{HELP}\n")
    while True:
        try:
            line = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        command = parse_command(line)
        if command is None:
            result = run_agent(line, session, args.channel, language)
            print(f"\n[{result['engine']} · {result['intent']} · {result['language']}]\n{result['reply']}\n")
            continue
        name, argument = command
        if name == "quit":
            break
        if name == "reset":
            get_store().delete(session)
            print("Forgotten. Start again whenever you like.\n")
        elif name == "profile":
            profile, asked, _ = get_store().load(session)
            print(json.dumps(profile.known_fields(), ensure_ascii=False, indent=2))
            print(f"Open questions: {asked or 'none'}\n")
        elif name == "lang":
            language = None if argument == "auto" else argument
            print(f"Reply language: {LANGUAGES.get(argument, 'auto-detect')}\n")
        else:  # help or error
            print(f"{argument or HELP}\n")


if __name__ == "__main__":
    main()
