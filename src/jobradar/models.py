from dataclasses import dataclass, field

from .utils import job_id


@dataclass
class Job:
    source: str
    url: str
    title: str
    company: str = ""
    location: str = ""
    salary_text: str = ""
    description: str = ""
    posted_at: str | None = None
    closes_at: str | None = None   # ISO date or a raw string parse_date understands
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    degree_flag: str = "none_mentioned"
    excluded: bool = False

    @property
    def id(self) -> str:
        return job_id(self.source, self.url)
