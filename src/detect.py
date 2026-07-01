"""Source-type detection (pipeline stage 1) — picks the extractor for a file path."""
from pathlib import Path


def detect_file_source(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return "recruiter_csv"
    if suffix == ".json":
        return "ats_json"
    if suffix in (".pdf", ".docx"):
        return "resume"
    if suffix == ".txt":
        return "notes"
    return None
