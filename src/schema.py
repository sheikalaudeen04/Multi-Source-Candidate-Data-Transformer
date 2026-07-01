"""Internal canonical schema (fixed). The projector reshapes this for output."""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Location:
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None  # ISO 3166 alpha-2


@dataclass
class Links:
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: list = field(default_factory=list)


@dataclass
class Skill:
    name: str
    confidence: float
    sources: list


@dataclass
class Experience:
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class Education:
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None


@dataclass
class Project:
    """Independent from Experience — a project (e.g. from a résumé's
    "Projects" section) is not a claim of employment, so it's never folded
    into experience[]. A candidate can have projects with no work
    experience at all (e.g. a student résumé), or vice versa."""
    name: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class ProvenanceEntry:
    field: str
    source: str
    method: str


@dataclass
class CandidateProfile:
    candidate_id: str
    full_name: Optional[str] = None
    emails: list = field(default_factory=list)
    phones: list = field(default_factory=list)
    location: Location = field(default_factory=Location)
    links: Links = field(default_factory=Links)
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: list = field(default_factory=list)        # list[Skill]
    experience: list = field(default_factory=list)     # list[Experience]
    education: list = field(default_factory=list)      # list[Education]
    projects: list = field(default_factory=list)        # list[Project]
    provenance: list = field(default_factory=list)      # list[ProvenanceEntry]
    overall_confidence: float = 0.0
    field_confidence: dict = field(default_factory=dict)  # internal only, used by projector

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("field_confidence", None)
        return d
