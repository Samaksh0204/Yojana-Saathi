import logging
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import speech, whatsapp
from .catalog import load_schemes
from .config import get_settings
from .graph import run_agent
from .lang import LANGUAGES
from .retriever import get_retriever
from .sessions import get_store, session_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("yojana")
settings = get_settings()
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Yojana Saathi", version="1.0.0",
              description="Multilingual government scheme eligibility assistant")
if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Per-IP sliding window on the public API (each call can cost LLM tokens)."""
    if request.url.path.startswith("/api/"):
        ip = (request.headers.get("x-forwarded-for") or request.client.host or "?").split(",")[0].strip()
        window, now = _hits[ip], time.monotonic()
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= settings.rate_limit_per_minute:
            return JSONResponse({"detail": "Too many requests. Please wait a minute."}, status_code=429)
        window.append(now)
    return await call_next(request)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=settings.max_message_chars)
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    language: Optional[str] = Field(None, description="Force a reply language (ISO 639-1); omit to auto-detect")


@app.get("/health")
def health():
    return {"status": "ok", "schemes": len(load_schemes()), "llm": settings.llm_enabled,
            "speech": speech.provider(), "vector_search": get_retriever().collection is not None}


@app.post("/api/chat")
def chat(body: ChatRequest):
    return run_agent(body.message, session_key("web", body.session_id), "web", body.language)


@app.post("/api/voice")
async def voice(audio: UploadFile = File(...), session_id: str = Form(..., min_length=8, max_length=64,
                                                                     pattern=r"^[A-Za-z0-9_-]+$"),
                language: Optional[str] = Form(None)):
    data = await audio.read(settings.max_audio_bytes + 1)
    if len(data) > settings.max_audio_bytes:
        raise HTTPException(413, "Audio file is too large")
    hint = language if language in LANGUAGES else None
    try:
        transcript = speech.transcribe(data, audio.filename or "audio.webm",
                                       audio.content_type or "audio/webm", hint)
    except speech.SpeechUnavailable:
        raise HTTPException(503, "Voice input is not configured on this server")
    except Exception:
        log.exception("Transcription failed")
        raise HTTPException(502, "Could not transcribe the audio")
    if not transcript:
        raise HTTPException(422, "Could not hear anything in the recording")
    result = run_agent(transcript[:settings.max_message_chars], session_key("web", session_id), "web", hint)
    return {"transcript": transcript, **result}


@app.delete("/api/session/{session_id}")
def forget(session_id: str):
    get_store().delete(session_key("web", session_id))
    return {"deleted": True}


@app.get("/api/schemes")
def schemes():
    return [s.model_dump(exclude={"rules"}) for s in load_schemes()]


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request, background: BackgroundTasks):
    form = {key: str(value) for key, value in (await request.form()).items()}
    if settings.twilio_validate_signature:
        if not settings.twilio_auth_token:
            raise HTTPException(503, "WhatsApp is not configured")
        url = (settings.public_base_url.rstrip("/") + request.url.path) if settings.public_base_url \
            else str(request.url)
        if not whatsapp.valid_signature(url, form, request.headers.get("X-Twilio-Signature", ""),
                                        settings.twilio_auth_token):
            raise HTTPException(403, "Invalid Twilio signature")
    # Reply asynchronously through the REST API; acknowledge the webhook straight away.
    background.add_task(whatsapp.handle_incoming, form)
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
