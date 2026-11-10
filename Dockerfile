FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    SESSIONS_DB=/data/sessions.sqlite3

RUN useradd --create-home app && mkdir /data && chown app:app /data
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app app ./app
COPY --chown=app:app data ./data
COPY --chown=app:app scripts ./scripts
RUN chown app:app /srv
USER app

# Build the vector index at image build time so containers start instantly
# (this also bakes the embedding model into the image).
RUN python -m scripts.ingest

VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8000\")}/health')"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
