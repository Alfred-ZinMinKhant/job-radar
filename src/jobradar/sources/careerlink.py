"""careerlink.co.th adapter.

NOT verified against the live site: CareerLink's robots.txt blocks Claude's crawlers, so this was
built without browsing it. Job links follow /en/job/<slug>/<id> (per the spec); detail parsing
prefers schema.org JSON-LD and falls back to the page's visible text, which the scoring regexes
can read either way. You supply the search URLs (copy them from your own browser after
filtering to Bangkok and a keyword) in config.yaml -> careerlink.search_urls.
"""
import logging
import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from ..http import PoliteClient
from ..models import Job
from ..utils import canonical_url, parse_date
from .base import SourceBlocked
from .jsonld import find_jobposting, posting_fields

log = logging.getLogger(__name__)
BASE = "https://www.careerlink.co.th"
LINK = re.compile(r"^(?:/en)?/job/[^/?#]+/\d+")


def parse_list(html: str, base: str = BASE) -> list[str]:
    seen, out = set(), []
    for a in LexborHTMLParser(html).css("a"):
        href = a.attributes.get("href") or ""
        path = re.sub(r"^https?://[^/]+", "", href)
        if LINK.match(path):
            url = canonical_url(urljoin(base, path))
            if url not in seen:
                seen.add(url)
                out.append(url)
    return out


def job_from_html(url: str, html: str) -> Job:
    jp = find_jobposting(html)
    if jp:
        f = posting_fields(jp)
        return Job(source="careerlink", url=url, title=f["title"], company=f["company"],
                   location=f["locality"] or f["region"], salary_text=f["salary"],
                   description=f["description"], posted_at=f["posted"], closes_at=f["closes"])
    tree = LexborHTMLParser(html)
    for n in tree.css("script,style,svg,nav,header,footer"):
        n.decompose()
    h1 = tree.css_first("h1")
    text = re.sub(r"\n\s*\n+", "\n", tree.body.text(separator="\n")) if tree.body else ""
    m = re.search(r"closing date\W*(\d{1,2}\s+\w+\.?\s+\d{4})", text, re.I)
    return Job(source="careerlink", url=url, title=h1.text().strip() if h1 else "",
               description=text, closes_at=m.group(1) if m else None)


class CareerLinkSource:
    name = "careerlink"

    def __init__(self, conf: dict, client: PoliteClient | None = None):
        self.conf = conf
        self.client = client or PoliteClient()
        self.partial_failures: list[str] = []

    def fetch(self) -> list[Job]:
        self.partial_failures, jobs, errors = [], [], 0
        urls: list[str] = []
        try:
            for su in self.conf["search_urls"]:
                urls += [u for u in parse_list(self.client.get(su)) if u not in urls]
            if not urls:
                raise RuntimeError("careerlink: search pages contained no job links (markup changed?)")
            for u in urls[: self.conf.get("max_jobs", 40)]:
                try:
                    job = job_from_html(u, self.client.get(u))
                except SourceBlocked:
                    raise
                except Exception as e:
                    errors += 1
                    log.warning("careerlink detail failed: %s", type(e).__name__)
                    continue
                if job.title:
                    jobs.append(job)
        except SourceBlocked as e:
            self.partial_failures.append(f"careerlink (blocked: {e})")
            if not jobs:
                raise
        if errors:
            self.partial_failures.append(f"careerlink ({errors} detail pages failed)")
        return jobs
