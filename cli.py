#!/usr/bin/env python3
"""Entry point: detect -> extract -> normalize -> group -> resolve ->
confidence -> project -> validate -> output JSON.

See README.md for usage examples.
"""
import argparse
import json
import sys
from pathlib import Path

from src.extractors import (
    csv_extractor, ats_json_extractor, resume_extractor, notes_extractor,
)
from src.normalize import normalize_assertions
from src.identity import group_into_candidates
from src.resolve import resolve_candidate
from src.confidence import compute_confidence
from src.projector import project, DEFAULT_CONFIG
from src.validator import derive_schema, validate_projected


def collect_batches(args) -> list[list]:
    """Gathers raw (un-normalized) Assertion batches from every source flag given."""
    batches: list[list] = []

    if args.csv:
        batches.extend(csv_extractor.extract(args.csv))
    if args.ats_json:
        batches.extend(ats_json_extractor.extract(args.ats_json))
    if args.resume:
        a = resume_extractor.extract(args.resume)
        if a:
            batches.append(a)
    if args.notes:
        a = notes_extractor.extract(args.notes)
        if a:
            batches.append(a)

    return batches


def discover_batch_dir(batch_dir: str) -> list[list]:
    """Walks a per-candidate directory layout (see brief section 12a) and
    extracts one combined batch per candidate from their own files."""
    root = Path(batch_dir)
    if not root.exists():
        return []

    flattened = []
    for candidate_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        combined = []
        for name, extractor in (
            ("recruiter.csv", csv_extractor),
            ("ats.json", ats_json_extractor),
            ("resume.pdf", resume_extractor),
            ("resume.docx", resume_extractor),
            ("notes.txt", notes_extractor),
        ):
            fpath = candidate_dir / name
            if not fpath.exists():
                continue
            result = extractor.extract(str(fpath))
            if extractor in (csv_extractor, ats_json_extractor):
                for batch in result:
                    combined.extend(batch)
            elif result:
                combined.extend(result)
        if combined:
            flattened.append(combined)
    return flattened


def run_pipeline(raw_batches: list[list], config: dict, verbose: bool):
    """Returns (results, ledger, result_candidate_ids, warnings).

    `results` is exactly what gets serialized to JSON -- shaped however the
    active config says, nothing extra leaked in. `result_candidate_ids[i]`
    is the *internal* candidate_id for `results[i]`, kept as a separate
    parallel list rather than injected into the dict, since a custom config
    that doesn't select "candidate_id" must not have it appear in the
    output. This lets callers (e.g. the UI) always associate ledger entries
    with the right profile, even when the projected output itself can't
    carry that field -- the ledger is diagnostic/internal data and must
    never depend on what fields a custom config chose to keep.
    """
    normalized_batches = [normalize_assertions(b) for b in raw_batches if b]
    candidates = group_into_candidates(normalized_batches)

    profiles, all_ledger = [], []
    for candidate_id, assertions in candidates.items():
        profile, ledger, field_info = resolve_candidate(candidate_id, assertions)
        profile.overall_confidence = compute_confidence(profile, field_info)
        profiles.append(profile)
        all_ledger.extend(ledger)

    schema = derive_schema(config)
    results, result_candidate_ids, warnings = [], [], []
    for profile in profiles:
        projected, errors = project(profile.to_dict(), config)
        if errors:
            for e in errors:
                warnings.append(f"ERROR: {e}")
            continue
        msgs = validate_projected(projected, schema)
        warnings.extend(msgs)
        results.append(projected)
        result_candidate_ids.append(profile.candidate_id)

    if verbose:
        for entry in all_ledger:
            print(entry.format(), file=sys.stderr)
        for w in warnings:
            print(f"[WARN] {w}", file=sys.stderr)

    return results, all_ledger, result_candidate_ids, warnings


def main():
    parser = argparse.ArgumentParser(description="Multi-Source Candidate Data Transformer")
    parser.add_argument("--csv", help="Recruiter CSV export path")
    parser.add_argument("--ats-json", help="ATS JSON export path")
    parser.add_argument("--resume", help="Resume PDF/DOCX path")
    parser.add_argument("--notes", help="Recruiter notes .txt path")
    parser.add_argument("--batch-dir", help="Directory of per-candidate subfolders (see README)")
    parser.add_argument("--config", help="Path to runtime projection config JSON")
    parser.add_argument("--out", default="output/profiles.json", help="Output JSON path")
    parser.add_argument("--verbose", action="store_true", help="Print the conflict resolution ledger")
    args = parser.parse_args()

    config = DEFAULT_CONFIG
    if args.config:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))

    if args.batch_dir:
        raw_batches = discover_batch_dir(args.batch_dir)
    else:
        raw_batches = collect_batches(args)

    if not raw_batches:
        print("No usable input sources found (all missing or unparseable).", file=sys.stderr)

    results, _ledger, _candidate_ids, _warnings = run_pipeline(raw_batches, config, args.verbose)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
