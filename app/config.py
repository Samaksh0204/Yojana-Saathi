import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # --- LLM (Claude). "auto" = use it when credentials are present. ---
    llm_mode: str = "auto"  # auto | on | off
    anthropic_model: str = "claude-opus-5-5"
    llm_timeout_seconds: float = 60.0

    # --- Retrieval ---
    vector_search: str = "auto"  # auto | off  (BM25 is always on)
    data_dir: Path = ROOT / "data"
    chroma_dir: Path = ROOT / "storage" / "chroma"
    sessions_db: Path = ROOT / "storage" / "sessions.sqlite3"
    session_ttl_days: int = 30
    session_secret: str = ""  # random string; keys the hash of phone numbers / session ids

    # --- Speech to text ---
    stt_provider: str = "auto"  # auto | groq | openai | local | off
    groq_api_key: str = ""
    openai_api_key: str = ""
    local_whisper_model: str = "small"
    max_audio_bytes: int = 15 * 1024 * 1024

    # --- WhatsApp (Twilio) ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"  # Twilio sandbox number
    twilio_validate_signature: bool = True
    public_base_url: str = ""  # e.g. https://yojana-saathi.onrender.com

    # --- API hardening ---
    cors_origins: str = ""  # comma separated; empty = same-origin only
    rate_limit_per_minute: int = 30
    max_message_chars: int = 2000

    @property
    def llm_enabled(self) -> bool:
        if self.llm_mode == "off":
            return False
        if self.llm_mode == "on":
            return True
        return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
