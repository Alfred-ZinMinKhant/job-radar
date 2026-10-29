"""jobtopgun.com adapter. Checked live 2026-10-29: the keyword search and /api/ are client-side
(and /api/ is disallowed in robots.txt), so we read the server-rendered field pages instead,
/th/jobs/jobs-in-<field>?page=N (30 jobs per page). Job pages are /th/jobs/j<company>-<job>
and carry plain JSON-LD."""
import logging
import re

from selectolax.lexbor import LexborHTMLParser

from ..http import PoliteClient
from ..models import Job
from ..scoring import find_term
from .base import SourceBlocked
from .jsonld import find_jobposting, posting_fields

log = logging.getLogger(__name__)
BASE = "https://www.jobtopgun.com"
BANGKOK = "กรุงเทพมหานคร"
_JOB_HREF = re.compile(r"^/th/jobs/(j\d+-\d+)$")


def list_url(field: str, page: int) -> str:
    return f"{BASE}/th/jobs/jobs-in-{field}" + (f"?page={page}" if page > 1 else "")


def parse_list(html: str) -> list[dict]:
    """One dict per job card: id, title, bangkok (does the card text name Bangkok)."""
    tree = LexborHTMLParser(html)
    anchors = {}
    for a in tree.css("a"):
        m = _JOB_HREF.match(a.attributes.get("href") or "")
        if m:
            anchors.setdefault(m.group(1), []).append(a)
    items = []
    for jid, links in anchors.items():
        title = next((a.text(strip=True) for a in links if a.text(strip=True)), "")
        card = links[0]  # climb to the card: the widest ancestor that still holds only this job
        while card.parent is not None and len({m.group(1) for a in card.parent.css("a")
                                               if (m := _JOB_HREF.match(a.attributes.get("href") or ""))}) <= 1:
            card = card.parent
        items.append({"id": jid, "title": title, "bangkok": BANGKOK in card.text(separator=" ")})
    if not items:
        raise ValueError("no job cards on jobtopgun list page")
    return items


def job_from(item: dict, detail_html: str | None) -> Job:
    f = posting_fields(find_jobposting(detail_html) or {}) if detail_html else {}
    where = " · ".join(x for x in (f.get("region"), f.get("locality")) if x) or (BANGKOK if item["bangkok"] else "")
    return Job(source="jobtopgun", url=f"{BASE}/th/jobs/{item['id']}", title=f.get("title") or item["title"],
               company=f.get("company", ""), location=where,
               salary_text=f.get("salary", ""), description=f.get("description", ""),
               posted_at=f.get("posted"), closes_at=f.get("closes"))


class JobTopGunSource:
    name = "jobtopgun"

    def __init__(self, conf: dict, terms: list[str], client: PoliteClient | None = None):
        self.conf, self.terms = conf, terms
        self.client = client or PoliteClient()
        self.partial_failures: list[str] = []

    def fetch(self) -> list[Job]:
        self.partial_failures, jobs, seen = [], [], set()
        listed = errors = 0
        try:
            for field in self.conf["fields"]:
                for page in range(1, self.conf.get("max_pages", 3) + 1):
                    try:
                        items = parse_list(self.client.get(list_url(field, page)))
                    except ValueError:
                        if page == 1:
                            raise  # an empty first page means the markup changed
                        break  # past the field's last page
                    listed += len(items)
                    for it in items:
                        if it["id"] in seen or not it["bangkok"] or not find_term(self.terms, it["title"].lower()):
                            continue
                        seen.add(it["id"])
                        html = None
                        try:
                            html = self.client.get(f"{BASE}/th/jobs/{it['id']}")
                        except SourceBlocked:
                            raise
                        except Exception as e:
                            errors += 1
                            log.warning("jobtopgun detail %s failed: %s", it["id"], type(e).__name__)
                        job = job_from(it, html)
                        region = (posting_fields(find_jobposting(html) or {}) if html else {}).get("region")
                        if region and region != "Bangkok":  # the card text can mention Bangkok for other provinces
                            continue
                        jobs.append(job)
        except SourceBlocked as e:
            self.partial_failures.append(f"jobtopgun (blocked: {e})")
            if not jobs:
                raise
        if listed == 0:
            raise RuntimeError("jobtopgun: field pages parsed to 0 jobs (markup changed?)")
        if errors:
            self.partial_failures.append(f"jobtopgun ({errors} detail pages failed)")
        return jobs
