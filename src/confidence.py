"""Per-field & overall confidence scoring (pipeline stage 6).

Deliberately a simple, explainable heuristic — not ML. Richness-aware
(rewards winners that came from a clear "density win"), not just
rank-aware, which is the actual upgrade over a plain source-priority system.
"""

FIELD_WEIGHTS = {
    "full_name": 3, "emails": 3, "phones": 2, "location": 1, "headline": 1,
    "skills": 2, "experience": 2, "education": 1, "links": 1, "projects": 1,
}

# A candidate grouped via the weak (fuzzy name + corroborating signal, no
# shared email/phone) identity match is inherently less certain than one
# grouped via a strong key — cap overall_confidence regardless of how
# confident the individual fields look, since the grouping itself is the
# weaker link here.
WEAK_MATCH_CONFIDENCE_CAP = 0.6


def _field_confidence_from_info(info: dict) -> float:
    if not info or info.get("num_agreeing", 0) == 0:
        return 0.0
    confidence = 0.4 + 0.2 * info["num_agreeing"] + 0.15 * info.get("richness", 0.0)
    if info.get("normalize_failed"):
        confidence -= 0.15
    confidence = min(1.0, max(0.0, confidence))
    if info.get("unresolved"):
        confidence = min(confidence, 0.5)
    return round(confidence, 2)


def compute_confidence(profile, field_info: dict) -> float:
    """Mutates nothing; returns overall_confidence. Caller assigns it."""
    scores: dict[str, float] = {}

    for field in ("full_name", "headline", "years_experience"):
        scores[field] = _field_confidence_from_info(field_info.get(field, {}))
    scores["location"] = _field_confidence_from_info(field_info.get("location", {}))
    link_scores = [_field_confidence_from_info(field_info.get(k, {})) for k in ("links.linkedin", "links.github")]
    scores["links"] = max(link_scores) if any(link_scores) else (1.0 if profile.links.portfolio else 0.0)

    scores["emails"] = 1.0 if profile.emails else 0.0
    scores["phones"] = 1.0 if profile.phones else 0.0
    scores["skills"] = round(sum(s.confidence for s in profile.skills) / len(profile.skills), 2) if profile.skills else 0.0
    scores["experience"] = 1.0 if profile.experience else 0.0
    scores["education"] = 1.0 if profile.education else 0.0
    scores["projects"] = 1.0 if profile.projects else 0.0

    populated_weight, weighted_sum = 0, 0.0
    for field, weight in FIELD_WEIGHTS.items():
        if field in ("full_name",) or scores.get(field, 0) > 0 or field in ("emails", "phones"):
            weighted_sum += scores.get(field, 0.0) * weight
            populated_weight += weight

    overall = weighted_sum / populated_weight if populated_weight else 0.0

    if not profile.full_name:
        overall *= 0.7
    if not profile.emails and not profile.phones:
        overall *= 0.7

    overall = min(1.0, max(0.0, overall))
    if any(p.field == "identity" and p.method == "weak_match" for p in profile.provenance):
        overall = min(overall, WEAK_MATCH_CONFIDENCE_CAP)

    return round(overall, 2)
