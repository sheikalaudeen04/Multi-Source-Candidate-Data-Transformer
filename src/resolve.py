"""Conflict resolution across assertions for a field (pipeline stage 5).

Richness-weighted resolution: source reliability rank is the tie-breaker,
not the primary rule. See IMPLEMENTATION_BRIEF.md section 6 for the full
policy this implements.
"""
from dataclasses import dataclass
from typing import Optional

from .assertion import Assertion
from .schema import CandidateProfile, Location, Links, Skill, Experience, Education, Project, ProvenanceEntry

RICHNESS_MARGIN = 0.2

SCALAR_FIELDS = ["full_name", "headline", "years_experience"]
DICT_SCALAR_FIELDS = ["location"]
SIMPLE_LIST_FIELDS = {"emails[]": "emails", "phones[]": "phones"}
LINK_FIELDS = {"links.linkedin": "linkedin", "links.github": "github"}

# List-type fields where a single source can legitimately contribute many
# individual values (e.g. 4 skills, 2 experience entries). Provenance only
# needs to state once that a source contributed to the field, not once per
# value — see _dedupe_list_field_provenance.
LIST_TYPE_PROVENANCE_FIELDS = {
    "emails[]", "phones[]", "skills[]", "experience[]", "education[]", "projects[]", "links.portfolio[]",
}


@dataclass
class ResolutionLogEntry:
    candidate_id: str
    field: str
    winner_value: object
    winner_source: str
    winner_richness: float
    loser_value: object
    loser_source: Optional[str]
    loser_richness: Optional[float]
    reason: str
    margin: Optional[float] = None

    def format(self) -> str:
        loser = (f'loser="{self.loser_value}" (source={self.loser_source}, '
                  f'richness={self.loser_richness:.2f})') if self.loser_source else 'loser="-"'
        margin = f" (margin={self.margin:.2f} >= {RICHNESS_MARGIN})" if self.margin is not None else ""
        return (f"[RESOLVED] candidate={self.candidate_id} field={self.field}\n"
                f'  winner="{self.winner_value}" (source={self.winner_source}, richness={self.winner_richness:.2f})\n'
                f"  {loser}\n"
                f"  reason={self.reason}{margin}")


def _values_equal(a, b) -> bool:
    norm = lambda v: v.strip().lower() if isinstance(v, str) else v
    if isinstance(a, dict) and isinstance(b, dict):
        keys = set(a) | set(b)
        return all(norm(a.get(k)) == norm(b.get(k)) for k in keys)
    return norm(a) == norm(b)


def _resolve_assertion_group(candidate_id: str, field: str, assertions: list[Assertion]):
    """Implements the per-field algorithm from brief section 6 for one set of
    competing assertions about a single logical slot — either a scalar field
    value, or one experience/education group sharing the same identity key.

    Every provenance method this produces describes the *resolution outcome*,
    never the raw extraction method (direct_field/regex_extract/api_fetch are
    extractor-internal and never surface here): "direct_field" here means
    "only one source had data, no conflict to resolve" — not "extracted via
    a direct field lookup".

    Returns (winning_assertion, methods: dict[id(a), str], confidence_info, ledger_entry).
    """
    if not assertions:
        return None, {}, {"num_agreeing": 0, "richness": 0.0, "unresolved": False}, None

    if len(assertions) == 1:
        a = assertions[0]
        info = {"num_agreeing": 1, "richness": a.structural_richness, "unresolved": False,
                "normalize_failed": a.raw_context == "normalize_failed"}
        return a, {id(a): "direct_field"}, info, None

    # group by normalized value to find agreement
    groups: list[list[Assertion]] = []
    for a in assertions:
        placed = False
        for g in groups:
            if _values_equal(a.value, g[0].value):
                g.append(a)
                placed = True
                break
        if not placed:
            groups.append([a])

    if len(groups) == 1:
        winners = groups[0]
        best = max(winners, key=lambda a: a.structural_richness)
        methods = {id(a): "agreement_resolved" for a in winners}
        info = {"num_agreeing": len(winners), "richness": best.structural_richness, "unresolved": False,
                "normalize_failed": any(a.raw_context == "normalize_failed" for a in winners)}
        return best, methods, info, None

    # disagreement: pick representative (richest) per group, then compare groups
    reps = sorted(
        (max(g, key=lambda a: a.structural_richness) for g in groups),
        key=lambda a: a.structural_richness, reverse=True,
    )
    top = reps[0]
    unresolved = False

    # Reps within RICHNESS_MARGIN of the top are "tied" with it (top is always
    # included, diff 0). A small epsilon absorbs float error so a true 0.2
    # margin (e.g. 1.0 - 0.8) isn't miscategorized as tied. Rank fallback only
    # considers this tied set — a far sparser assertion must never win on rank
    # alone just because no source happens to rank lower (richness-weighted,
    # not just rank-based).
    tied_with_top = [a for a in reps if (top.structural_richness - a.structural_richness) < RICHNESS_MARGIN - 1e-9]

    if len(tied_with_top) == 1:
        winner, loser = top, reps[1]
        reason, margin = "density_win", top.structural_richness - loser.structural_richness
    else:
        rank_sorted = sorted(tied_with_top, key=lambda a: a.source_rank)
        winner, loser, margin = rank_sorted[0], rank_sorted[1], None
        if rank_sorted[0].source_rank != rank_sorted[1].source_rank:
            reason = "rank_resolved"
        else:
            reason = "unresolved_conflict"
            unresolved = True

    ledger = ResolutionLogEntry(
        candidate_id, field, winner.value, winner.source, winner.structural_richness,
        loser.value, loser.source, loser.structural_richness, reason, margin=margin,
    )

    group_size_by_id = {id(a): len(g) for g in groups for a in g}
    methods = {}
    for g in groups:
        for a in g:
            if unresolved:
                methods[id(a)] = "unresolved_conflict" if (a is winner or a is loser) else "superseded"
            else:
                methods[id(a)] = reason if a is winner else "superseded"

    info = {"num_agreeing": group_size_by_id[id(winner)], "richness": winner.structural_richness,
            "unresolved": unresolved, "normalize_failed": winner.raw_context == "normalize_failed"}
    return winner, methods, info, ledger


def _resolve_single_field(candidate_id: str, field: str, assertions: list[Assertion]):
    """Scalar-field wrapper around _resolve_assertion_group. Returns
    (winning_value, confidence_info, provenance_entries, ledger_entry)."""
    winner, methods, info, ledger = _resolve_assertion_group(candidate_id, field, assertions)
    if winner is None:
        return None, info, [], None
    provenance = [ProvenanceEntry(field, a.source, methods[id(a)]) for a in assertions]
    return winner.value, info, provenance, ledger


def _resolve_list_field(field_key: str, assertions: list[Assertion]):
    """Union + dedupe (case-insensitive) for emails/phones/portfolio links."""
    seen: dict[str, list[str]] = {}
    order = []
    for a in assertions:
        if not a.value:
            continue
        key = a.value.strip().lower() if isinstance(a.value, str) else a.value
        if key not in seen:
            seen[key] = []
            order.append(key)
        seen[key].append(a.source)
    values = [next(a.value for a in assertions if (a.value.strip().lower() if isinstance(a.value, str) else a.value) == k) for k in order]
    provenance = [ProvenanceEntry(field_key, src, "union_dedupe") for k in order for src in set(seen[k])]
    return values, provenance


def _resolve_skills(assertions: list[Assertion]):
    counts: dict[str, set] = {}
    for a in assertions:
        if not a.value:
            continue
        counts.setdefault(a.value, set()).add(a.source)
    skill_sources_total = len({a.source for a in assertions}) or 1
    skills = []
    provenance = []
    for name, sources in counts.items():
        confidence = min(1.0, len(sources) / skill_sources_total)
        skills.append(Skill(name=name, confidence=round(confidence, 2), sources=sorted(sources)))
        for src in sources:
            provenance.append(ProvenanceEntry("skills[]", src, "union_dedupe"))
    skills.sort(key=lambda s: (-s.confidence, s.name))
    return skills, provenance


def _dates_overlap(a_start, a_end, b_start, b_end) -> bool:
    if not a_start and not a_end and not b_start and not b_end:
        return True
    a0, a1 = a_start or "0000-00", a_end or "9999-99"
    b0, b1 = b_start or "0000-00", b_end or "9999-99"
    return a0 <= b1 and b0 <= a1


def _resolve_experience(candidate_id: str, assertions: list[Assertion]):
    groups: list[list[Assertion]] = []
    for a in assertions:
        company = (a.value.get("company") or "").strip().lower()
        placed = False
        for g in groups:
            gc = (g[0].value.get("company") or "").strip().lower()
            if company and company == gc and _dates_overlap(
                a.value.get("start"), a.value.get("end"), g[0].value.get("start"), g[0].value.get("end")
            ):
                g.append(a)
                placed = True
                break
        if not placed:
            groups.append([a])

    experiences, provenance, ledger = [], [], []
    for g in groups:
        winner, methods, _, entry = _resolve_assertion_group(candidate_id, "experience[]", g)
        merged = dict(winner.value)
        for a in g:
            if a is not winner and a.value.get("summary") and not merged.get("summary"):
                merged["summary"] = a.value["summary"]
        experiences.append(Experience(**{k: merged.get(k) for k in ("company", "title", "start", "end", "summary")}))
        for a in g:
            provenance.append(ProvenanceEntry("experience[]", a.source, methods[id(a)]))
        if entry:
            ledger.append(entry)
    return experiences, provenance, ledger


def _resolve_education(candidate_id: str, assertions: list[Assertion]):
    groups: list[list[Assertion]] = []
    for a in assertions:
        inst = (a.value.get("institution") or "").strip().lower()
        placed = False
        for g in groups:
            gi = (g[0].value.get("institution") or "").strip().lower()
            if inst and inst == gi:
                g.append(a)
                placed = True
                break
        if not placed:
            groups.append([a])

    education, provenance, ledger = [], [], []
    for g in groups:
        winner, methods, _, entry = _resolve_assertion_group(candidate_id, "education[]", g)
        education.append(Education(**{k: winner.value.get(k) for k in ("institution", "degree", "field", "end_year")}))
        for a in g:
            provenance.append(ProvenanceEntry("education[]", a.source, methods[id(a)]))
        if entry:
            ledger.append(entry)
    return education, provenance, ledger


def _resolve_projects(candidate_id: str, assertions: list[Assertion]):
    groups: list[list[Assertion]] = []
    for a in assertions:
        name = (a.value.get("name") or "").strip().lower()
        placed = False
        for g in groups:
            gn = (g[0].value.get("name") or "").strip().lower()
            if name and name == gn:
                g.append(a)
                placed = True
                break
        if not placed:
            groups.append([a])

    projects, provenance, ledger = [], [], []
    for g in groups:
        winner, methods, _, entry = _resolve_assertion_group(candidate_id, "projects[]", g)
        merged = dict(winner.value)
        for a in g:
            if a is not winner and a.value.get("summary") and not merged.get("summary"):
                merged["summary"] = a.value["summary"]
        projects.append(Project(**{k: merged.get(k) for k in ("name", "summary")}))
        for a in g:
            provenance.append(ProvenanceEntry("projects[]", a.source, methods[id(a)]))
        if entry:
            ledger.append(entry)
    return projects, provenance, ledger


def _dedupe_list_field_provenance(provenance: list[ProvenanceEntry]) -> list[ProvenanceEntry]:
    """Collapses repeated (field, source, method) provenance entries for
    list-type fields down to one each, so "résumé contributed 4 skills"
    is stated once instead of 4 times. Scalar fields are left untouched."""
    seen = set()
    out = []
    for entry in provenance:
        if entry.field in LIST_TYPE_PROVENANCE_FIELDS:
            key = (entry.field, entry.source, entry.method)
            if key in seen:
                continue
            seen.add(key)
        out.append(entry)
    return out


def resolve_candidate(candidate_id: str, assertions: list[Assertion]):
    """Resolves all assertions for one candidate into a CandidateProfile.

    Returns (CandidateProfile, list[ResolutionLogEntry], field_confidence_info dict).
    """
    by_field: dict[str, list[Assertion]] = {}
    for a in assertions:
        by_field.setdefault(a.field, []).append(a)

    profile = CandidateProfile(candidate_id=candidate_id)
    ledger: list[ResolutionLogEntry] = []
    field_info: dict[str, dict] = {}
    provenance: list[ProvenanceEntry] = []

    for a in by_field.get("_flag", []):
        provenance.append(ProvenanceEntry("identity", a.source, a.method))

    for field in SCALAR_FIELDS:
        value, info, prov, entry = _resolve_single_field(candidate_id, field, by_field.get(field, []))
        if value is not None:
            setattr(profile, field, value)
        field_info[field] = info
        provenance.extend(prov)
        if entry:
            ledger.append(entry)

    loc_value, loc_info, loc_prov, loc_entry = _resolve_single_field(candidate_id, "location", by_field.get("location", []))
    if loc_value:
        profile.location = Location(**{k: loc_value.get(k) for k in ("city", "region", "country")})
    field_info["location"] = loc_info
    provenance.extend(loc_prov)
    if loc_entry:
        ledger.append(loc_entry)

    for field_key, attr in LINK_FIELDS.items():
        value, info, prov, entry = _resolve_single_field(candidate_id, field_key, by_field.get(field_key, []))
        if value:
            setattr(profile.links, attr, value)
        field_info[field_key] = info
        provenance.extend(prov)
        if entry:
            ledger.append(entry)

    for field_key, attr in SIMPLE_LIST_FIELDS.items():
        values, prov = _resolve_list_field(field_key, by_field.get(field_key, []))
        setattr(profile, attr, values)
        provenance.extend(prov)

    portfolio, prov = _resolve_list_field("links.portfolio[]", by_field.get("links.portfolio[]", []))
    profile.links.portfolio = portfolio
    provenance.extend(prov)

    skills, prov = _resolve_skills(by_field.get("skills[]", []))
    profile.skills = skills
    provenance.extend(prov)

    experience, prov, exp_ledger = _resolve_experience(candidate_id, by_field.get("experience[]", []))
    profile.experience = experience
    provenance.extend(prov)
    ledger.extend(exp_ledger)

    education, prov, edu_ledger = _resolve_education(candidate_id, by_field.get("education[]", []))
    profile.education = education
    provenance.extend(prov)
    ledger.extend(edu_ledger)

    projects, prov, proj_ledger = _resolve_projects(candidate_id, by_field.get("projects[]", []))
    profile.projects = projects
    provenance.extend(prov)
    ledger.extend(proj_ledger)

    profile.provenance = _dedupe_list_field_provenance(provenance)
    profile.field_confidence = field_info
    return profile, ledger, field_info
