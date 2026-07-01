from src.projector import project, DEFAULT_CONFIG

RECORD = {
    "candidate_id": "abc123",
    "full_name": "Jane Doe",
    "emails": ["jane@example.com"],
    "phones": ["+14155550142"],
    "location": {"city": "SF", "region": "CA", "country": "US"},
    "links": {"linkedin": None, "github": None, "portfolio": []},
    "headline": "Engineer",
    "years_experience": None,
    "skills": [{"name": "Python", "confidence": 1.0, "sources": ["ats_json"]}],
    "experience": [],
    "education": [],
    "projects": [{"name": "PromptLedger", "summary": "An AI tool."}],
    "provenance": [],
    "overall_confidence": 0.8,
}


def test_default_config_round_trips_full_schema():
    out, errors = project(RECORD, DEFAULT_CONFIG)
    assert errors == []
    assert out["full_name"] == "Jane Doe"
    assert out["emails"] == ["jane@example.com"]
    assert "overall_confidence" in out
    assert "provenance" in out
    assert out["projects"] == [{"name": "PromptLedger", "summary": "An AI tool."}]


def test_custom_config_renames_and_subsets():
    config = {
        "fields": [
            {"path": "full_name", "type": "string", "required": True},
            {"path": "primary_email", "from": "emails[0]", "type": "string"},
        ],
        "include_confidence": False,
        "include_provenance": False,
        "on_missing": "null",
    }
    out, errors = project(RECORD, config)
    assert errors == []
    assert out == {"full_name": "Jane Doe", "primary_email": "jane@example.com"}


def test_on_missing_null():
    config = {"fields": [{"path": "phone", "from": "phones[5]", "type": "string"}],
              "include_confidence": False, "include_provenance": False, "on_missing": "null"}
    out, _ = project(RECORD, config)
    assert out["phone"] is None


def test_on_missing_omit():
    config = {"fields": [{"path": "phone", "from": "phones[5]", "type": "string"}],
              "include_confidence": False, "include_provenance": False, "on_missing": "omit"}
    out, _ = project(RECORD, config)
    assert "phone" not in out


def test_on_missing_error_for_required_field():
    config = {"fields": [{"path": "linkedin_url", "from": "links.linkedin", "type": "string", "required": True}],
              "include_confidence": False, "include_provenance": False, "on_missing": "error"}
    out, errors = project(RECORD, config)
    assert len(errors) == 1
    assert "linkedin_url" in errors[0]


def test_skills_path_map_and_normalize():
    config = {"fields": [{"path": "skill_names", "from": "skills[].name", "type": "string[]", "normalize": "canonical"}],
              "include_confidence": False, "include_provenance": False, "on_missing": "null"}
    out, _ = project(RECORD, config)
    assert out["skill_names"] == ["Python"]


def test_empty_list_fields_are_null_not_empty_array_top_level():
    # experience and education are both [] in RECORD (no contributing source)
    out, _ = project(RECORD, DEFAULT_CONFIG)
    assert out["experience"] is None
    assert out["education"] is None


def test_empty_list_fields_are_null_not_empty_array_nested():
    # links.portfolio is [] inside the "links" object — must follow the same
    # null-for-no-data rule as top-level list fields, not stay as [].
    out, _ = project(RECORD, DEFAULT_CONFIG)
    assert out["links"]["portfolio"] is None
    # sanity: a populated nested list is left alone
    record_with_portfolio = dict(RECORD, links={"linkedin": None, "github": None, "portfolio": ["https://jane.dev"]})
    out2, _ = project(record_with_portfolio, DEFAULT_CONFIG)
    assert out2["links"]["portfolio"] == ["https://jane.dev"]
