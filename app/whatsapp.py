"""Twilio WhatsApp plumbing: verify webhooks, download voice notes, send replies."""
import base64
import hashlib
import hmac
import logging

import httpx

from .config import get_settings
from .graph import run_agent
from .lang import strings
from .sessions import session_key
from .speech import SpeechUnavailable, transcribe

log = logging.getLogger(__name__)
MAX_BODY = 1500  # Twilio rejects WhatsApp messages over 1600 characters


def valid_signature(url: str, params: dict[str, str], signature: str, auth_token: str) -> bool:
    """Twilio signs: full URL + every POST field (sorted by name) as name+value, HMAC-SHA1, base64."""
    payload = url + "".join(key + params[key] for key in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature or "")


def chunk(text: str, size: int = MAX_BODY) -> list[str]:
    """Split on blank lines so a scheme block is never cut in half if it can be avoided."""
    parts, current = [], ""
    for block in text.split("\n\n"):
        while len(block) > size:  # a single oversized block: hard split
            parts.append(block[:size])
            block = block[size:]
        if len(current) + len(block) + 2 > size and current:
            parts.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        parts.append(current)
    return parts


def send(to: str, body: str) -> None:
    s = get_settings()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json"
    with httpx.Client(auth=(s.twilio_account_sid, s.twilio_auth_token), timeout=20) as client:
        for part in chunk(body):
            response = client.post(url, data={"From": s.twilio_whatsapp_from, "To": to, "Body": part})
            if response.status_code >= 400:
                log.error("Twilio send failed (%s): %s", response.status_code, response.text[:300])
                return


def _download(media_url: str) -> bytes:
    s = get_settings()
    response = httpx.get(media_url, auth=(s.twilio_account_sid, s.twilio_auth_token),
                         follow_redirects=True, timeout=30)
    response.raise_for_status()
    return response.content


def handle_incoming(form: dict[str, str]) -> None:
    """Runs in a background task: Twilio only waits 15 seconds for the webhook itself."""
    sender = form.get("From", "")
    text = (form.get("Body") or "").strip()
    fallback = strings("hi")
    try:
        if int(form.get("NumMedia") or 0) > 0 and (form.get("MediaContentType0") or "").startswith("audio"):
            try:
                content_type = form["MediaContentType0"].split(";")[0]
                extension = content_type.split("/")[-1]
                text = transcribe(_download(form["MediaUrl0"]), f"voice.{extension}", content_type)
            except SpeechUnavailable:
                send(sender, f"{fallback['voice_off']}\n\n{strings('en')['voice_off']}")
                return
        if not text:
            send(sender, f"{fallback['welcome']}")
            return
        text = text[:get_settings().max_message_chars]
        result = run_agent(text, session_key("whatsapp", sender), channel="whatsapp")
        send(sender, result["reply"])
    except Exception:
        log.exception("Failed to handle a WhatsApp message")
        send(sender, f"{fallback['error']}\n\n{strings('en')['error']}")
