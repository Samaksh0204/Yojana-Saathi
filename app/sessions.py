"""Tiny SQLite session store: the profile gathered so far, per conversation.

Profiles hold sensitive facts (caste, income, disability), so WhatsApp numbers
are stored only as a keyed SHA-256 hash (set SESSION_SECRET) and rows expire after a TTL.
"""
import hashlib
import json
import sqlite3
import threading
import time
from functools import lru_cache

from .config import get_settings
from .schemas import UserProfile


def session_key(channel: str, user_id: str) -> str:
    secret = get_settings().session_secret
    return f"{channel}:{hashlib.sha256((secret + user_id).encode()).hexdigest()[:32]}"


class SessionStore:
    def __init__(self, path, ttl_days: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._ttl = ttl_days * 86400
        with self._lock, self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS sessions ("
                             "id TEXT PRIMARY KEY, profile TEXT, asked TEXT, language TEXT, updated REAL)")
            self._db.execute("DELETE FROM sessions WHERE updated < ?", (time.time() - self._ttl,))

    def load(self, session_id: str) -> tuple[UserProfile, list[str], str | None]:
        with self._lock:
            row = self._db.execute("SELECT profile, asked, language, updated FROM sessions WHERE id = ?",
                                   (session_id,)).fetchone()
        if not row or row[3] < time.time() - self._ttl:
            return UserProfile(), [], None
        return UserProfile(**json.loads(row[0])), json.loads(row[1]), row[2]

    def save(self, session_id: str, profile: UserProfile, asked: list[str], language: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?)",
                             (session_id, profile.model_dump_json(), json.dumps(asked), language, time.time()))

    def delete(self, session_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


@lru_cache
def get_store() -> SessionStore:
    settings = get_settings()
    return SessionStore(settings.sessions_db, settings.session_ttl_days)
