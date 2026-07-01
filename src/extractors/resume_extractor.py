"""Résumé extractor: PDF (pdfplumber) / DOCX (python-docx) -> text -> heuristics.

Lossy by nature (free-form layout), so résumé-derived assertions carry a
lower source_rank than structured sources (see assertion.SOURCE_RANK).
OCR for scanned/image-based PDFs is explicitly descoped.
"""
from pathlib import Path

from ..assertion import Assertion
from . import text_heuristics as th

SRC, METHOD = "resume", "regex_extract"


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception:
            return ""
    if suffix == ".docx":
        try:
            import docx
            d = docx.Document(str(path))
            return "\n".join(p.text for p in d.paragraphs)
        except Exception:
            return ""
    if suffix == ".txt":
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
    return ""


def extract(path: str) -> list[Assertion]:
    p = Path(path)
    if not p.exists():
        return []
    text = _extract_text(p)
    if not text.strip():
        return []

    out = []
    first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")
    if first_line and len(first_line.split()) <= 5 and "@" not in first_line:
        out.append(Assertion("full_name", first_line, SRC, METHOD, raw_context=first_line))

    email = th.find_email(text)
    if email:
        out.append(Assertion("emails[]", email, SRC, METHOD))

    phone = th.find_phone(text)
    if phone:
        out.append(Assertion("phones[]", phone, SRC, METHOD))

    location = th.find_location(text)
    if location:
        out.append(Assertion("location", {"city": location, "region": None, "country": None}, SRC, METHOD))

    links = th.find_links(text)
    if links["linkedin"]:
        out.append(Assertion("links.linkedin", links["linkedin"], SRC, METHOD))
    if links["github"]:
        out.append(Assertion("links.github", links["github"], SRC, METHOD))
    for url in links["portfolio"]:
        out.append(Assertion("links.portfolio[]", url, SRC, METHOD))

    for skill in th.find_skills_section(text):
        out.append(Assertion("skills[]", skill, SRC, METHOD))

    for company, title, start, end, summary in _find_experience(text):
        out.append(Assertion(
            "experience[]",
            {"company": company, "title": title, "start": start, "end": end, "summary": summary},
            SRC, METHOD, raw_context=summary,
        ))

    for edu in th.find_education_section(text):
        out.append(Assertion("education[]", edu, SRC, METHOD))

    # Independent from experience[] — a "Projects" section entry isn't a
    # claim of employment, so a project-based résumé with no work history
    # still leaves experience[] empty rather than being forced into it.
    for project in th.find_projects_section(text):
        out.append(Assertion("projects[]", project, SRC, METHOD, raw_context=project.get("summary")))

    return out


def _find_experience(text: str):
    """Very small heuristic: lines like 'Title - Company (Start - End)'."""
    import re
    results = []
    pattern = re.compile(
        r"^(?P<title>[A-Za-z][A-Za-z /]+?)\s*[-–,]\s*(?P<company>[A-Za-z][A-Za-z .&]+?)"
        r"\s*\((?P<start>[A-Za-z0-9 ]+)\s*[-–]\s*(?P<end>[A-Za-z0-9 ]+)\)\s*$",
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        next_line_start = m.end()
        rest = text[next_line_start:next_line_start + 200].strip().splitlines()
        summary = rest[0].strip() if rest and not re.match(r"^[A-Za-z][A-Za-z /]+\s*[-–,]", rest[0]) else None
        results.append((m.group("company").strip(), m.group("title").strip(),
                         m.group("start").strip(), m.group("end").strip(), summary))
    return results
