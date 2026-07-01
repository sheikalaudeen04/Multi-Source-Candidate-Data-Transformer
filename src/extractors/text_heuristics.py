"""Shared regex/keyword heuristics for unstructured text sources (resume, notes)."""
import re

# Allows an optional space/tab before '@' — PDF text extraction commonly
# inserts one around icon-prefixed contact lines (e.g. an email/phone icon
# glyph rendered as whitespace). The match is cleaned of that space after.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+\s?@\s?[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(\+?\d[\d\-\.\(\)\s]{8,}\d)")

# Common résumé section headings, used to find where the "Skills" section
# ends when the source has no blank line between sections (pdfplumber often
# doesn't preserve one) — see find_skills_section.
SECTION_HEADINGS = [
    "skills", "experience", "work experience", "professional experience",
    "education", "certificates", "certifications", "projects", "languages",
    "profile", "summary", "objective", "awards", "achievements",
    "publications", "interests", "references", "contact",
]
_HEADING_LINE_RE = re.compile(
    r"^\s*(?:" + "|".join(re.escape(h) for h in SECTION_HEADINGS) + r")\s*$", re.IGNORECASE,
)

# Small known-skills vocabulary for keyword matching in free text.
SKILL_VOCAB = [
    "python", "java", "javascript", "typescript", "react", "node.js", "node",
    "sql", "postgresql", "mysql", "mongodb", "aws", "gcp", "azure", "docker",
    "kubernetes", "go", "golang", "c++", "c#", "machine learning", "ml",
    "django", "flask", "fastapi", "html", "css", "git", "linux",
]


def find_email(text: str) -> str | None:
    m = EMAIL_RE.search(text)
    return m.group(0).replace(" ", "") if m else None


def find_phone(text: str) -> str | None:
    m = PHONE_RE.search(text)
    return m.group(1).strip() if m else None


# Matches a full http(s) URL, or a bare linkedin.com/github.com domain
# (résumé contact lines commonly omit the scheme, e.g. "linkedin.com/in/jane").
_URL_RE = re.compile(
    r"https?://[^\s,;)]+|(?:www\.)?(?:linkedin|github)\.com/[^\s,;)]+", re.IGNORECASE,
)


# Platform/social/dev-site names that PDF icon fonts commonly render as
# literal words (e.g. an icon glyph followed by "Github"/"LinkedIn" instead
# of an actual URL) — these must never be mistaken for a city or region.
_NON_LOCATION_TERMS = {
    "github", "gitlab", "linkedin", "twitter", "x", "instagram", "facebook",
    "portfolio", "behance", "dribbble", "medium", "stackoverflow", "youtube",
    "resume", "cv", "email", "phone", "contact", "website", "blog",
}
# A domain-like token (TLD, scheme, or "www.") is never a location, even
# when it lacks "http://" (e.g. a bare personal site like "janedoe.tech").
_DOMAIN_LIKE_RE = re.compile(
    r"\.(com|net|org|io|dev|tech|app|co|me|info|in|xyz|ai)\b|https?://|www\.", re.IGNORECASE,
)
# "City, Region" / "City, Country" — comma-separated, each side capitalized,
# letters/spaces/periods only (so "St. Louis, Missouri" still matches). Uses
# [ \t] rather than \s so a match can never span a newline — \s matching
# "\n" let an earlier version of this regex merge "Github LinkedIn" on one
# line with "Coimbatore" on the next into a single bogus "city". The
# trailing word-group quantifiers are non-greedy: a trailing icon-rendered
# word ("Portfolio", "Github", ...) right after the region must NOT get
# pulled into the match just because the pattern technically allows up to
# two extra words — only expand when the comma actually requires it (e.g.
# multi-word cities like "San Francisco").
_LOCATION_PAIR_RE = re.compile(
    r"\b([A-Z][A-Za-z.]+(?:[ \t][A-Z][A-Za-z.]+){0,2}?),[ \t]*([A-Z][A-Za-z.]+(?:[ \t][A-Z][A-Za-z.]+){0,2}?)\b"
)


def _looks_like_location_token(token: str) -> bool:
    """Content-based validation, not positional — rejects anything that
    looks like a URL, domain, or known platform name, regardless of where
    it sits on the line. This is what's missing from blindly trusting
    "whatever's left after stripping email/phone": an icon font can render
    a platform name as a bare word with no URL attached at all, and that
    word can land in any position depending on how the icon row is laid
    out."""
    token = token.strip()
    if not token or len(token) > 30:
        return False
    if re.search(r"[\d@/]", token):
        return False
    if _DOMAIN_LIKE_RE.search(token):
        return False
    words = re.findall(r"[A-Za-z']+", token.lower())
    if not words or any(w in _NON_LOCATION_TERMS for w in words):
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z .'-]*$", token))


_SECTION_LABEL_LINE_RE = re.compile(
    r"^\s*(?:" + "|".join(re.escape(h) for h in SECTION_HEADINGS) + r")\s*:", re.IGNORECASE,
)


def find_location(text: str, header_lines: int = 8) -> str | None:
    """Looks for a "City, Region"/"City, Country" shaped pair within the
    résumé's contact-header area (the first few lines) — content-based, not
    positional, so it works whether location sits on the email/phone line
    or its own line (e.g. an icon-only header that puts email/phone/social
    icons on one line and location/portfolio icons on the next). Falls back
    to a bare single-token city (no comma) on the email/phone line itself.
    Every candidate is validated against _looks_like_location_token so a
    platform name or domain rendered by an icon font is never mistaken for
    a city.

    The pair-matcher runs *per line*, not over the whole header blob, and
    skips any line with more than one comma or a "Skills:"/"Languages:"-
    style section-label prefix — without that, a short résumé whose Skills
    line ("Skills: JavaScript, React, Python, ...") happens to fall within
    the header window gets misread as a location, since two capitalized
    words separated by a comma is exactly what a real "City, Region" looks
    like too. A genuine location mention has exactly one comma in context;
    a list has several.
    """
    lines = text.splitlines()[:header_lines]

    for line in lines:
        if line.count(",") != 1 or _SECTION_LABEL_LINE_RE.match(line):
            continue
        m = _LOCATION_PAIR_RE.search(line)
        if not m:
            continue
        city, region = m.group(1).strip(), m.group(2).strip()
        if _looks_like_location_token(city) and _looks_like_location_token(region):
            return f"{city}, {region}"

    for line in lines:
        email_m = EMAIL_RE.search(line)
        phone_m = PHONE_RE.search(line)
        if not (email_m or phone_m):
            continue
        remainder = line
        for m in list(_URL_RE.finditer(line)) + [x for x in (email_m, phone_m) if x]:
            remainder = remainder.replace(m.group(0), " ")
        remainder = re.sub(r"[|,•]", " ", remainder)
        remainder = re.sub(r"\s{2,}", " ", remainder).strip()
        if _looks_like_location_token(remainder):
            return remainder

    return None


def find_links(text: str) -> dict:
    """Scans free text for a LinkedIn profile URL, a GitHub profile URL, and
    any other URLs (treated as portfolio links). This is plain text
    extraction from a document the user supplied themselves — not an API
    integration or scrape of a third-party site, so it's unaffected by the
    LinkedIn API/ToS descope (see README)."""
    linkedin, github, portfolio = None, None, []
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;)")
        if not url.lower().startswith("http"):
            url = "https://" + url
        lower = url.lower()
        if "linkedin.com" in lower:
            linkedin = linkedin or url
        elif "github.com" in lower:
            github = github or url
        else:
            portfolio.append(url)
    return {"linkedin": linkedin, "github": github, "portfolio": portfolio}


def find_skills(text: str) -> list[str]:
    lower = text.lower()
    found = []
    for skill in SKILL_VOCAB:
        if re.search(r"\b" + re.escape(skill) + r"\b", lower):
            found.append(skill)
    return found


def _section_lines(text: str, heading: str) -> list[str] | None:
    """Returns the lines between a heading line matching `heading` and the
    *next* recognized section heading (or end of text) — bounded this way
    rather than by a blank line, since many PDF extractions (pdfplumber
    included) don't preserve blank lines between sections. Returns None if
    `heading` isn't found at all."""
    lines = text.splitlines()
    start = next(
        (i + 1 for i, line in enumerate(lines) if re.match(rf"^\s*{re.escape(heading)}\s*[:]?\s*$", line, re.IGNORECASE)),
        None,
    )
    if start is None:
        return None
    end = next((i for i in range(start, len(lines)) if _HEADING_LINE_RE.match(lines[i])), len(lines))
    return lines[start:end]


def find_skills_section(text: str) -> list[str]:
    """Look for a 'Skills' heading and pull comma/bullet-separated items from it."""
    lines = _section_lines(text, "skills")
    if lines is None:
        return find_skills(text)
    chunk = "\n".join(lines)

    items = re.split(r"[,\n•\-|:()]", chunk)
    cleaned = []
    for item in items:
        item = item.strip(" )(\t")
        if not item or len(item) >= 40 or len(item.split()) > 4:
            continue
        if re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", item):
            continue
        cleaned.append(item)
    return cleaned or find_skills(text)


_DATE_RANGE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}\s*[–—\-]\s*\d{1,2}/\d{1,2}/\d{2,4}")
_BARE_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
_PRESENT_RE = re.compile(r"\bpresent\b", re.IGNORECASE)


def find_projects_section(text: str) -> list[dict]:
    """Look for a 'Projects' heading and split it into {name, summary}
    entries. Résumés conventionally put a date (or "Present") next to each
    project title, so a line containing one is used purely as a block
    boundary — the date itself isn't kept, since a project isn't a
    structured experience entry with start/end fields."""
    lines = _section_lines(text, "projects")
    if not lines:
        return []

    entries: list[dict] = []
    pending_name = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        date_match = _DATE_RANGE_RE.search(line)
        is_present_line = _PRESENT_RE.search(line) is not None
        if date_match or is_present_line:
            if date_match:
                name_on_line = (line[:date_match.start()] + line[date_match.end():]).strip()
            else:
                name_on_line = _PRESENT_RE.sub("", line).strip()
            name = pending_name or name_on_line or None

            summary_lines = []
            j = i + 1
            while j < len(lines) and len(summary_lines) < 3:
                nxt = lines[j].strip()
                if not nxt or _BARE_DATE_RE.search(nxt) or _PRESENT_RE.search(nxt):
                    break
                summary_lines.append(nxt)
                j += 1

            if name:
                entries.append({"name": name, "summary": " ".join(summary_lines) or None})
            pending_name = None
            i = j
        else:
            pending_name = line
            i += 1

    return entries


_EDU_BRACKET_RE = re.compile(r"^(?P<df>.+?)\s*[-–]\s*(?P<inst>.+?)\s*\((?P<year>(?:19|20)\d{2})\)\s*$")
_EDU_TRAILING_DATE_RE = re.compile(
    r"\s*(?:\d{1,2}/)?(?:19|20)\d{2}\s*[–—\-]\s*(?:(?:\d{1,2}/)?(?:19|20)\d{2}|present)\s*$", re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_HAS_DATE_OR_PRESENT_RE = re.compile(r"(?:19|20)\d{2}|\bpresent\b", re.IGNORECASE)


def _split_degree_field(phrase: str) -> tuple[str | None, str | None]:
    phrase = phrase.strip(" -–,")
    if not phrase:
        return None, None
    m = re.search(r"^(.*?)\s+in\s+(.*)$", phrase, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return phrase, None


def find_education_section(text: str) -> list[dict]:
    """Look for an 'Education' heading and split it into {institution,
    degree, field, end_year} entries. Supports two common résumé layouts:
    a single line "<Degree> - <Institution> (<Year>)", or two lines — a
    degree/field line carrying a date (or "Present"), followed by an
    institution line. Like find_projects_section, a date is used purely as
    a block-boundary signal, not because every layout is identical."""
    lines = _section_lines(text, "education")
    if not lines:
        return []

    entries: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        m = _EDU_BRACKET_RE.match(line)
        if m:
            degree, field = _split_degree_field(m.group("df"))
            entries.append({"institution": m.group("inst").strip(), "degree": degree, "field": field,
                             "end_year": int(m.group("year"))})
            i += 1
            continue

        if _HAS_DATE_OR_PRESENT_RE.search(line):
            degree_phrase = _EDU_TRAILING_DATE_RE.sub("", line).strip()
            years = _YEAR_RE.findall(line)
            end_year = int(years[-1]) if years and "present" not in line.lower() else None
            degree, field = _split_degree_field(degree_phrase)

            institution = None
            j = i + 1
            if j < len(lines):
                nxt = lines[j].strip()
                if nxt and not _HAS_DATE_OR_PRESENT_RE.search(nxt):
                    institution = nxt
                    j += 1

            if degree or institution:
                entries.append({"institution": institution, "degree": degree, "field": field, "end_year": end_year})
            i = j
            continue

        i += 1

    return entries
