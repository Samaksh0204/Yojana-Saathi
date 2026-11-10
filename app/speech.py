"""Speech-to-text with Whisper.

Providers: Groq (hosted whisper-large-v3, fast, has a free tier), OpenAI
(whisper-1), or a local faster-whisper model (`pip install faster-whisper`).
"""
import logging
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx

from .config import get_settings

log = logging.getLogger(__name__)
HOSTED = {
    "groq": ("https://api.groq.com/openai/v1/audio/transcriptions", "whisper-large-v3"),
    "openai": ("https://api.openai.com/v1/audio/transcriptions", "whisper-1"),
}


class SpeechUnavailable(RuntimeError):
    pass


def provider() -> str:
    s = get_settings()
    if s.stt_provider != "auto":
        return s.stt_provider
    if s.groq_api_key:
        return "groq"
    if s.openai_api_key:
        return "openai"
    try:
        import faster_whisper  # noqa: F401
        return "local"
    except ImportError:
        return "off"


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

    if name in HOSTED:
        url, model = HOSTED[name]
        key = s.groq_api_key if name == "groq" else s.openai_api_key
        data = {"model": model, "response_format": "json"}
        if language:
            data["language"] = language
        response = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, data=data,
                              files={"file": (filename, audio, content_type)}, timeout=60)
        response.raise_for_status()
        return response.json()["text"].strip()

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        path.write_bytes(audio)
        segments, _ = _local_model().transcribe(str(path), language=language)
        return " ".join(seg.text.strip() for seg in segments).strip()
