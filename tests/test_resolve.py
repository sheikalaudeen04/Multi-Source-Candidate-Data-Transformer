from src.assertion import Assertion
from src.resolve import resolve_candidate
from src.confidence import compute_confidence, WEAK_MATCH_CONFIDENCE_CAP


def _exp(company, title, richness, source):
    return Assertion(
        "experience[]",
        {"company": company, "title": title, "start": None, "end": None, "summary": None},
        source, "direct_field", structural_richness=richness,
    )


def test_density_win_richer_resume_beats_sparse_ats():
    assertions = [
        _exp("Google", None, 0.2, "ats_json"),
        Assertion(
            "experience[]",
            {"company": "Google", "title": "Senior Software Engineer", "start": "2021-01", "end": "2024-01", "summary": "led stuff"},
            "resume", "regex_extract", structural_richness=1.0,
        ),
    ]
    profile, ledger, _ = resolve_candidate("c1", assertions)
    assert profile.experience[0].title == "Senior Software Engineer"
    assert profile.experience[0].start == "2021-01"
    # experience group merges must emit a ledger entry too, not just scalar fields
    entry = next(e for e in ledger if e.field == "experience[]")
    assert entry.reason == "density_win"
    methods = {p.method for p in profile.provenance if p.field == "experience[]"}
    assert methods == {"density_win", "superseded"}


def test_density_win_with_more_than_two_competing_values():
    # four sources disagree; only the résumé (richness 1.0) is genuinely
    # competitive. A much sparser assertion must never win on rank alone
    # just because it happens to have the lowest source_rank globally.
    assertions = [
        _exp("Google", "Eng I", 0.2, "ats_json"),       # rank 1, but far sparser
        _exp("Google", "Eng II", 0.4, "recruiter_csv"),  # rank 2
        _exp("Google", "Eng III", 0.6, "notes"),          # rank 4
        Assertion(
            "experience[]",
            {"company": "Google", "title": "Senior Software Engineer", "start": "2021-01", "end": "2024-01", "summary": "led stuff"},
            "resume", "regex_extract", structural_richness=1.0,
        ),
    ]
    profile, ledger, _ = resolve_candidate("c1", assertions)
    assert profile.experience[0].title == "Senior Software Engineer"
    entry = next(e for e in ledger if e.field == "experience[]")
    assert entry.reason == "density_win"
    assert entry.winner_source == "resume"


def test_richness_tied_falls_back_to_source_rank():
    assertions = [
        Assertion("headline", "Backend Engineer", "ats_json", "direct_field", structural_richness=0.5),
        Assertion("headline", "Software Developer", "notes", "regex_extract", structural_richness=0.5),
    ]
    profile, ledger, _ = resolve_candidate("c1", assertions)
    assert profile.headline == "Backend Engineer"  # ats_json has lower (better) source_rank
    entry = next(e for e in ledger if e.field == "headline")
    assert entry.reason == "rank_resolved"


def test_richness_and_rank_tied_unresolved_conflict():
    # two unranked sources (default rank 99) tie on both richness and rank
    assertions = [
        Assertion("headline", "Backend Engineer", "source_x", "custom", structural_richness=0.5),
        Assertion("headline", "Backend Lead", "source_y", "custom", structural_richness=0.5),
    ]
    profile, ledger, field_info = resolve_candidate("c1", assertions)
    entry = next(e for e in ledger if e.field == "headline")
    assert entry.reason == "unresolved_conflict"
    assert field_info["headline"]["unresolved"] is True
    methods = [p.method for p in profile.provenance if p.field == "headline"]
    assert "unresolved_conflict" in methods


def test_list_field_union_dedupe_emails():
    assertions = [
        Assertion("emails[]", "jane@example.com", "recruiter_csv", "direct_field"),
        Assertion("emails[]", "JANE@example.com", "ats_json", "direct_field"),
        Assertion("emails[]", "jane.alt@example.com", "resume", "regex_extract"),
    ]
    profile, _, _ = resolve_candidate("c1", assertions)
    assert len(profile.emails) == 2


def test_skills_union_dedupe_with_confidence():
    assertions = [
        Assertion("skills[]", "Python", "ats_json", "direct_field"),
        Assertion("skills[]", "Python", "resume", "regex_extract"),
        Assertion("skills[]", "SQL", "ats_json", "direct_field"),
    ]
    profile, _, _ = resolve_candidate("c1", assertions)
    by_name = {s.name: s for s in profile.skills}
    assert by_name["Python"].confidence == 1.0
    assert by_name["SQL"].confidence == 0.5


def test_provenance_dedupes_per_source_not_per_value():
    # one source (resume) contributes 4 skills -> provenance should only
    # state "resume contributed to skills[]" once, not 4 times.
    assertions = [
        Assertion("skills[]", "Python", "resume", "regex_extract"),
        Assertion("skills[]", "React", "resume", "regex_extract"),
        Assertion("skills[]", "AWS", "resume", "regex_extract"),
        Assertion("skills[]", "Docker", "resume", "regex_extract"),
        Assertion("skills[]", "SQL", "ats_json", "direct_field"),
    ]
    profile, _, _ = resolve_candidate("c1", assertions)
    resume_skill_entries = [p for p in profile.provenance if p.field == "skills[]" and p.source == "resume"]
    assert len(resume_skill_entries) == 1
    ats_skill_entries = [p for p in profile.provenance if p.field == "skills[]" and p.source == "ats_json"]
    assert len(ats_skill_entries) == 1


def test_skill_confidence_invariant_to_number_of_values_per_source():
    # control: each source contributes exactly 1 skill
    control = [
        Assertion("skills[]", "Python", "ats_json", "direct_field"),
        Assertion("skills[]", "SQL", "resume", "regex_extract"),
    ]
    # variant: resume contributes 3 extra unrelated skills too
    variant = control + [
        Assertion("skills[]", "React", "resume", "regex_extract"),
        Assertion("skills[]", "AWS", "resume", "regex_extract"),
        Assertion("skills[]", "Docker", "resume", "regex_extract"),
    ]
    control_profile, _, _ = resolve_candidate("c1", control)
    variant_profile, _, _ = resolve_candidate("c2", variant)

    control_python = next(s for s in control_profile.skills if s.name == "Python")
    variant_python = next(s for s in variant_profile.skills if s.name == "Python")
    # Python's confidence (1 of 2 sources) must be unaffected by resume
    # also emitting 3 other unrelated skills.
    assert control_python.confidence == variant_python.confidence == 0.5


def test_projects_independent_of_experience():
    # a project-based résumé with zero work experience must leave
    # experience[] empty while still populating projects[].
    assertions = [
        Assertion("projects[]", {"name": "PromptLedger", "summary": "An AI tool."}, "resume", "regex_extract", structural_richness=1.0),
    ]
    profile, _, _ = resolve_candidate("c1", assertions)
    assert profile.experience == []
    assert len(profile.projects) == 1
    assert profile.projects[0].name == "PromptLedger"


def test_projects_dedupe_by_name_prefers_richer_summary():
    assertions = [
        Assertion("projects[]", {"name": "PromptLedger", "summary": None}, "ats_json", "direct_field", structural_richness=0.5),
        Assertion("projects[]", {"name": "promptledger", "summary": "An AI tool."}, "resume", "regex_extract", structural_richness=1.0),
    ]
    profile, _, _ = resolve_candidate("c1", assertions)
    assert len(profile.projects) == 1
    assert profile.projects[0].summary == "An AI tool."


def test_overall_confidence_capped_for_weak_identity_match():
    # mirrors what identity.py inserts when a candidate is grouped via the
    # weak (fuzzy name + corroboration, no shared email/phone) match path --
    # overall_confidence must never exceed the cap regardless of how strong
    # the individual fields otherwise look.
    assertions = [
        Assertion("_flag", "weak_match (corroborated, no shared email/phone)", "identity", "weak_match"),
        Assertion("full_name", "Jane Doe", "recruiter_csv", "direct_field"),
        Assertion("emails[]", "jane@example.com", "recruiter_csv", "direct_field"),
        Assertion("phones[]", "+14155550142", "recruiter_csv", "direct_field"),
    ]
    profile, _, field_info = resolve_candidate("c1", assertions)
    overall = compute_confidence(profile, field_info)
    assert overall <= WEAK_MATCH_CONFIDENCE_CAP


def test_overall_confidence_not_capped_for_strong_identity_match():
    assertions = [
        Assertion("full_name", "Jane Doe", "recruiter_csv", "direct_field"),
        Assertion("emails[]", "jane@example.com", "recruiter_csv", "direct_field"),
        Assertion("phones[]", "+14155550142", "recruiter_csv", "direct_field"),
    ]
    profile, _, field_info = resolve_candidate("c1", assertions)
    overall = compute_confidence(profile, field_info)
    assert overall > WEAK_MATCH_CONFIDENCE_CAP
