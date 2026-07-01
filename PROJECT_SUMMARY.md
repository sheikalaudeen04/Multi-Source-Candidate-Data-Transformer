# Multi-Source Candidate Data Transformer — One-Page Summary

## Problem
Candidate data arrives from structured sources (recruiter CSV, ATS JSON) and unstructured
sources (GitHub, résumé, recruiter notes), often missing, malformed, or conflicting.
The goal: merge it into one canonical, provenance-tracked, confidence-scored profile per
candidate, reshaped at runtime via config — no code changes per config.

## Pipeline
```
DETECT → EXTRACT → NORMALIZE → GROUP (identity) → RESOLVE → CONFIDENCE → PROJECT → VALIDATE
```
Every value pulled from any source is first recorded as an immutable **Assertion**
(`field`, `value`, `source`, `method`, `source_rank`, `structural_richness`) — extractors
never merge, they only produce assertions. This makes provenance structural rather than
bolted on, and conflict resolution one generic algorithm instead of six special cases.

## Canonical schema & normalization
Fixed internal schema (`candidate_id`, `full_name`, `emails[]`, `phones[]`, `location`,
`links`, `headline`, `years_experience`, `skills[]`, `experience[]`, `education[]`,
`projects[]`, `provenance[]`, `overall_confidence`). Normalized formats: phones → E.164
(`phonenumbers`, default region US), dates → `YYYY-MM`, country → ISO 3166 alpha-2, skills →
canonical name via a synonym dict. `projects[]` is a deliberate, documented extension beyond
the assignment's literal default schema, kept independent of `experience[]` since a project
isn't a claim of employment.

## Identity matching
Assertions are grouped per candidate by a cascading key: exact email match → exact phone
match → fuzzy name + at least one corroborating signal (company, education institution, or
2+ shared skills) — a name match alone never merges two batches, since two different real
people can share a name. Any such weak match is flagged in provenance and caps
`overall_confidence` at 0.6. Backed by reverse indexes for O(1) average matching, not a
linear scan — needed to stay reasonable at thousands of candidates.

## Merge / conflict-resolution policy
Richness-weighted, not purely rank-based. For each field: one assertion wins trivially;
multiple agreeing assertions merge with a confidence boost; on disagreement, compare
**structural richness** (0–1, how much corroborating sub-structure a value carries — e.g.
a full `title+company+dates+summary` experience entry scores 1.0 vs. a bare company name at
0.2). If one value is clearly richer (margin ≥ 0.2) it wins (`density_win`) regardless of
source. Only when richness is roughly tied does source reliability rank act as the
tiebreaker (`rank_resolved`: ATS JSON > recruiter CSV > résumé > GitHub > notes).
If richness *and* rank both tie, it's an `unresolved_conflict` — the rank-1 value is kept,
confidence is capped at 0.5, and both competing values stay in provenance; nothing is
silently dropped. List fields (emails, phones, skills, portfolio links) use union + dedupe
instead, since multiple valid values can legitimately coexist.

## Confidence
Per-field: `0.4 + 0.2×(agreeing sources) + 0.15×(winning richness)`, minus 0.15 if
normalization failed, capped at 0.5 if unresolved. `overall_confidence` is a weighted
average across populated fields (name/contact weighted highest), with a 30% penalty each if
`full_name` or any contact method is missing. Deliberately a transparent heuristic, not ML.

## Runtime config (the required twist)
A config JSON selects a field subset, renames/remaps via a `from` path (a small dot/bracket
resolver supporting `a.b`, `a[0]`, `a[].b`), re-applies normalization, toggles
provenance/confidence, and controls `on_missing` (`null`/`omit`/`error`). No config supplied
→ a built-in default config covering the full schema — proving both paths share one
projection function. Output is then validated against a JSON Schema derived dynamically from
the same active config (`jsonschema` library), never inventing values to satisfy it.

## Edge cases handled
1. Missing/garbage source file → extractor returns `[]`, run continues.
2. Same person, conflicting names sharing an email → grouped via email, conflict flagged,
   confidence lowered.
3. Phone with no country code → default-region assumption, flagged rather than guessed
   silently.
4. Skill synonyms/casing (`js`/`React.js`) → canonicalization dict, unknown skills
   Title-Cased.
5. Richness tie with no clear winner → falls through to rank, then to `unresolved_conflict`.
6. Two different people sharing a name, no corroborating signal → stay as two separate
   profiles; a name match alone never merges.

**Explicitly descoped / removed**: OCR for scanned PDFs, ML-based entity resolution,
full-text fuzzy dedup beyond company+date-range overlap, and LinkedIn — actively removed
(not merely unbuilt), since real access requires paid/licensed API and scraping is
ToS-prohibited.

## Scale
Shared CSV/JSON files are read once and split into per-candidate assertion batches, not
re-opened per candidate. Identity matching is indexed (O(1) avg), not a linear scan —
verified empirically: 10,000 candidates resolve in ~2.7s. No database or distributed
processing was built; deliberate scope decision for an assignment-scale demo, not an
oversight.
