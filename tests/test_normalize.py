from src.normalize import normalize_phone, normalize_date, normalize_skill, structural_richness


def test_phone_with_country_code():
    value, failed = normalize_phone("+1 415-555-0142")
    assert value == "+14155550142"
    assert failed is False


def test_phone_without_country_code_defaults_us():
    value, failed = normalize_phone("415-555-0142")
    assert value == "+14155550142"
    assert failed is False


def test_phone_malformed_keeps_raw_and_flags():
    value, failed = normalize_phone("not-a-phone")
    assert failed is True
    assert value == "not-a-phone"


def test_date_variants():
    assert normalize_date("2022-01") == ("2022-01", False)
    assert normalize_date("01/2022") == ("2022-01", False)
    assert normalize_date("Jan 2022") == ("2022-01", False)
    value, inferred = normalize_date("2022")
    assert value == "2022-01"
    assert inferred is True


def test_skill_synonyms():
    assert normalize_skill("js") == "JavaScript"
    assert normalize_skill("ReactJS".lower()) == normalize_skill("react")
    assert normalize_skill("py") == "Python"


def test_skill_unknown_title_cased():
    assert normalize_skill("rust") == "Rust"


def test_structural_richness_experience():
    sparse = {"company": "Google", "title": None, "start": None, "end": None, "summary": None}
    rich = {"company": "Google", "title": "SWE", "start": "2021-01", "end": "2024-01", "summary": "did stuff"}
    assert structural_richness("experience[]", sparse) == 0.2
    assert structural_richness("experience[]", rich) == 1.0
