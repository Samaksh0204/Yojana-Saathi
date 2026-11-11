"""Polite fetching: terms and robots.txt checks, 1 request/second per host, cached raw responses."""
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.config import ROOT

log = logging.getLogger("ingest")
SOURCES_FILE = Path(__file__).parent / "sources.json"
RAW_DIR = ROOT / "storage" / "raw"
# Says what this is and how it behaves; deliberately carries no name, email or other personal data.
USER_AGENT = ("YojanaSaathi-Ingest/1.0 (offline catalogue builder for a public-benefit scheme assistant; "
              "at most 1 request per second; output is reviewed by a person)")
MIN_INTERVAL = 1.0  # seconds between requests to the same host


@dataclass
class Document:
    url: str
    text: str
    fetched_at: str
    raw_file: str
    source_id: str


def load_sources(path: Path = SOURCES_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_official(url: str, domains: list[str]) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and any(host == d or host.endswith("." + d) for d in domains)


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skipping += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data):
        if not self._skipping and data.strip():
            self.parts.append(data.strip())


def to_text(raw: bytes, content_type: str, name: str = "") -> str:
    """Visible text of an HTML page, PDF or plain-text file."""
    kind = content_type.lower()
    if "pdf" in kind or name.lower().endswith(".pdf"):
        import io

        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    text = raw.decode("utf-8", errors="replace")
    if "html" in kind or name.lower().endswith((".html", ".htm")):
        parser = _TextExtractor()
        parser.feed(text)
        return "\n".join(parser.parts)
    return text


class Fetcher:
    def __init__(self, raw_dir: Path = RAW_DIR, client: httpx.Client | None = None,
                 sleep=time.sleep, clock=time.monotonic) -> None:
        self.raw_dir = raw_dir
        self.client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30,
                                             follow_redirects=False)
        self._sleep, self._clock = sleep, clock
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self.skipped: list[tuple[str, str]] = []  # (url, reason) - reported at the end of a run

    # -- politeness ---------------------------------------------------------
    def _get(self, url: str) -> httpx.Response:
        host = urlparse(url).hostname or ""
        wait = self._last_request.get(host, -1e9) + self._interval(host) - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_request[host] = self._clock()
        return self.client.get(url)

    def _interval(self, host: str) -> float:
        robots = self._robots.get(host)
        delay = robots.crawl_delay(USER_AGENT) if robots else None
        return max(MIN_INTERVAL, float(delay or 0))

    def _robots_for(self, base_url: str) -> RobotFileParser | None:
        """Parsed robots.txt, or None when it could not be read (then nothing is fetched)."""
        host = urlparse(base_url).hostname or ""
        if host not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                response = self._get(base_url.rstrip("/") + "/robots.txt")
                if response.status_code == 404:
                    parser.parse([])  # no robots.txt: nothing is disallowed
                elif response.status_code == 200:
                    parser.parse(response.text.splitlines())
                else:
                    parser = None
            except httpx.HTTPError:
                parser = None
            self._robots[host] = parser
        return self._robots[host]

    def permitted(self, source: dict, url: str) -> tuple[bool, str]:
        if source.get("terms_status") != "allowed":
            return False, f"site terms are '{source.get('terms_status')}': {source.get('notes', '')[:120]}"
        base, target = urlparse(source["base_url"]), urlparse(url)
        if target.scheme != "https" or target.hostname != base.hostname:
            return False, "not an https URL on the source's own host"
        if not any(target.path.startswith(prefix) for prefix in source.get("allowed_paths", [])):
            return False, "path is not in the source's allowed_paths"
        robots = self._robots_for(source["base_url"])
        if robots is None:
            return False, "robots.txt could not be read"
        if not robots.can_fetch(USER_AGENT, url):
            return False, "disallowed by robots.txt"
        return True, ""

    # -- fetching -----------------------------------------------------------
    def fetch(self, source: dict, url: str, refresh: bool = False) -> Document | None:
        ok, reason = self.permitted(source, url)
        if not ok:
            log.warning("SKIP %s (%s)", url, reason)
            self.skipped.append((url, reason))
            return None
        folder = self.raw_dir / (urlparse(url).hostname or "unknown")
        stem = hashlib.sha256(url.encode()).hexdigest()[:16]
        meta_file, body_file = folder / f"{stem}.json", folder / f"{stem}.bin"
        if meta_file.exists() and body_file.exists() and not refresh:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        else:
            try:
                response = self._get(url)
            except httpx.HTTPError as exc:
                self.skipped.append((url, f"request failed: {type(exc).__name__}"))
                return None
            if response.status_code != 200:
                self.skipped.append((url, f"HTTP {response.status_code}"))
                return None
            folder.mkdir(parents=True, exist_ok=True)
            meta = {"url": url, "source_id": source["id"], "status": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            body_file.write_bytes(response.content)
            meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        text = to_text(body_file.read_bytes(), meta["content_type"])
        return Document(url=url, text=text, fetched_at=meta["fetched_at"], raw_file=str(body_file),
                        source_id=source["id"])


def local_documents(source: dict, root: Path = ROOT) -> tuple[list[Document], list[tuple[str, str]]]:
    """Files a person saved from an official site, listed in <folder>/manifest.json."""
    folder = root / source["folder"]
    manifest = folder / "manifest.json"
    documents, skipped = [], []
    if not manifest.exists():
        return documents, skipped
    for entry in json.loads(manifest.read_text(encoding="utf-8")):
        path, url = folder / entry.get("file", ""), entry.get("url", "")
        if not is_official(url, source["official_domains"]):
            skipped.append((entry.get("file", "?"), "manifest URL is not https on an official domain"))
        elif not path.is_file() or folder.resolve() not in path.resolve().parents:
            skipped.append((entry.get("file", "?"), "file not found in the manual sources folder"))
        else:
            saved = entry.get("saved_on") or datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
            documents.append(Document(url=url, text=to_text(path.read_bytes(), "", path.name),
                                      fetched_at=saved, raw_file=str(path), source_id=source["id"]))
    return documents, skipped


def normalise(text: str) -> str:
    """Collapse whitespace so a quote can be matched across line breaks in the source."""
    return re.sub(r"\s+", " ", text).strip()
