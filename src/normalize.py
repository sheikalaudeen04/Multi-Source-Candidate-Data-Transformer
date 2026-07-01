"""Normalization rules: phone -> E.164, dates -> YYYY-MM, country -> ISO alpha-2,
skills -> canonical name, plus structural_richness scoring.
"""
import re
from typing import Optional

import phonenumbers

# --- Phone -----------------------------------------------------------------

def normalize_phone(raw: str, default_region: str = "US") -> tuple[Optional[str], bool]:
    """Returns (e164_or_raw, failed). failed=True means keep raw, flag normalize_failed."""
    if not raw:
        return None, True
    try:
        parsed = phonenumbers.parse(raw, default_region)
        if not phonenumbers.is_valid_number(parsed):
            return raw, True
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), False
    except phonenumbers.NumberParseException:
        return raw, True


# --- Dates -------------------------------------------------------------------

_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "sept": "09", "oct": "10", "nov": "11", "dec": "12",
}


def normalize_date(raw: str) -> tuple[Optional[str], bool]:
    """Returns (YYYY-MM or None, month_inferred)."""
    if not raw:
        return None, False
    raw = raw.strip()
    # YYYY-MM
    m = re.match(r"^(\d{4})-(\d{2})$", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}", False
    # MM/YYYY
    m = re.match(r"^(\d{1,2})/(\d{4})$", raw)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}", False
    # "Jan 2022" / "January 2022"
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{4})$", raw)
    if m:
        mon = _MONTHS.get(m.group(1).lower()[:4].rstrip("."), None) or _MONTHS.get(m.group(1).lower()[:3])
        if mon:
            return f"{m.group(2)}-{mon}", False
    # YYYY only
    m = re.match(r"^(\d{4})$", raw)
    if m:
        return f"{m.group(1)}-01", True
    return None, False


# --- Country -----------------------------------------------------------------

_COUNTRY_MAP = {
    "usa": "US", "us": "US", "united states": "US", "united states of america": "US",
    "uk": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "india": "IN", "canada": "CA", "germany": "DE", "france": "FR", "australia": "AU",
    "singapore": "SG", "netherlands": "NL", "ireland": "IE", "spain": "ES", "italy": "IT",
    "brazil": "BR", "mexico": "MX", "japan": "JP", "china": "CN",
}


def normalize_country(raw: str) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().lower()
    if len(raw.strip()) == 2:
        return raw.strip().upper()
    return _COUNTRY_MAP.get(key, raw.strip())


# --- Skills --------------------------------------------------------------------

_SKILL_SYNONYMS = {
    "js": "JavaScript", "javascript": "JavaScript", "reactjs": "React", "react.js": "React",
    "react": "React", "py": "Python", "python": "Python", "ml": "Machine Learning",
    "machine learning": "Machine Learning", "ts": "TypeScript", "typescript": "TypeScript",
    "node": "Node.js", "nodejs": "Node.js", "node.js": "Node.js", "k8s": "Kubernetes",
    "kubernetes": "Kubernetes", "golang": "Go", "go": "Go", "sql": "SQL",
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "aws": "AWS",
    "c++": "C++", "c#": "C#", "css": "CSS", "html": "HTML",
}


def normalize_skill(raw: str) -> str:
    key = raw.strip().lower()
    if key in _SKILL_SYNONYMS:
        return _SKILL_SYNONYMS[key]
    return raw.strip().title()


# --- Structural richness -------------------------------------------------------

def structural_richness(field_name: str, value) -> float:
    """0-1 score of how much corroborating structure a value carries."""
    if field_name.startswith("experience"):
        if isinstance(value, dict):
            present = sum(1 for f in ["title", "company", "start", "end", "summary"] if value.get(f))
            return present / 5.0
        return 0.2
    if field_name.startswith("education"):
        if isinstance(value, dict):
            present = sum(1 for f in ["institution", "degree", "field", "end_year"] if value.get(f))
            return present / 4.0
        return 0.2
    if isinstance(value, dict):
        present = sum(1 for v in value.values() if v)
        return min(1.0, present / max(1, len(value)))
    return 0.5 if value else 0.0


# --- Pipeline stage: normalize a list of raw Assertions ------------------------

def normalize_assertions(assertions: list) -> list:
    """Stage 3 of the pipeline: per-assertion cleanup + richness scoring.

    Returns new Assertion objects (Assertion is frozen) with normalized values
    and structural_richness populated. Assertions that fail to normalize keep
    their raw value but get a 'normalize_failed' note in raw_context.
    """
    from .assertion import Assertion  # local import avoids a circular import

    out = []
    for a in assertions:
        value, failed_note = a.value, None

        if a.field == "phones[]":
            e164, failed = normalize_phone(a.value)
            value = e164 if e164 else a.value
            if failed:
                failed_note = "normalize_failed"
        elif a.field == "skills[]":
            value = normalize_skill(a.value)
        elif a.field == "location" and isinstance(a.value, dict):
            value = dict(a.value)
            if value.get("country"):
                value["country"] = normalize_country(value["country"])
        elif a.field in ("experience[]",) and isinstance(a.value, dict):
            value = dict(a.value)
            for key in ("start", "end"):
                if value.get(key):
                    parsed, inferred = normalize_date(value[key])
                    value[key] = parsed
                    if inferred:
                        failed_note = "month_inferred"

        richness = structural_richness(a.field, value)
        raw_context = failed_note or a.raw_context
        out.append(Assertion(
            field=a.field, value=value, source=a.source, method=a.method,
            raw_context=raw_context, structural_richness=richness,
        ))
    return out
