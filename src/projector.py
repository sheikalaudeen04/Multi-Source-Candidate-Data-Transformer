"""Runtime config / projection layer (pipeline stage 7) — the "required twist".

Reshapes the internal canonical record per a config: select/rename/remap
fields, re-normalize, toggle provenance/confidence, control missing-value
behavior. No config passed -> a built-in default config that mirrors the
full canonical schema, proving both paths go through the same code.
"""
import re

from .normalize import normalize_phone, normalize_skill, normalize_country

DEFAULT_CONFIG = {
    "fields": [
        {"path": "candidate_id", "type": "string"},
        {"path": "full_name", "type": "string"},
        {"path": "emails", "type": "string[]"},
        {"path": "phones", "type": "string[]"},
        {"path": "location", "type": "object"},
        {"path": "links", "type": "object"},
        {"path": "headline", "type": "string"},
        {"path": "years_experience", "type": "number"},
        {"path": "skills", "type": "object[]"},
        {"path": "experience", "type": "object[]"},
        {"path": "education", "type": "object[]"},
        {"path": "projects", "type": "object[]"},
    ],
    "include_confidence": True,
    "include_provenance": True,
    "on_missing": "null",
}


class ProjectionError(Exception):
    pass


_SEGMENT_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(\[\]|\[(\d+)\])?$")


def _walk(node, segments: list[str]):
    if not segments:
        return node
    seg, rest = segments[0], segments[1:]
    m = _SEGMENT_RE.match(seg)
    if not m or not isinstance(node, dict):
        return None
    name, bracket, idx = m.group(1), m.group(2), m.group(3)
    if name not in node:
        return None
    value = node[name]
    if bracket == "[]":
        if not isinstance(value, list):
            return None
        return [_walk(item, rest) for item in value] if rest else value
    if bracket is not None:
        i = int(idx)
        if not isinstance(value, list) or i >= len(value):
            return None
        return _walk(value[i], rest)
    return _walk(value, rest)


def resolve_path(record: dict, path: str):
    return _walk(record, path.split("."))


def _nullify_empty_lists(value):
    """Recursively converts empty lists to None so 'no data from any source'
    is represented the same way (null) everywhere — including list-type
    fields nested inside an object field (e.g. links.portfolio), not just
    at the top level."""
    if isinstance(value, dict):
        return {k: _nullify_empty_lists(v) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return None
        return [_nullify_empty_lists(v) for v in value]
    return value


def _apply_normalize(value, kind: str):
    if value is None:
        return None
    if kind == "E164":
        if isinstance(value, list):
            return [normalize_phone(v)[0] if v else v for v in value]
        return normalize_phone(value)[0] if value else value
    if kind == "canonical":
        if isinstance(value, list):
            return [normalize_skill(v) if isinstance(v, str) else v for v in value]
        return normalize_skill(value) if isinstance(value, str) else value
    if kind == "country":
        if isinstance(value, list):
            return [normalize_country(v) if v else v for v in value]
        return normalize_country(value)
    return value


def project(record: dict, config: dict | None = None) -> tuple[dict, list[str]]:
    """Returns (projected_dict, errors). errors is non-empty only when
    on_missing == 'error' and a required field is missing."""
    cfg = config or DEFAULT_CONFIG
    on_missing = cfg.get("on_missing", "null")
    out: dict = {}
    errors: list[str] = []

    for spec in cfg.get("fields", []):
        path = spec["path"]
        source_path = spec.get("from", path)
        value = resolve_path(record, source_path)

        if spec.get("normalize"):
            value = _apply_normalize(value, spec["normalize"])

        value = _nullify_empty_lists(value)

        missing = value is None or value == [] or value == {}
        field_on_missing = spec.get("on_missing", on_missing)

        if missing:
            if spec.get("required") and field_on_missing == "error":
                errors.append(
                    f"required field '{path}' (from '{source_path}') is missing for "
                    f"candidate_id={record.get('candidate_id')}"
                )
                continue
            if field_on_missing == "omit":
                continue
            out[path] = None
        else:
            out[path] = value

    if cfg.get("include_confidence", True):
        out["overall_confidence"] = record.get("overall_confidence")
    if cfg.get("include_provenance", True):
        out["provenance"] = record.get("provenance")

    return out, errors
