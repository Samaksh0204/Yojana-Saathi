"""Proposals: candidates waiting for a person to approve or reject them."""
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import ROOT
from app.rules import validate_rules
from app.schemas import Scheme

from .extract import Candidate
from .fetcher import Document, is_official

PROPOSALS_DIR = ROOT / "storage" / "proposals"
CATALOGUE_DIR = ROOT / "data" / "schemes"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_catalogue(catalogue_dir: Path | None = None) -> dict[str, tuple[Path, dict]]:
    """scheme id -> (file it lives in, raw entry)."""
    catalogue_dir = catalogue_dir or CATALOGUE_DIR
    found: dict[str, tuple[Path, dict]] = {}
    for path in sorted(catalogue_dir.glob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            found[entry["id"]] = (path, entry)
    return found


def diff(scheme: Scheme, catalogue: dict[str, tuple[Path, dict]]) -> dict:
    new = scheme.model_dump()
    if scheme.id not in catalogue:
        return {"kind": "new", "fields": {}}
    old = Scheme(**catalogue[scheme.id][1]).model_dump()
    changed = {key: {"old": old[key], "new": new[key]} for key in new if old[key] != new[key]}
    return {"kind": "changed" if changed else "unchanged", "fields": changed}


def save(candidate: Candidate, document: Document, model: str, proposals_dir: Path | None = None,
         catalogue_dir: Path | None = None) -> Path:
    proposals_dir = proposals_dir or PROPOSALS_DIR
    proposals_dir.mkdir(parents=True, exist_ok=True)
    path = proposals_dir / f"{candidate.scheme.id}.json"
    proposal = {
        "status": "pending",
        "scheme": candidate.scheme.model_dump(),
        "evidence": [e.model_dump() for e in candidate.evidence],
        "diff": diff(candidate.scheme, read_catalogue(catalogue_dir)),
        "provenance": {"source_id": document.source_id, "source_url": document.url,
                       "fetched_at": document.fetched_at, "raw_file": document.raw_file,
                       "extracted_by": model, "extracted_at": _now()},
    }
    path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load(scheme_id: str, proposals_dir: Path | None = None) -> dict:
    proposals_dir = proposals_dir or PROPOSALS_DIR
    path = proposals_dir / f"{scheme_id}.json"
    if not path.is_file() or path.parent.resolve() != proposals_dir.resolve():
        raise FileNotFoundError(f"No proposal named '{scheme_id}'")
    return json.loads(path.read_text(encoding="utf-8"))


def list_all(proposals_dir: Path | None = None) -> list[dict]:
    proposals_dir = proposals_dir or PROPOSALS_DIR
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(proposals_dir.glob("*.json"))]


def _decide(scheme_id: str, status: str, proposals_dir: Path) -> dict:
    proposal = load(scheme_id, proposals_dir)
    if proposal["status"] != "pending":
        raise ValueError(f"Proposal '{scheme_id}' is already {proposal['status']}")
    proposal["status"], proposal["decided_at"] = status, _now()
    return proposal


def reject(scheme_id: str, proposals_dir: Path | None = None) -> None:
    proposals_dir = proposals_dir or PROPOSALS_DIR
    proposal = _decide(scheme_id, "rejected", proposals_dir)
    (proposals_dir / f"{scheme_id}.json").write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")


def approve(scheme_id: str, official_domains: list[str], proposals_dir: Path | None = None,
            catalogue_dir: Path | None = None) -> Path:
    """The only code path that writes to the catalogue. Re-validates first: the file may have been edited."""
    proposals_dir, catalogue_dir = proposals_dir or PROPOSALS_DIR, catalogue_dir or CATALOGUE_DIR
    proposal = _decide(scheme_id, "approved", proposals_dir)
    scheme = Scheme(**proposal["scheme"])
    validate_rules(scheme.rules, scheme.id)
    if scheme.id != scheme_id:
        raise ValueError("The proposal's scheme id does not match its file name")
    if not is_official(scheme.url, official_domains):
        raise ValueError(f"Link '{scheme.url}' is not https on an official domain")

    catalogue = read_catalogue(catalogue_dir)
    target = catalogue[scheme.id][0] if scheme.id in catalogue else \
        catalogue_dir / ("central.json" if scheme.level == "central" else "states.json")
    entries = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    entry = scheme.model_dump(exclude_defaults=True) | {"id": scheme.id, "level": scheme.level}
    entries = [entry if e["id"] == scheme.id else e for e in entries]
    if scheme.id not in catalogue:
        entries.append(entry)
    target.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (proposals_dir / f"{scheme_id}.json").write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
