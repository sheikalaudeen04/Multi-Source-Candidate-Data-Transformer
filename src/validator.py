"""jsonschema-based validation of the projected output (pipeline stage 8).

The schema is derived dynamically from the active config (default or
custom) — never hand-rolled type checks. A bad/garbage source must never
crash this stage: missing fields are either null/omitted upstream by the
projector, or surfaced as clear errors when on_missing == 'error'.
"""
from jsonschema import Draft7Validator

_TYPE_MAP = {
    "string": "string",
    "number": "number",
    "object": "object",
    "string[]": "array",
    "object[]": "array",
}


def derive_schema(config: dict) -> dict:
    properties: dict = {}
    required: list[str] = []

    for spec in config.get("fields", []):
        path, declared = spec["path"], spec.get("type", "string")
        json_type = _TYPE_MAP.get(declared, "string")
        prop: dict = {"type": [json_type, "null"]}
        if declared.endswith("[]"):
            item_type = "string" if declared == "string[]" else "object"
            prop = {"type": ["array", "null"], "items": {"type": item_type}}
        properties[path] = prop
        if spec.get("required") and config.get("on_missing") == "error":
            required.append(path)

    if config.get("include_confidence", True):
        properties["overall_confidence"] = {"type": ["number", "null"]}
    if config.get("include_provenance", True):
        properties["provenance"] = {"type": ["array", "null"]}

    return {"type": "object", "properties": properties, "required": required}


def validate_projected(projected: dict, schema: dict) -> list[str]:
    """Returns a list of human-readable warning/error strings (empty if valid)."""
    validator = Draft7Validator(schema)
    messages = []
    for err in validator.iter_errors(projected):
        path = ".".join(str(p) for p in err.absolute_path) or "(root)"
        candidate = projected.get("candidate_id", "?")
        messages.append(f"candidate_id={candidate} field={path}: {err.message}")
    return messages
