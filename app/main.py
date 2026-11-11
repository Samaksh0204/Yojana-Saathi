import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import speech, whatsapp
from .catalog import load_schemes
from .config import get_settings
from .graph import build_graph, run_agent
from .lang import LANGUAGES
from .ratelimit import RateLimiter
from .retriever import get_retriever
from .sessions import get_store, session_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("yojana")
settings = get_settings()
STATIC = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load everything up front: bad scheme data stops the deploy, and the first user is not kept waiting.
    load_schemes()
    get_retriever()
    build_graph()
    get_store()
    log.info("Ready: %d schemes, llm=%s, speech=%s, vector_search=%s", len(load_schemes()),
             settings.llm_enabled, speech.provider(), get_retriever().collection is not None)
    yield


app = FastAPI(title="Yojana Saathi", version="1.1.0", lifespan=lifespan,
              description="Multilingual government scheme eligibility assistant")
if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

api_limiter = RateLimiter(settings.rate_limit_per_minute)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                               "style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'",
}


@app.middleware("http")
async def guard(request: Request, call_next):
    """Per-IP rate limit on the public API (each call can cost LLM tokens) plus security headers."""
    if request.url.path.startswith("/api/"):
        # request.client is the real caller: uvicorn runs with --proxy-headers behind the platform's
        # proxy. Reading X-Forwarded-For here instead would let anyone dodge the limit by forging it.
        ip = request.client.host if request.client else "unknown"
        if not api_limiter.allow(ip):
            return JSONResponse({"detail": "Too many requests. Please wait a minute."}, status_code=429,
                                headers={"Retry-After": "60"})
    response = await call_next(request)
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):  # Swagger UI loads from a CDN
        response.headers.update(SECURITY_HEADERS)
    return response


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
        # Transcription and the agent are blocking calls: keep them off the event loop.
        transcript = await run_in_threadpool(speech.transcribe, data, audio.filename or "audio.webm",
                                             audio.content_type or "audio/webm", hint)
    except speech.SpeechUnavailable:
        raise HTTPException(503, "Voice input is not configured on this server") from None
    except Exception:
        log.exception("Transcription failed")
        raise HTTPException(502, "Could not transcribe the audio") from None
    if not transcript:
        raise HTTPException(422, "Could not hear anything in the recording")
    result = await run_in_threadpool(run_agent, transcript[:settings.max_message_chars],
                                     session_key("web", session_id), "web", hint)
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


@app.api_route("/", methods=["GET", "HEAD"])  # uptime monitors probe with HEAD
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)  # the page carries its icon inline
