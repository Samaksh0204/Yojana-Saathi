"""Measure the pipeline on eval/testset.json.

    python -m scripts.evaluate              # rule-based extractor (no API key needed)
    python -m scripts.evaluate --mode llm   # Claude extraction (uses API credits)

Three numbers, from most to least direct:
  1. Label checks    - hand-written must_include / must_exclude schemes per persona.
  2. Scheme match F1 - schemes found from the free-text message vs. schemes found
                       from the hand-written gold profile (what extraction errors cost).
  3. Field accuracy  - extracted profile fields vs. the gold profile.
"""
import argparse
import json
import sys

from app import llm
from app.catalog import load_schemes
from app.config import ROOT
from app.extract import extract_profile, normalise_state
from app.rules import match_schemes
from app.schemas import UserProfile


def eligible_ids(profile: UserProfile) -> set[str]:
    return {m.scheme_id for m in match_schemes(profile, load_schemes()) if m.status == "eligible"}


def extract(text: str, mode: str) -> UserProfile:
    if mode == "rules":
        return extract_profile(text)
    parsed = llm.understand(text, UserProfile(), [])
    if parsed is None:
        sys.exit("Claude call failed - check ANTHROPIC_API_KEY / network (see log above).")
    parsed.profile.state = normalise_state(parsed.profile.state) or parsed.profile.state
    return parsed.profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["rules", "llm"], default="rules")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    cases = json.loads((ROOT / "eval" / "testset.json").read_text(encoding="utf-8"))
    if args.mode == "rules":
        cases = [c for c in cases if not c.get("llm_only")]

    fields_ok = fields_total = tp = fp = fn = checks_ok = checks_total = perfect = 0
    for case in cases:
        got = extract(case["text"], args.mode)
        gold = UserProfile(**case["profile"])
        got_dump = got.model_dump()
        wrong = []
        for field, value in gold.known_fields().items():
            fields_total += 1
            if got_dump[field] == value:
                fields_ok += 1
            else:
                wrong.append(f"{field}: got {got_dump[field]!r}, want {value!r}")

        predicted, expected = eligible_ids(got), eligible_ids(gold)
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        perfect += predicted == expected

        missed = [s for s in case["must_include"] if s not in predicted]
        leaked = [s for s in case["must_exclude"] if s in predicted]
        checks_total += len(case["must_include"]) + len(case["must_exclude"])
        checks_ok += len(case["must_include"]) - len(missed) + len(case["must_exclude"]) - len(leaked)
        # Gold labels must agree with the rules engine, or the test set itself is wrong.
        for s in case["must_include"]:
            assert s in expected, f"{case['id']}: gold profile is not eligible for {s}"
        for s in case["must_exclude"]:
            assert s not in expected, f"{case['id']}: gold profile is eligible for {s}"

        if args.verbose or missed or leaked:
            status = "ok  " if not (missed or leaked) else "FAIL"
            print(f"[{status}] {case['id']} ({case['lang']})")
            for line in wrong:
                print(f"         field {line}")
            if missed:
                print(f"         missed: {missed}")
            if leaked:
                print(f"         wrongly included: {leaked}")

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    print(f"\nMode: {args.mode}   Personas: {len(cases)}   Schemes in catalogue: {len(load_schemes())}")
    print(f"Label checks passed      : {checks_ok}/{checks_total} ({checks_ok / checks_total:.1%})")
    print(f"Scheme match  precision  : {precision:.1%}   recall: {recall:.1%}   F1: {f1:.1%}")
    print(f"Personas with exact match: {perfect}/{len(cases)} ({perfect / len(cases):.1%})")
    print(f"Profile field accuracy   : {fields_ok}/{fields_total} ({fields_ok / fields_total:.1%})")


if __name__ == "__main__":
    main()
