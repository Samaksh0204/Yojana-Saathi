"""Deterministic eligibility engine.

The LLM never decides eligibility. It only turns free text into a UserProfile;
this module checks that profile against each scheme's structured rules, so every
match is explainable and testable.

Each rule evaluates to True (met), False (not met) or None (we don't know yet).
"""
from collections import Counter
from typing import Any, Optional

from .schemas import Match, Scheme, UserProfile

UNORGANISED = {"agri_labourer", "street_vendor", "artisan", "construction_worker",
               "fisher", "unorganised_worker"}
# Rule key -> profile field to ask about when the rule can't be decided.
ASK = {
    "occupation": "occupation", "gender": "gender", "min_age": "age", "max_age": "age",
    "max_income": "annual_income", "caste": "caste", "residence": "residence", "bpl": "bpl",
    "owns_land": "owns_land", "max_land_acres": "land_acres", "is_student": "is_student",
    "education": "education", "marital": "marital_status", "no_pucca_house": "has_pucca_house",
}
RULE_KEYS = set(ASK) | {"disability", "widow", "pregnant", "minority", "exclude", "any_of"}
# When the unknown fact is about a child, ask about the child, not the parent.
CHILD_ASK = {"age": "child_age", "gender": "child_gender", "education": "child_education",
             "is_student": "child_education"}
MAX_MISSING = 2  # a "possible" match may depend on at most this many unknown facts


def validate_rules(rules: dict[str, Any], scheme_id: str) -> None:
    """Fail at start-up, not mid-conversation, if a scheme file has a typo in a rule name."""
    for key, value in rules.items():
        if key not in RULE_KEYS:
            raise ValueError(f"Scheme '{scheme_id}' uses unknown rule '{key}'")
        if key == "any_of":
            for alternative in value:
                validate_rules(alternative, scheme_id)


def _occupations(p: UserProfile) -> Optional[set[str]]:
    occ = set()
    if p.occupation:
        occ.add(p.occupation)
        if p.occupation in UNORGANISED:
            occ.add("unorganised_worker")
    if p.is_student:
        occ.add("student")
    return occ or None


def _is_student(p: UserProfile) -> Optional[bool]:
    if p.is_student is not None:
        return p.is_student
    if p.occupation:
        return p.occupation == "student"
    if p.age is not None and p.age > 30:
        return False  # not worth asking; a mature student will say so
    return None


# A "possible" match that hinges on these is a guess, so it is used to pick the
# next question but not shown to the user as a likely scheme.
SPECULATIVE = {"occupation", "is_student", "child_gender"}


def shown(matches: list[Match]) -> list[Match]:
    return [m for m in matches if not SPECULATIVE & set(m.missing)]


def _check(key: str, want: Any, p: UserProfile) -> Optional[bool]:
    if key == "occupation":
        occ = _occupations(p)
        return None if occ is None else bool(occ & set(want))
    if key == "gender":
        return None if p.gender is None else p.gender in want
    if key == "min_age":
        return None if p.age is None else p.age >= want
    if key == "max_age":
        return None if p.age is None else p.age <= want
    if key == "max_income":
        if p.annual_income is not None:
            return p.annual_income <= want
        return True if p.bpl else None  # a BPL card implies income under scheme ceilings
    if key == "caste":
        return None if p.caste is None else p.caste in want
    if key == "residence":
        return None if p.residence is None else p.residence == want
    if key == "bpl":
        return p.bpl
    if key == "owns_land":
        if p.owns_land is not None:
            return p.owns_land
        return True if (p.land_acres or 0) > 0 else None
    if key == "max_land_acres":
        return None if p.land_acres is None else p.land_acres <= want
    if key == "is_student":
        return _is_student(p)
    if key == "education":
        if p.education is None:
            return False if _is_student(p) is False else None
        return p.education in want
    if key == "marital":
        return None if p.marital_status is None else p.marital_status in want
    if key == "no_pucca_house":
        return None if p.has_pucca_house is None else not p.has_pucca_house
    # Opt-in facts: people mention these when they apply, so unknown counts as "no".
    if key == "disability":
        return bool(p.disability)
    if key == "widow":
        return p.marital_status == "widowed"
    if key == "pregnant":
        return bool(p.pregnant) and p.gender != "male"
    if key == "minority":
        return bool(p.minority)
    raise ValueError(f"Unknown rule key: {key}")


def _evaluate(rules: dict[str, Any], p: UserProfile) -> tuple[bool, list[str], list[str]]:
    """Returns (not_rejected, passed_rule_keys, missing_profile_fields)."""
    passed: list[str] = []
    missing: list[str] = []
    for key, want in rules.items():
        if key == "exclude":
            if ("govt_employee" in want and p.is_govt_employee) or \
               ("taxpayer" in want and p.pays_income_tax):
                return False, [], []
            continue
        if key == "any_of":
            options = [_evaluate(alt, p) for alt in want]
            alive = [o for o in options if o[0]]
            if not alive:
                return False, [], []
            sure = [o for o in alive if not o[2]]
            if sure:
                passed += max(sure, key=lambda o: len(o[1]))[1]
            else:
                best = min(alive, key=lambda o: len(o[2]))
                passed += best[1]
                missing += best[2]
            continue
        result = _check(key, want, p)
        if result is False:
            return False, [], []
        if result is None:
            missing.append(ASK[key])
        else:
            passed.append(key)
    return True, passed, list(dict.fromkeys(missing))


def _candidates(p: UserProfile) -> list[tuple[str, UserProfile]]:
    """The user plus each child, since many schemes are claimed on a child's behalf."""
    out = [("self", p)]
    for child in p.children:
        label = {"female": "daughter", "male": "son"}.get(child.gender or "", "child")
        out.append((label, UserProfile(
            age=child.age, gender=child.gender, education=child.education,
            is_student=child.education is not None or None,
            occupation="student" if child.education else None,
            state=p.state, residence=p.residence, caste=p.caste, minority=p.minority,
            annual_income=p.annual_income, bpl=p.bpl, has_pucca_house=p.has_pucca_house,
            marital_status="single", pregnant=False, owns_land=False,
            is_govt_employee=False, pays_income_tax=p.pays_income_tax,
        )))
    return out


def match_schemes(profile: UserProfile, schemes: list[Scheme]) -> list[Match]:
    matches: list[Match] = []
    for scheme in schemes:
        best: Optional[Match] = None
        for label, person in _candidates(profile):
            if scheme.child_only and label == "self":
                continue
            passed: list[str] = []
            if scheme.states:
                # State schemes are only shown once we know the state matches.
                if person.state not in scheme.states:
                    continue
                passed.append("state")
            ok, rule_passed, missing = _evaluate(scheme.rules, person)
            passed += rule_passed
            if not ok or not passed or len(missing) > MAX_MISSING:
                continue
            if label != "self":
                missing = list(dict.fromkeys(CHILD_ASK.get(f, f) for f in missing))
            match = Match(scheme_id=scheme.id, beneficiary=label, passed=passed, missing=missing,
                          status="possible" if missing else "eligible")
            if best is None or (best.status == "possible" and match.status == "eligible"):
                best = match
        if best:
            matches.append(best)
    # Confirmed first, then the most specific (most conditions met) first.
    matches.sort(key=lambda m: (m.status != "eligible", len(m.missing), -len(m.passed)))
    return matches


def follow_up_fields(matches: list[Match], limit: int = 2) -> list[str]:
    """The unknown facts that would settle the most 'possible' schemes."""
    counts = Counter(f for m in matches if m.status == "possible" for f in m.missing)
    return [field for field, _ in counts.most_common(limit)]
