from pathlib import Path

from .base import Source


def build_sources(cfg: dict, only: str | None = None) -> list[Source]:
    """Instantiate enabled sources (or just `only`). Later phases register more here."""
    root = Path(cfg["_root"])
    registry = {}

    def fixtures():
        from .fixtures import FixtureSource
        return FixtureSource(root / cfg["sources"]["fixtures"]["path"])
    registry["fixtures"] = fixtures

    def jobspy():
        from .jobspy_source import JobSpySource
        return JobSpySource(cfg["jobspy"])
    registry["jobspy"] = jobspy

    def hoteljob():
        from .hoteljob import HotelJobSource
        return HotelJobSource(cfg["hoteljob"], cfg["scoring"]["target_role"]["terms"])
    registry["hoteljob"] = hoteljob

    def _terms():
        return cfg["scoring"]["target_role"]["terms"] + cfg["scoring"]["burmese"]["terms"]

    def jobbkk():
        from .jobbkk import JobBKKSource
        return JobBKKSource(cfg["jobbkk"], _terms())
    registry["jobbkk"] = jobbkk

    def jobthai():
        from .jobthai import JobThaiSource
        return JobThaiSource(cfg["jobthai"], _terms())
    registry["jobthai"] = jobthai

    def careerlink():
        from .careerlink import CareerLinkSource
        if not cfg["careerlink"].get("search_urls"):
            raise SystemExit("careerlink: add search_urls to config.yaml (see README) or remove it from sources.enabled")
        return CareerLinkSource(cfg["careerlink"])
    registry["careerlink"] = careerlink

    names = [only] if only else cfg["sources"]["enabled"]
    unknown = [n for n in names if n not in registry]
    if unknown:
        raise SystemExit(f"unknown source(s): {', '.join(unknown)}. known: {', '.join(registry)}")
    return [registry[n]() for n in names]
