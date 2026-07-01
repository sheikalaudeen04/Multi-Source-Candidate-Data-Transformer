"""Presentation-only helper: turns the pipeline's plain JSON output (plus
the structured ledger run_pipeline() now returns) into a readable HTML
view. No pipeline logic — purely formatting of data the pipeline already
produced. Works generically for both the default canonical schema and
arbitrary custom-config field names (e.g. a renamed "primary_email"), since
it just walks whatever keys are present.
"""
import html

# A field's provenance only collapses into a "N sources contributed" summary
# when every entry for it is a plain list-merge (no winner/loser to show).
# Fields with a resolved conflict keep their winner/loser breakdown visible
# directly, since that's the informative part and it's already low-volume.
_COLLAPSIBLE_METHODS = {"union_dedupe"}

# Only these resolution outcomes represent an actual contested decision worth
# flagging inline next to the field's value. direct_field (single source)
# and agreement_resolved (sources agreed) aren't interesting decisions —
# they're just normal population, so no badge for those.
_CONTESTED_REASONS = {"density_win", "rank_resolved", "unresolved_conflict"}

# Maps a top-level profile dict key (as it appears in the *default* config's
# output) to the canonical field name resolve.py's ledger entries use. Only
# covers fields that can actually go through contested resolution — skills/
# emails/phones/portfolio are always union_dedupe, never contested, so they
# don't need an entry here. A custom config that renames a field (e.g.
# "primary_email") simply won't match anything here, so it gets no badge —
# a reasonable fallback since the badge is a presentation nicety, not a
# correctness requirement.
_CANONICAL_FIELD_NAMES = {
    "full_name": "full_name",
    "headline": "headline",
    "years_experience": "years_experience",
    "experience": "experience[]",
    "education": "education[]",
    "projects": "projects[]",
}
_LINKS_CANONICAL_FIELD_NAMES = {"linkedin": "links.linkedin", "github": "links.github"}


def render_profiles(results: list[dict], ledger_per_result: list[list] | None = None) -> str:
    """`ledger_per_result[i]` is the list of ResolutionLogEntry objects for
    `results[i]`, already matched up by the caller using the *internal*
    candidate_id (see cli.run_pipeline) — independent of whether the
    projected dict itself includes a candidate_id field. This is why the
    ledger never fails to associate with a profile, even in custom-config
    mode where candidate_id may not be part of the chosen output shape."""
    if not results:
        return '<p class="muted">No candidates produced from the given inputs.</p>'
    ledgers = ledger_per_result if ledger_per_result is not None else [[] for _ in results]
    return "\n".join(_render_candidate_card(p, entries) for p, entries in zip(results, ledgers))


def _render_candidate_card(profile: dict, ledger_entries: list) -> str:
    name = profile.get("full_name") or profile.get("primary_email") or profile.get("candidate_id") or "Candidate"
    parts = [f'<div class="candidate-card">', f"<h3>{html.escape(str(name))}</h3>"]

    confidence = profile.get("overall_confidence")
    if confidence is not None:
        parts.append(_render_confidence_badge(confidence))

    ledger_by_field: dict[str, list] = {}
    for e in ledger_entries:
        ledger_by_field.setdefault(e.field, []).append(e)

    skip = {"overall_confidence", "provenance", "full_name", "candidate_id"}
    rows = [
        _render_field(k, v, _CANONICAL_FIELD_NAMES.get(k), ledger_by_field)
        for k, v in profile.items() if k not in skip
    ]
    parts.append('<div class="fields">' + "".join(rows) + "</div>")

    provenance = profile.get("provenance")
    if provenance:
        parts.append(_render_provenance(provenance))

    parts.append("</div>")
    return "".join(parts)


def _render_confidence_badge(confidence) -> str:
    try:
        pct = round(float(confidence) * 100)
    except (TypeError, ValueError):
        return ""
    if confidence >= 0.75:
        cls = "high"
    elif confidence >= 0.5:
        cls = "mid"
    else:
        cls = "low"
    return f'<div class="confidence-badge confidence-{cls}">Overall confidence: {pct}%</div>'


def _contested_entries(canonical: str | None, ledger_by_field: dict) -> list:
    if not canonical:
        return []
    return [e for e in ledger_by_field.get(canonical, []) if e.reason in _CONTESTED_REASONS]


def _match_winner(item: dict, entries: list):
    """Finds the ledger entry whose winner_value produced this list item.
    Uses a subset match (every key in winner_value must match item) rather
    than full dict equality, since e.g. experience[] backfills a missing
    summary from a losing assertion after the winner is already chosen —
    the final merged item is a superset of winner_value, not identical."""
    for e in entries:
        if isinstance(e.winner_value, dict) and all(item.get(k) == v for k, v in e.winner_value.items()):
            return e
    return None


def _render_field(key, value, canonical: str | None = None, ledger_by_field: dict | None = None) -> str:
    ledger_by_field = ledger_by_field or {}
    label = html.escape(str(key).replace("_", " ").replace(".", " ").title())

    if value is None or value == [] or value == {}:
        return f'<div class="field"><span class="field-label">{label}</span><span class="field-value muted">—</span></div>'

    if isinstance(value, list):
        if key == "skills" and all(isinstance(v, dict) and "name" in v for v in value):
            return f'<div class="field field-block"><span class="field-label">{label}</span>{_render_skills_table(value)}</div>'
        if all(isinstance(v, str) for v in value):
            tags = "".join(f'<span class="tag">{html.escape(v)}</span>' for v in value)
            return f'<div class="field"><span class="field-label">{label}</span><div class="tag-list">{tags}</div></div>'
        if all(isinstance(v, dict) for v in value):
            entries = _contested_entries(canonical, ledger_by_field)
            rows = "".join(_render_dict_row(v, _match_winner(v, entries)) for v in value)
            return f'<div class="field field-block"><span class="field-label">{label}</span><div class="mini-list">{rows}</div></div>'
        return f'<div class="field"><span class="field-label">{label}</span><span class="field-value">{html.escape(str(value))}</span></div>'

    if isinstance(value, dict):
        child_map = _LINKS_CANONICAL_FIELD_NAMES if key == "links" else {}
        inner = "".join(_render_field(k, v, child_map.get(k), ledger_by_field) for k, v in value.items())
        return f'<div class="field field-block"><span class="field-label">{label}</span><div class="nested">{inner}</div></div>'

    contested = _contested_entries(canonical, ledger_by_field)
    badge = _render_resolution_badge(contested[0]) if contested else ""
    return f'<div class="field"><span class="field-label">{label}</span><span class="field-value">{html.escape(str(value))}</span>{badge}</div>'


def _render_skills_table(skills: list[dict]) -> str:
    """3-column table (Skill | Confidence | Sources), sorted by confidence
    descending. UI-only presentation — resolve.py already sorts skills this
    way, but this re-sorts defensively at render time without mutating the
    underlying data, so the Raw JSON / output.json ordering is untouched."""
    ordered = sorted(skills, key=lambda s: -(s.get("confidence") or 0))
    rows = []
    for s in ordered:
        name = html.escape(str(s.get("name", "")))
        try:
            pct = f"{round(float(s.get('confidence', 0)) * 100)}%"
        except (TypeError, ValueError):
            pct = "—"
        sources = html.escape(", ".join(s.get("sources") or []))
        rows.append(f"<tr><td>{name}</td><td>{pct}</td><td>{sources}</td></tr>")
    return (
        '<table class="skills-table"><thead><tr><th>Skill</th><th>Confidence</th><th>Sources</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _render_dict_row(d: dict, matched_entry=None) -> str:
    bits = " · ".join(
        f"<strong>{html.escape(str(k))}:</strong> {html.escape(str(v))}"
        for k, v in d.items() if v not in (None, "", [])
    )
    badge = _render_resolution_badge(matched_entry) if matched_entry else ""
    return f'<div class="mini-row">{bits or "—"}{badge}</div>'


def _render_resolution_badge(entry) -> str:
    """Compact outcome-only tag for a contested field's resolution — just
    the reason label (e.g. "density_win"), nothing else. The full
    winner/loser values, sources, richness, and margin live only in the
    Raw JSON's provenance and the --verbose CLI output, not duplicated
    here, so the default Pretty view stays a quick glance, not a second
    copy of the ledger."""
    reason = html.escape(entry.reason)
    return f'<span class="resolution-tag resolution-{reason}" title="See Raw JSON / --verbose CLI output for full detail">{reason}</span>'


def _render_provenance(entries: list[dict]) -> str:
    """Groups provenance rows by field. Fields where every contribution is a
    plain union_dedupe merge collapse into a one-line summary (expandable);
    fields with an actual resolved conflict (winner/loser) stay fully
    visible, since that's the informative part and it's already low-volume."""
    by_field: dict[str, list[dict]] = {}
    for e in entries:
        by_field.setdefault(e.get("field", ""), []).append(e)

    groups = []
    for field, group in by_field.items():
        if group and all(e.get("method") in _COLLAPSIBLE_METHODS for e in group):
            sources = list(dict.fromkeys(e.get("source", "") for e in group))
            detail_rows = "".join(
                f'<tr><td>{html.escape(e.get("source",""))}</td>'
                f'<td><span class="method-tag method-{html.escape(e.get("method",""))}">{html.escape(e.get("method",""))}</span></td></tr>'
                for e in group
            )
            groups.append(
                f'<details class="provenance-field"><summary>{html.escape(field)} — '
                f'{len(group)} source(s) contributed ({html.escape(", ".join(sources))})</summary>'
                f'<table><tbody>{detail_rows}</tbody></table></details>'
            )
        else:
            rows = "".join(
                f'<div class="provenance-row"><span class="prov-source">{html.escape(e.get("source",""))}</span>'
                f'<span class="method-tag method-{html.escape(e.get("method",""))}">{html.escape(e.get("method",""))}</span></div>'
                for e in group
            )
            groups.append(f'<div class="provenance-field-block"><strong>{html.escape(field)}</strong>{rows}</div>')

    return (
        f'<details class="provenance" open><summary>Provenance ({len(entries)} entries — grouped by field)</summary>'
        f'<div class="provenance-groups">{"".join(groups)}</div></details>'
    )
