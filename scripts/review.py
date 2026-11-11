"""Review proposals from the ingestion pipeline. Nothing reaches the catalogue without `approve`.

    python -m scripts.review list
    python -m scripts.review show <id>
    python -m scripts.review approve <id>
    python -m scripts.review reject <id>
"""
import argparse
import json
import sys

from scripts.ingest_sources import proposals
from scripts.ingest_sources.fetcher import load_sources


def official_domains() -> list[str]:
    return sorted({domain for source in load_sources() for domain in source["official_domains"]})


def show(proposal: dict) -> str:
    scheme, change = proposal["scheme"], proposal["diff"]
    lines = [f"{scheme['id']}  [{proposal['status']}]  ({change['kind']})", f"  {scheme['name']}",
             f"  source : {proposal['provenance']['source_url']} (fetched {proposal['provenance']['fetched_at']})",
             f"  benefit: {scheme['benefit']}", f"  rules  : {json.dumps(scheme['rules'], ensure_ascii=False)}"]
    for field, values in change["fields"].items():
        lines.append(f"  changed {field}:\n      was: {json.dumps(values['old'], ensure_ascii=False)}"
                     f"\n      now: {json.dumps(values['new'], ensure_ascii=False)}")
    lines.append("  evidence (each quote was found word for word in the source):")
    lines += [f"    {item['field']}: \"{item['quote']}\"" for item in proposal["evidence"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    for name in ("show", "approve", "reject"):
        commands.add_parser(name).add_argument("id")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        if args.command == "list":
            items = proposals.list_all()
            for p in items:
                print(f"{p['status']:9} {p['diff']['kind']:10} {p['scheme']['id']:32} {p['scheme']['name']}")
            print(f"{len(items)} proposal(s), {sum(p['status'] == 'pending' for p in items)} pending")
        elif args.command == "show":
            print(show(proposals.load(args.id)))
        elif args.command == "approve":
            target = proposals.approve(args.id, official_domains())
            print(f"Approved '{args.id}' and wrote it to {target}.")
            print("Now run: python -m pytest -q   and   python -m scripts.ingest   (rebuilds the search index)")
        elif args.command == "reject":
            proposals.reject(args.id)
            print(f"Rejected '{args.id}'. The catalogue was not changed.")
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
