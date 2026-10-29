import json
from pathlib import Path

from ..models import Job


class FixtureSource:
    """Reads synthetic jobs from a JSON file. Used for dry-runs and tests."""
    name = "fixtures"

    def __init__(self, path: Path):
        self.path = path

    def fetch(self) -> list[Job]:
        return [Job(source=self.name, **d) for d in json.loads(self.path.read_text(encoding="utf-8"))]
