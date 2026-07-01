"""ATS JSON extractor: semi-structured, with its own field names that do NOT
match canonical names. The mapping below is the explicit translation table
(documented again in README).

Expected shape (one record, or a list of records for batch mode):
{
  "candidate_ref": "...",
  "contact": {"full_name": "...", "email_address": "...", "mobile": "..."},
  "current_role": {"employer": "...", "job_title": "...", "started": "..."},
  "address": {"town": "...", "state": "...", "nation": "..."},
  "skill_tags": ["python", "sql"],
  "summary_headline": "..."
}
"""
import json
from pathlib import Path

from ..assertion import Assertion

SRC, METHOD = "ats_json", "direct_field"


def extract(path: str) -> list[list[Assertion]]:
    """Returns one batch (list[Assertion]) per ATS record (a JSON array of N
    records is read once and split into per-candidate assertions)."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []

    records = data if isinstance(data, list) else [data]
    batches = []
    for rec in records:
        if isinstance(rec, dict):
            rec_assertions = _record_to_assertions(rec)
            if rec_assertions:
                batches.append(rec_assertions)
    return batches


def _record_to_assertions(rec: dict) -> list[Assertion]:
    out = []
    contact = rec.get("contact") or {}
    role = rec.get("current_role") or {}
    addr = rec.get("address") or {}

    if contact.get("full_name"):
        out.append(Assertion("full_name", contact["full_name"], SRC, METHOD))
    if contact.get("email_address"):
        out.append(Assertion("emails[]", contact["email_address"], SRC, METHOD))
    if contact.get("mobile"):
        out.append(Assertion("phones[]", contact["mobile"], SRC, METHOD))

    if role.get("employer") or role.get("job_title"):
        out.append(Assertion(
            "experience[]",
            {
                "company": role.get("employer"),
                "title": role.get("job_title"),
                "start": role.get("started"),
                "end": role.get("ended"),
                "summary": role.get("summary"),
            },
            SRC, METHOD,
        ))

    if addr.get("town") or addr.get("state") or addr.get("nation"):
        out.append(Assertion(
            "location",
            {"city": addr.get("town"), "region": addr.get("state"), "country": addr.get("nation")},
            SRC, METHOD,
        ))

    for skill in rec.get("skill_tags") or []:
        out.append(Assertion("skills[]", skill, SRC, METHOD))

    if rec.get("summary_headline"):
        out.append(Assertion("headline", rec["summary_headline"], SRC, METHOD))

    return out
