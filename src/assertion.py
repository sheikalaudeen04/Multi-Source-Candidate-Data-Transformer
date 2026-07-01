"""The Assertion object: every value pulled from a source is recorded here first.

Conceptually each Assertion is an edge from a source to a claimed field value;
candidate-identity is the implicit shared node they get grouped under later
(see identity.py). No literal graph structure is needed for that.
"""
from dataclasses import dataclass, field
from typing import Any, Optional

# Lower rank = more trusted, used only as a tie-breaker (see resolve.py).
# LinkedIn and the GitHub API integration were both deliberately removed
# (LinkedIn: real API requires paid/licensed access and scraping violates
# its ToS; GitHub API: unused in practice) and have no source rank here. A
# résumé that itself lists a github.com URL still works fine — that's plain
# text extraction tagged source="resume", not this removed API integration.
SOURCE_RANK = {
    "ats_json": 1,
    "recruiter_csv": 2,
    "resume": 3,
    "notes": 4,
}


@dataclass(frozen=True)
class Assertion:
    field: str                          # canonical field path, e.g. "experience[].title"
    value: Any                          # raw or normalized value
    source: str                         # e.g. "ats_json", "resume", "recruiter_csv"
    method: str                         # e.g. "direct_field", "regex_extract", "api_fetch"
    raw_context: Optional[str] = None   # snippet for debugging
    structural_richness: float = 0.0    # 0-1, filled in by normalize.py
    source_rank: int = field(default=99)

    def __post_init__(self):
        if self.source_rank == 99:
            object.__setattr__(self, "source_rank", SOURCE_RANK.get(self.source, 99))
