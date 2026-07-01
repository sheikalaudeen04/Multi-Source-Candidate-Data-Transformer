import json
from pathlib import Path

from cli import collect_batches, run_pipeline
from src.projector import DEFAULT_CONFIG
from src.validator import derive_schema, validate_projected

SAMPLE_DIR = Path(__file__).parent.parent / "sample_inputs"


class Args:
    csv = str(SAMPLE_DIR / "recruiter.csv")
    ats_json = str(SAMPLE_DIR / "ats.json")
    resume = str(SAMPLE_DIR / "resume.docx")
    notes = str(SAMPLE_DIR / "notes.txt")


def test_pipeline_default_config_schema_valid():
    batches = collect_batches(Args())
    results, ledger, candidate_ids, _warnings = run_pipeline(batches, DEFAULT_CONFIG, verbose=False)
    assert len(results) >= 1
    assert len(candidate_ids) == len(results)

    schema = derive_schema(DEFAULT_CONFIG)
    for profile in results:
        assert validate_projected(profile, schema) == []

    jane = next(p for p in results if p["full_name"] == "Jane Doe")
    assert jane["emails"] == ["jane.doe@example.com"]
    assert jane["experience"][0]["company"] == "Google"
    # the résumé's richer experience entry should win over the sparse ATS one
    assert jane["experience"][0]["title"] == "Senior Software Engineer"
    # the ledger entries for Jane's candidate_id must be resolvable even
    # though "experience[]" went through conflict resolution
    jane_id = candidate_ids[results.index(jane)]
    assert any(e.candidate_id == jane_id for e in ledger)


def test_pipeline_custom_config_schema_valid():
    config = json.loads((SAMPLE_DIR.parent / "config" / "example_config.json").read_text())
    batches = collect_batches(Args())
    results, ledger, candidate_ids, _warnings = run_pipeline(batches, config, verbose=False)
    schema = derive_schema(config)
    for profile in results:
        assert validate_projected(profile, schema) == []
        assert "primary_email" in profile
        # the custom config doesn't select candidate_id for the output --
        # confirm it's still recoverable via the parallel candidate_ids list
        assert "candidate_id" not in profile
    assert len(candidate_ids) == len(results)
    assert all(isinstance(cid, str) and cid for cid in candidate_ids)
    # the ledger itself is keyed by internal candidate_id regardless of what
    # the custom config chose to project -- recoverable here even though no
    # result dict carries "candidate_id"
    assert any(e.candidate_id in candidate_ids for e in ledger)


def test_missing_csv_source_does_not_crash():
    class PartialArgs(Args):
        csv = "sample_inputs/does_not_exist.csv"

    batches = collect_batches(PartialArgs())
    results, _ledger, _candidate_ids, _warnings = run_pipeline(batches, DEFAULT_CONFIG, verbose=False)
    assert isinstance(results, list)
