"""Speech-to-text with Whisper.

Providers: a local faster-whisper model (`pip install faster-whisper`; free, runs
on this machine) or OpenAI's hosted Whisper (`OPENAI_API_KEY`).
"""
import logging
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx

from .config import get_settings

log = logging.getLogger(__name__)
OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_MODEL = "whisper-1"
PROVIDERS = {"openai", "local", "off"}


class SpeechUnavailable(RuntimeError):
    pass


def _local_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def provider() -> str:
    """The provider that will actually be used: 'openai', 'local' or 'off'."""
    s = get_settings()
    choice = s.stt_provider.lower()
    if choice == "auto":
        return "openai" if s.openai_api_key else "local" if _local_installed() else "off"
    if choice not in PROVIDERS:
        log.warning("Unknown STT_PROVIDER '%s'; voice input is off", s.stt_provider)
        return "off"
    # An explicit choice that cannot work is reported as off, not discovered on the first voice note.
    if (choice == "openai" and not s.openai_api_key) or (choice == "local" and not _local_installed()):
        return "off"
    return choice


@lru_cache
def _local_model():
    from faster_whisper import WhisperModel

    return WhisperModel(get_settings().local_whisper_model, device="cpu", compute_type="int8")


def transcribe(audio: bytes, filename: str = "audio.ogg", content_type: str = "audio/ogg",
               language: Optional[str] = None) -> str:
    """`language` is an optional ISO 639-1 hint; Whisper auto-detects when it is None."""
    s = get_settings()
    name = provider()
    if name == "off":
        raise SpeechUnavailable("No speech-to-text provider configured")
    if len(audio) > s.max_audio_bytes:
        raise ValueError("Audio file is too large")

    if name == "openai":
        data = {"model": OPENAI_MODEL, "response_format": "json"}
        if language:
            data["language"] = language
        response = httpx.post(OPENAI_URL, headers={"Authorization": f"Bearer {s.openai_api_key}"}, data=data,
                              files={"file": (filename, audio, content_type)}, timeout=60)
        response.raise_for_status()
        return response.json()["text"].strip()

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(filename).name  # basename only: the name comes from the uploader
        path.write_bytes(audio)
        segments, _ = _local_model().transcribe(str(path), language=language)
        return " ".join(seg.text.strip() for seg in segments).strip()
