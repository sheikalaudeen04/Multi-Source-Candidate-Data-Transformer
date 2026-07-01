# Demo video talking points (~2 min)

1. **Run default config** on the sample inputs (CSV + ATS JSON + résumé +
   notes) — show the merged JSON profile for Jane Doe: one record, multiple
   emails/phones unioned, one resolved experience entry.

2. **Run with `--config config/example_config.json`** — same engine, same
   inputs, reshaped output: renamed `primary_email`, E.164 phone, canonical
   skill names, provenance stripped. Point out this is the same `project()`
   code path as the default — no special-casing.

3. **Design decision to narrate:** richness-weighted conflict resolution.
   Run with `--verbose` and point at the `experience` field: ATS says
   `"Google"` alone, the résumé says `"Senior Software Engineer - Google
   (Jan 2021 - Dec 2024)"` with a summary. The résumé wins because it's
   structurally richer (richness 1.0 vs 0.2), not because of a hardcoded
   source preference — source rank is only the fallback when richness ties.

4. **Edge case to narrate:** identity matching never merges on a name match
   alone — two different "John Smith"s with no shared email/phone and no
   corroborating signal (company/education/shared skills) stay as two
   separate profiles. When a weak match *does* happen (name + a
   corroborating signal, no shared email/phone), it's flagged `weak_match`
   in provenance and overall_confidence is capped at 0.6.

5. Close on `pytest tests/` passing, and the `--batch-dir` flag reusing the
   identical pipeline for multi-candidate runs.
