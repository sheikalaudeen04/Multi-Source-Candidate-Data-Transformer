"""Recruiter free-text notes (.txt): lowest reliability rank."""
from pathlib import Path

from ..assertion import Assertion
from . import text_heuristics as th

SRC, METHOD = "notes", "regex_extract"


def extract(path: str) -> list[Assertion]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    if not text.strip():
        return []

    out = []
    email = th.find_email(text)
    if email:
        out.append(Assertion("emails[]", email, SRC, METHOD))
    phone = th.find_phone(text)
    if phone:
        out.append(Assertion("phones[]", phone, SRC, METHOD))
    for skill in th.find_skills(text):
        out.append(Assertion("skills[]", skill, SRC, METHOD))
    return out
