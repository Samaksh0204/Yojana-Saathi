from app.catalog import load_schemes
from app.rules import follow_up_fields, match_schemes
from app.schemas import Child, UserProfile


def results(profile: UserProfile) -> dict[str, str]:
    return {m.scheme_id: m.status for m in match_schemes(profile, load_schemes())}


def test_catalogue_loads_and_every_rule_key_is_supported():
    schemes = load_schemes()
    assert len(schemes) >= 70
    # An unsupported rule key raises ValueError, so matching a rich profile exercises them all.
    match_schemes(UserProfile(age=30, gender="female", state="Bihar", occupation="farmer",
                              annual_income=100000, caste="sc", residence="rural", bpl=True,
                              land_acres=1, education="undergraduate", marital_status="married",
                              has_pucca_house=False), schemes)


def test_farmer_with_land_gets_pm_kisan():
    r = results(UserProfile(occupation="farmer", land_acres=2, state="Uttar Pradesh"))
    assert r["pm-kisan"] == "eligible"
    assert "pm-svanidhi" not in r
    assert "mh-namo-shetkari" not in r  # another state's scheme


def test_taxpayer_farmer_is_excluded_from_pm_kisan():
    r = results(UserProfile(occupation="farmer", land_acres=10, pays_income_tax=True))
    assert "pm-kisan" not in r
    assert r["pmfby"] == "eligible"


def test_unknown_facts_give_possible_not_eligible():
    r = results(UserProfile(occupation="farmer", land_acres=2))
    assert r["pm-kmy"] == "possible"  # needs age
    r = results(UserProfile(occupation="farmer", land_acres=2, age=35))
    assert r["pm-kmy"] == "eligible"
    r = results(UserProfile(occupation="farmer", land_acres=2, age=45))
    assert "pm-kmy" not in r


def test_schemes_for_children_are_found_through_the_parent():
    parent = UserProfile(state="Uttar Pradesh", occupation="farmer", annual_income=100000, caste="sc",
                         children=[Child(gender="female", age=15, education="class_9_10")])
    matches = {m.scheme_id: m for m in match_schemes(parent, load_schemes())}
    assert matches["pre-matric-sc"].status == "eligible"
    assert matches["pre-matric-sc"].beneficiary == "daughter"
    assert matches["up-kanya-sumangala"].status == "eligible"
    assert "post-matric-sc" not in matches


def test_any_of_rule():
    assert results(UserProfile(age=72))["pmjay"] == "eligible"  # 70+ regardless of income
    assert results(UserProfile(age=40, bpl=True))["pmjay"] == "eligible"
    assert "pmjay" not in results(UserProfile(age=40, bpl=False))


def test_opt_in_facts_default_to_no():
    r = results(UserProfile(age=45, gender="female", bpl=True))
    assert "ignwps" not in r and "igndps" not in r
    r = results(UserProfile(age=45, gender="female", bpl=True, marital_status="widowed"))
    assert r["ignwps"] == "eligible"


def test_follow_up_questions_target_missing_facts():
    matches = match_schemes(UserProfile(occupation="farmer", land_acres=2), load_schemes())
    assert "age" in follow_up_fields(matches)
