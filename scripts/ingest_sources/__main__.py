"""Run the ingestion pipeline.

    python -m scripts.ingest_sources                    # every source in sources.json
    python -m scripts.ingest_sources --source manual    # one source
    python -m scripts.ingest_sources --dry-run          # fetch and cache only, no LLM

Output goes to storage/proposals/ as "pending". Review with `python -m scripts.review`.
"""
import argparse
import logging
import sys

from app.config import get_settings

from . import extract, proposals
from .fetcher import Fetcher, load_sources, local_documents


def run(source_id: str | None = None, limit: int | None = None, dry_run: bool = False,
        refresh: bool = False) -> dict:
    settings = get_settings()
    fetcher = Fetcher()
    summary = {"documents": 0, "candidates": 0, "proposed": [], "rejected": [], "skipped": []}
    known = {sid: entry["name"] for sid, (_, entry) in proposals.read_catalogue().items()}
    seen_ids: set[str] = set()

    for source in load_sources():
        if source_id and source["id"] != source_id:
            continue
        if source["type"] == "local":
            documents, skipped = local_documents(source)
            summary["skipped"] += skipped
        else:
            documents = [doc for url in source.get("seed_urls", [])[:limit]
                         if (doc := fetcher.fetch(source, url, refresh))]
        for document in documents[:limit]:
            summary["documents"] += 1
            if dry_run:
                continue
            candidates = extract.extract(document, known)
            if candidates is None:
                summary["skipped"].append((document.url, "extraction failed or the text is too long to send"))
                continue
            for candidate in candidates:
                summary["candidates"] += 1
                problems = extract.check(candidate, document, source["official_domains"])
                if candidate.scheme.id in seen_ids:
                    problems.append(f"duplicate id '{candidate.scheme.id}' in this run")
                if problems:
                    summary["rejected"].append((candidate.scheme.id, problems))
                    continue
                seen_ids.add(candidate.scheme.id)
                proposals.save(candidate, document, settings.anthropic_model)
                summary["proposed"].append(candidate.scheme.id)
    summary["skipped"] += fetcher.skipped
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", help="only this source id from sources.json")
    parser.add_argument("--limit", type=int, help="at most this many documents per source")
    parser.add_argument("--dry-run", action="store_true", help="fetch and cache only; do not call the LLM")
    parser.add_argument("--refresh", action="store_true", help="re-download instead of using the cache")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")

    if not args.dry_run and not get_settings().llm_enabled:
        sys.exit("Extraction needs ANTHROPIC_API_KEY in .env (or use --dry-run to only fetch).")
    summary = run(args.source, args.limit, args.dry_run, args.refresh)

    print(f"\nDocuments read : {summary['documents']}")
    print(f"Candidates     : {summary['candidates']}")
    print(f"Proposed       : {len(summary['proposed'])}  {summary['proposed']}")
    print(f"Rejected       : {len(summary['rejected'])}")
    for scheme_id, problems in summary["rejected"]:
        print(f"  - {scheme_id}: " + "; ".join(problems))
    print(f"Skipped        : {len(summary['skipped'])}")
    for item, reason in summary["skipped"]:
        print(f"  - {item}: {reason}")
    if summary["proposed"]:
        print("\nNothing has been added to the catalogue. Review with: python -m scripts.review list")


if __name__ == "__main__":
    main()
