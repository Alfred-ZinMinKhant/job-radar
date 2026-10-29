from typing import Protocol

from ..models import Job


class SourceBlocked(Exception):
    """Site refused us (403/429 x3, robots.txt). Stop that source; never work around it."""


class Source(Protocol):
    name: str

    def fetch(self) -> list[Job]: ...
