from src.assertion import Assertion
from src.identity import group_into_candidates


def test_groups_by_email():
    batch_a = [Assertion("full_name", "Jane Doe", "recruiter_csv", "direct_field"),
               Assertion("emails[]", "jane@example.com", "recruiter_csv", "direct_field")]
    batch_b = [Assertion("emails[]", "JANE@example.com", "ats_json", "direct_field"),
               Assertion("headline", "Engineer", "ats_json", "direct_field")]
    candidates = group_into_candidates([batch_a, batch_b])
    assert len(candidates) == 1


def test_phone_only_fallback_groups_together():
    batch_a = [Assertion("phones[]", "+14155550142", "recruiter_csv", "direct_field")]
    batch_b = [Assertion("phones[]", "+14155550142", "resume", "regex_extract")]
    candidates = group_into_candidates([batch_a, batch_b])
    assert len(candidates) == 1


def test_fuzzy_name_and_company_fallback():
    batch_a = [Assertion("full_name", "Jane Doe", "recruiter_csv", "direct_field"),
               Assertion("experience[]", {"company": "Google", "title": "Eng", "start": None, "end": None, "summary": None},
                         "recruiter_csv", "direct_field")]
    batch_b = [Assertion("full_name", "Jane Doe", "notes", "regex_extract"),
               Assertion("experience[]", {"company": "Google", "title": "SWE", "start": None, "end": None, "summary": None},
                         "notes", "regex_extract")]
    candidates = group_into_candidates([batch_a, batch_b])
    assert len(candidates) == 1
    flags = [a for a in next(iter(candidates.values())) if a.field == "_flag"]
    assert any(f.method == "weak_match" for f in flags)


def test_fuzzy_name_and_education_fallback():
    batch_a = [Assertion("full_name", "Jane Doe", "recruiter_csv", "direct_field"),
               Assertion("education[]", {"institution": "Stanford University", "degree": "B.S.", "field": "CS", "end_year": 2020},
                         "recruiter_csv", "direct_field")]
    batch_b = [Assertion("full_name", "Jane Doe", "resume", "regex_extract"),
               Assertion("education[]", {"institution": "Stanford University", "degree": None, "field": None, "end_year": None},
                         "resume", "regex_extract")]
    candidates = group_into_candidates([batch_a, batch_b])
    assert len(candidates) == 1
    flags = [a for a in next(iter(candidates.values())) if a.field == "_flag"]
    assert any(f.method == "weak_match" for f in flags)


def test_fuzzy_name_and_shared_skills_fallback():
    batch_a = [Assertion("full_name", "Jane Doe", "recruiter_csv", "direct_field"),
               Assertion("skills[]", "Python", "recruiter_csv", "direct_field"),
               Assertion("skills[]", "SQL", "recruiter_csv", "direct_field")]
    batch_b = [Assertion("full_name", "Jane Doe", "notes", "regex_extract"),
               Assertion("skills[]", "Python", "notes", "regex_extract"),
               Assertion("skills[]", "SQL", "notes", "regex_extract")]
    candidates = group_into_candidates([batch_a, batch_b])
    assert len(candidates) == 1
    flags = [a for a in next(iter(candidates.values())) if a.field == "_flag"]
    assert any(f.method == "weak_match" for f in flags)


def test_name_alone_is_never_sufficient_to_merge():
    # one shared skill is below the >=2 threshold, and there's no company/
    # institution overlap -- a name match alone (or name + 1 weak skill
    # overlap) must NOT merge two otherwise-unrelated batches.
    batch_a = [Assertion("full_name", "Jane Doe", "recruiter_csv", "direct_field"),
               Assertion("skills[]", "Python", "recruiter_csv", "direct_field")]
    batch_b = [Assertion("full_name", "Jane Doe", "notes", "regex_extract"),
               Assertion("skills[]", "Python", "notes", "regex_extract")]
    candidates = group_into_candidates([batch_a, batch_b])
    assert len(candidates) == 2


def test_two_different_people_same_name_different_companies_stay_separate():
    # The actual regression this guards against: two different real "John
    # Smith"s with no shared email/phone and no corroborating signal must
    # produce two separate profiles, not get merged on name alone.
    batch_a = [
        Assertion("full_name", "John Smith", "recruiter_csv", "direct_field"),
        Assertion("emails[]", "john.smith.acme@example.com", "recruiter_csv", "direct_field"),
        Assertion("experience[]", {"company": "Acme Corp", "title": "Engineer", "start": None, "end": None, "summary": None},
                  "recruiter_csv", "direct_field"),
    ]
    batch_b = [
        Assertion("full_name", "John Smith", "ats_json", "direct_field"),
        Assertion("emails[]", "john.smith.globex@example.com", "ats_json", "direct_field"),
        Assertion("experience[]", {"company": "Globex Inc", "title": "Manager", "start": None, "end": None, "summary": None},
                  "ats_json", "direct_field"),
    ]
    candidates = group_into_candidates([batch_a, batch_b])
    assert len(candidates) == 2
    for assertions in candidates.values():
        assert not any(a.field == "_flag" for a in assertions)


def test_unrelated_candidates_stay_separate():
    batch_a = [Assertion("emails[]", "a@example.com", "recruiter_csv", "direct_field")]
    batch_b = [Assertion("emails[]", "b@example.com", "recruiter_csv", "direct_field")]
    candidates = group_into_candidates([batch_a, batch_b])
    assert len(candidates) == 2


def test_conflicting_name_same_email_flagged():
    batch_a = [Assertion("full_name", "Jane Doe", "recruiter_csv", "direct_field"),
               Assertion("emails[]", "shared@example.com", "recruiter_csv", "direct_field")]
    batch_b = [Assertion("full_name", "J. D. Smith", "ats_json", "direct_field"),
               Assertion("emails[]", "shared@example.com", "ats_json", "direct_field")]
    candidates = group_into_candidates([batch_a, batch_b])
    assert len(candidates) == 1
    flags = [a for a in next(iter(candidates.values())) if a.field == "_flag"]
    assert any(f.method == "conflicting_name" for f in flags)
