import os
import tempfile

# Must be set before the app is imported: tests run offline, with no LLM, vector index or network.
_tmp = tempfile.mkdtemp()
os.environ.update({
    "LLM_MODE": "off", "VECTOR_SEARCH": "off", "STT_PROVIDER": "off",
    "SESSIONS_DB": os.path.join(_tmp, "sessions.sqlite3"),
    "TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "test-token",
    "TWILIO_VALIDATE_SIGNATURE": "true", "PUBLIC_BASE_URL": "", "RATE_LIMIT_PER_MINUTE": "1000",
})
