"""Recruiter CSV extractor: structured rows -> list[Assertion].

Column name variants are mapped via ALIASES since real recruiter exports
rarely agree on header names.
"""
import csv
from pathlib import Path

from ..assertion import Assertion

ALIASES = {
    "full_name": {"full_name", "name", "candidate_name"},
    "email": {"email", "email_address", "e-mail"},
    "phone": {"phone", "phone_number", "mobile", "telephone"},
    "current_company": {"current_company", "company", "employer"},
    "title": {"title", "job_title", "current_title", "position"},
}


def _build_lookup(fieldnames: list[str]) -> dict[str, str]:
    lookup = {}
    for canonical, variants in ALIASES.items():
        for fn in fieldnames:
            if fn.strip().lower() in variants:
                lookup[canonical] = fn
                break
    return lookup


def extract(path: str) -> list[list[Assertion]]:
    """Returns one batch (list[Assertion]) per CSV row, since a shared
    recruiter export has one row per candidate (read once, not re-opened)."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        with p.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return []
            lookup = _build_lookup(reader.fieldnames)
            batches = []
            for row in reader:
                row_assertions = _row_to_assertions(row, lookup)
                if row_assertions:
                    batches.append(row_assertions)
            return batches
    except (csv.Error, OSError, UnicodeDecodeError):
        return []


def _row_to_assertions(row: dict, lookup: dict[str, str]) -> list[Assertion]:
    out = []
    src, method = "recruiter_csv", "direct_field"

    def get(key):
        col = lookup.get(key)
        return row.get(col, "").strip() if col else ""

    if get("full_name"):
        out.append(Assertion("full_name", get("full_name"), src, method))
    if get("email"):
        out.append(Assertion("emails[]", get("email"), src, method))
    if get("phone"):
        out.append(Assertion("phones[]", get("phone"), src, method))
    company, title = get("current_company"), get("title")
    if company or title:
        out.append(Assertion(
            "experience[]",
            {"company": company or None, "title": title or None, "start": None, "end": None, "summary": None},
            src, method,
        ))
    return out
