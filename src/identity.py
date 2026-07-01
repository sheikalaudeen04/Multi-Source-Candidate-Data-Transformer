"""Candidate identity matching/grouping (pipeline stage 4).

Input unit is a "batch": the list of Assertions produced by one extractor
call for one person (one CSV row, one ATS record, one résumé file, ...).
Within a batch, all assertions are known to be about the same person, so
matching only has to happen *across* batches.

Cascading match strategy, most-confident match wins, first match found:
  1. exact email match (case-insensitive, trimmed)
  2. exact phone match (E.164)
  3. weak match: fuzzy name + at least one *additional* corroborating signal
     (same company, same education institution, or >= 2 shared skills).
     A name match alone is NEVER sufficient — two different real people can
     share a name, and merging them on that alone is a false-positive risk,
     not a "same person, conflicting name" case (which is handled
     separately, see the `conflicting_name` flag below).

No graph traversal: candidates is just a dict keyed by a deterministic
candidate_id, built incrementally as batches are folded in. Matching is
backed by reverse indexes (email/phone/name+company/name+institution ->
candidate_id) so each batch is matched in O(1) average time instead of
scanning every already-grouped candidate — at "thousands of candidates"
scale, an O(N) scan per batch becomes an accidentally-quadratic O(N^2)
pipeline, which is exactly the trap the assignment's scale constraint asks
to avoid. The skill-overlap corroboration check is the one exception: it
only scans candidates that already share the batch's name (via `by_name`),
which is a small set in practice, not the full candidate pool.
"""
import hashlib
import re

from .assertion import Assertion

MIN_SHARED_SKILLS_FOR_WEAK_MATCH = 2


def _norm_email(v: str) -> str:
    return v.strip().lower()


def _norm_name(v: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", v.strip().lower())


def _batch_signals(batch: list[Assertion]) -> dict:
    emails = {_norm_email(a.value) for a in batch if a.field == "emails[]" and a.value}
    phones = {a.value for a in batch if a.field == "phones[]" and a.value}
    names = {_norm_name(a.value) for a in batch if a.field == "full_name" and a.value}
    companies = {
        _norm_name(a.value.get("company"))
        for a in batch if a.field == "experience[]" and isinstance(a.value, dict) and a.value.get("company")
    }
    institutions = {
        _norm_name(a.value.get("institution"))
        for a in batch if a.field == "education[]" and isinstance(a.value, dict) and a.value.get("institution")
    }
    skills = {a.value.strip().lower() for a in batch if a.field == "skills[]" and a.value}
    return {
        "emails": emails, "phones": phones, "names": names,
        "companies": companies, "institutions": institutions, "skills": skills,
    }


def _candidate_id(signals: dict) -> str:
    seed = next(iter(signals["emails"]), None) or next(iter(signals["names"]), None) or "unknown"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _empty_bucket() -> dict:
    return {
        "assertions": [], "emails": set(), "phones": set(), "names": set(),
        "companies": set(), "institutions": set(), "skills": set(),
    }


class _Indexes:
    """Reverse lookups so a batch can find its candidate without scanning
    every existing candidate. The company/institution weak-match indexes are
    keyed by every (name, X) pair the candidate has accumulated, which
    preserves "any name overlap AND any X overlap" semantics even when a
    name and an X were contributed by two different batches. The skill path
    can't be indexed the same way (it's a set-intersection-size check, not
    an exact pair), so it scans only candidates sharing the batch's name."""

    def __init__(self):
        self.by_email: dict[str, str] = {}
        self.by_phone: dict[str, str] = {}
        self.by_name_company: dict[tuple[str, str], str] = {}
        self.by_name_institution: dict[tuple[str, str], str] = {}
        self.by_name: dict[str, set[str]] = {}

    def find(self, sig: dict, candidates: dict[str, dict]):
        for e in sig["emails"]:
            if e in self.by_email:
                return self.by_email[e], "email"
        for p in sig["phones"]:
            if p in self.by_phone:
                return self.by_phone[p], "phone"

        for n in sig["names"]:
            for c in sig["companies"]:
                if (n, c) in self.by_name_company:
                    return self.by_name_company[(n, c)], "weak_match"
            for i in sig["institutions"]:
                if (n, i) in self.by_name_institution:
                    return self.by_name_institution[(n, i)], "weak_match"

        if sig["skills"]:
            for n in sig["names"]:
                for cid in self.by_name.get(n, ()):
                    shared = sig["skills"] & candidates[cid]["skills"]
                    if len(shared) >= MIN_SHARED_SKILLS_FOR_WEAK_MATCH:
                        return cid, "weak_match"

        return None, None

    def register(self, candidate_id: str, bucket: dict):
        for e in bucket["emails"]:
            self.by_email[e] = candidate_id
        for p in bucket["phones"]:
            self.by_phone[p] = candidate_id
        for n in bucket["names"]:
            self.by_name.setdefault(n, set()).add(candidate_id)
            for c in bucket["companies"]:
                self.by_name_company[(n, c)] = candidate_id
            for i in bucket["institutions"]:
                self.by_name_institution[(n, i)] = candidate_id


def group_into_candidates(batches: list[list[Assertion]]) -> dict[str, list[Assertion]]:
    candidates: dict[str, dict] = {}
    indexes = _Indexes()

    for batch in batches:
        if not batch:
            continue
        sig = _batch_signals(batch)
        match_id, match_kind = indexes.find(sig, candidates)

        if match_id is None:
            match_id = _candidate_id(sig)
            while match_id in candidates:
                match_id += "0"
            candidates[match_id] = _empty_bucket()

        bucket = candidates[match_id]
        if match_kind == "weak_match":
            bucket["assertions"].append(Assertion("_flag", "weak_match (corroborated, no shared email/phone)", "identity", "weak_match"))
        if match_kind == "email" and sig["names"] and bucket["names"] and not (sig["names"] & bucket["names"]):
            bucket["assertions"].append(Assertion("_flag", "conflicting_name", "identity", "conflicting_name"))

        bucket["assertions"].extend(batch)
        bucket["emails"] |= sig["emails"]
        bucket["phones"] |= sig["phones"]
        bucket["names"] |= sig["names"]
        bucket["companies"] |= sig["companies"]
        bucket["institutions"] |= sig["institutions"]
        bucket["skills"] |= sig["skills"]
        indexes.register(match_id, bucket)

    return {cid: data["assertions"] for cid, data in candidates.items()}
