from app.extract import extract_profile, normalise_state
from app.lang import detect_language


def test_english_example_from_the_brief():
    p = extract_profile("I'm a farmer in UP with 2 acres and a daughter in Class 10")
    assert (p.occupation, p.state, p.land_acres, p.owns_land) == ("farmer", "Uttar Pradesh", 2.0, True)
    assert p.age is None  # the daughter's class must not be read as the farmer's age
    assert [(c.gender, c.age, c.education) for c in p.children] == [("female", 15, "class_9_10")]


def test_hindi_message():
    p = extract_profile("मैं बिहार की विधवा हूँ, उम्र 52 साल, मेरे पास राशन कार्ड है और गाँव में रहती हूँ")
    assert (p.state, p.age, p.gender, p.marital_status) == ("Bihar", 52, "female", "widowed")
    assert p.bpl is True and p.residence == "rural"


def test_hinglish_monthly_income_is_annualised():
    p = extract_profile("Main Maharashtra mein thela lagata hoon, umar 34 saal, mahine ki kamai 9000")
    assert (p.occupation, p.age, p.annual_income, p.gender) == ("street_vendor", 34, 108000, "male")


def test_numbers_with_decimals_commas_and_devanagari_digits():
    assert extract_profile("My family income is 1.5 lakh per year").annual_income == 150000
    assert extract_profile("family income 80,000 per year").annual_income == 80000
    assert extract_profile("मेरी उम्र ४५ साल है").age == 45
    assert extract_profile("I have 2 hectares of land").land_acres == 4.94


def test_negation_stays_inside_its_clause():
    assert extract_profile("I have a BPL card and no pucca house").bpl is True
    assert extract_profile("I do not have a ration card").bpl is False
    assert extract_profile("मेरे पास राशन कार्ड नहीं है").bpl is False


def test_state_abbreviations_are_not_guessed_from_ordinary_words():
    assert normalise_state("I earn up to 2 lakh") is None
    assert normalise_state("I live in MP") == "Madhya Pradesh"
    assert normalise_state("uttar pradesh") == "Uttar Pradesh"


def test_language_detection():
    assert detect_language("I am a farmer") == "en"
    assert detect_language("मैं किसान हूँ") == "hi"
    assert detect_language("Main kisan hoon aur mera gaon Bihar mein hai") == "hi"
    assert detect_language("मी शेतकरी आहे") == "mr"
    assert detect_language("আমি একজন কৃষক") == "bn"
    assert detect_language("நான் ஒரு விவசாயி") == "ta"
    assert detect_language("నేను రైతును") == "te"


def test_degree_names_are_not_read_as_caste():
    p = extract_profile("I am doing B.Sc in Bihar, income 2 lakh")
    assert p.caste is None and p.education == "undergraduate"
    assert extract_profile("I am SC and study in class 11").caste == "sc"


def test_a_girl_describing_herself_is_not_her_own_child():
    p = extract_profile("main ek ladki hoon, class 11 mein padhti hoon, UP se")
    assert p.children == [] and p.gender == "female" and p.education == "class_11_12"
    assert len(extract_profile("meri ladki class 6 mein hai").children) == 1


def test_no_children_and_several_children():
    assert extract_profile("I have no children. I am a 40 year old farmer").children == []
    p = extract_profile("my 2 daughters are in class 9 and 11")
    assert [(c.gender, c.age, c.education) for c in p.children] == [
        ("female", 14, "class_9_10"), ("female", 16, "class_11_12")]
    assert p.age is None


def test_a_duration_is_not_an_age():
    assert extract_profile("मैं 10 साल से खेती कर रहा हूँ, बिहार में").age is None
    assert extract_profile("I have been farming for 10 years").age is None
    assert extract_profile("I am 10th pass and unemployed, 22 years old").age == 22
