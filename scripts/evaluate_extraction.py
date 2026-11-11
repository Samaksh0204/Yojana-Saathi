"""Score the ingestion extractor against hand-checked gold labels.

    python -m scripts.evaluate_extraction

Reads eval/extraction_gold/*.json. A gold file only counts once a person has
filled in `expected` from the official text and set `verified_by`; the saved
source text must sit at the file's `source_file` path. Uses the LLM (API credits).

Reports field-level precision and recall for amounts, age limits, income limits,
occupation and documents, and how many candidates the quote check threw out.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from app.config import ROOT, get_settings
from app.schemas import Scheme
from scripts.ingest_sources import extract
from scripts.ingest_sources.fetcher import Document, load_sources, to_text

GOLD_DIR = ROOT / "eval" / "extraction_gold"
FIELDS = ["amounts", "age_limits", "income_limits", "occupation", "documents"]
_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore)?", re.I)
_SCALE = {"lakh": 100_000, "lac": 100_000, "crore": 10_000_000}


def amounts_in(text: str) -> set[int]:
    return {int(float(number.replace(",", "")) * _SCALE.get((unit or "").lower(), 1))
            for number, unit in _AMOUNT.findall(text)}


def _rule_sets(rules: dict) -> list[dict]:
    return [rules, *(alt for alt in rules.get("any_of", []))]


def predicted_fields(scheme: Scheme) -> dict[str, set]:
    rule_sets = _rule_sets(scheme.rules)
    return {
        "amounts": amounts_in(scheme.benefit),
        "age_limits": {(key, r[key]) for r in rule_sets for key in ("min_age", "max_age") if key in r},
        "income_limits": {r["max_income"] for r in rule_sets if "max_income" in r},
        "occupation": {o for r in rule_sets for o in r.get("occupation", [])},
        "documents": set(scheme.documents),
    }


def expected_fields(expected: dict) -> dict[str, set]:
    ages = {(key, expected[key]) for key in ("min_age", "max_age") if expected.get(key) is not None}
    incomes = expected.get("max_income")
    incomes = set(incomes) if isinstance(incomes, list) else ({incomes} if incomes is not None else set())
    return {"amounts": set(expected.get("amounts", [])), "age_limits": ages, "income_limits": incomes,
            "occupation": set(expected.get("occupation", [])), "documents": set(expected.get("documents", []))}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - {"a", "an", "the", "of", "or", "and", "card", "copy"}


def same_document(a: str, b: str) -> bool:
    """Document names are free text ("Aadhaar card" vs "Aadhaar"): match on word overlap."""
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.5


def score(predicted: dict[str, set], expected: dict[str, set]) -> dict[str, tuple[int, int, int]]:
    """(true positives, false positives, false negatives) per field."""
    result = {}
    for field in FIELDS:
        got, want = predicted[field], expected[field]
        if field == "documents":
            matched_want = {w for w in want if any(same_document(g, w) for g in got)}
            matched_got = {g for g in got if any(same_document(g, w) for w in want)}
            result[field] = (len(matched_want), len(got - matched_got), len(want - matched_want))
        else:
            result[field] = (len(got & want), len(got - want), len(want - got))
    return result


def load_gold(gold_dir: Path = GOLD_DIR) -> tuple[list[dict], int]:
    """Verified gold entries, and how many files are still waiting for a person."""
    verified, pending = [], 0
    for path in sorted(gold_dir.glob("*.json")):
        gold = json.loads(path.read_text(encoding="utf-8"))
        source = gold_dir / (gold.get("source_file") or "")
        if gold.get("verified_by") and source.is_file():
            gold["_text"] = to_text(source.read_bytes(), "", source.name)
            verified.append(gold)
        else:
            pending += 1
    return verified, pending


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    gold, pending = load_gold()
    print(f"Gold files: {len(gold)} verified, {pending} not yet verified by a person")
    if not gold:
        print("Nothing to score. Fill in eval/extraction_gold/ first (see its README.md).")
        return
    if not get_settings().llm_enabled:
        sys.exit("Scoring runs the extractor, which needs ANTHROPIC_API_KEY in .env.")

    domains = sorted({d for s in load_sources() for d in s["official_domains"]})
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    candidates = rejected = quote_rejected = missing = 0
    for item in gold:
        document = Document(url=item["source_url"], text=item["_text"], fetched_at="", raw_file="",
                            source_id="gold")
        found = extract.extract(document, {item["scheme_id"]: item["scheme_id"]}) or []
        accepted = None
        for candidate in found:
            candidates += 1
            problems = extract.check(candidate, document, domains)
            if problems:
                rejected += 1
                quote_rejected += any("quote" in p or "evidence" in p for p in problems)
            elif accepted is None:
                accepted = candidate
        empty = {field: set() for field in FIELDS}
        predicted = predicted_fields(accepted.scheme) if accepted else empty
        missing += accepted is None
        for field, counts in score(predicted, expected_fields(item["expected"])).items():
            totals[field] = [a + b for a, b in zip(totals[field], counts, strict=True)]

    print(f"Candidates: {candidates}   rejected: {rejected} (quote check: {quote_rejected})   "
          f"gold schemes with no accepted candidate: {missing}\n")
    print(f"{'field':15} {'precision':>10} {'recall':>8}   tp  fp  fn")
    for field in FIELDS:
        tp, fp, fn = totals[field]
        precision = f"{tp / (tp + fp):.1%}" if tp + fp else "n/a"
        recall = f"{tp / (tp + fn):.1%}" if tp + fn else "n/a"
        print(f"{field:15} {precision:>10} {recall:>8}   {tp:2}  {fp:2}  {fn:2}")


if __name__ == "__main__":
    main()
