"""jobthai.com adapter. Verified live 2026-10-29: the search page is server-rendered and embeds
its results as Apollo state in __NEXT_DATA__ (ROOT_QUERY.searchJobs(...).data.data); Bangkok is
province id '01'; job pages are /th/company/job/<id> and carry JSON-LD (inside a Next.js push)."""
import json
import logging
import re
from urllib.parse import quote

from ..http import PoliteClient
from ..models import Job
from ..scoring import find_term
from .base import SourceBlocked
from .jsonld import find_jobposting, posting_fields

log = logging.getLogger(__name__)
BASE = "https://www.jobthai.com"
BANGKOK_ID = "01"
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def list_url(keyword: str, page: int) -> str:
    return f"{BASE}/th/jobs?keyword={quote(keyword)}&province={BANGKOK_ID}&orderBy=RELEVANCE_SEARCH&page={page}"


def parse_list(html: str) -> list[dict]:
    m = _NEXT.search(html)
    if not m:
        raise ValueError("no __NEXT_DATA__ on jobthai list page")
    root = json.loads(m.group(1))["props"]["apolloState"]["ROOT_QUERY"]
    key = next((k for k in root if k.startswith("searchJobs")), None)
    if key is None:
        raise ValueError("no searchJobs in jobthai Apollo state")
    return root[key]["data"]["data"]


def job_from(item: dict, detail_html: str | None) -> Job:
    f = posting_fields(find_jobposting(detail_html) or {}) if detail_html else {}
    province, district = item["province"]["name"] or "", (item.get("district") or {}).get("name") or ""
    return Job(source="jobthai", url=f"{BASE}/th/company/job/{item['id']}",
               title=f.get("title") or item["jobTitle"], company=item["companyName"] or "",
               location=" · ".join(x for x in (province, district) if x),
               salary_text=item.get("salary") or f.get("salary", ""), description=f.get("description", ""),
               posted_at=(item.get("updatedAt") or "")[:10] or None, closes_at=f.get("closes"))


class JobThaiSource:
    name = "jobthai"

    def __init__(self, conf: dict, terms: list[str], client: PoliteClient | None = None):
        self.conf, self.terms = conf, terms
        self.client = client or PoliteClient()
        self.partial_failures: list[str] = []

    def fetch(self) -> list[Job]:
        self.partial_failures, jobs, seen = [], [], set()
        listed = errors = 0
        try:
            for kw in self.conf["keywords"]:
                for page in range(1, self.conf.get("max_pages", 1) + 1):
                    items = parse_list(self.client.get(list_url(kw, page)))
                    listed += len(items)
                    for it in items:  # the province filter is also enforced here, not just in the URL
                        if it["id"] in seen or (it["province"] or {}).get("id") != BANGKOK_ID:
                            continue
                        if not find_term(self.terms, (it["jobTitle"] or "").lower()):
                            continue
                        seen.add(it["id"])
                        html = None
                        try:
                            html = self.client.get(f"{BASE}/th/company/job/{it['id']}")
                        except SourceBlocked:
                            raise
                        except Exception as e:
                            errors += 1
                            log.warning("jobthai detail %s failed: %s", it["id"], type(e).__name__)
                        jobs.append(job_from(it, html))
        except SourceBlocked as e:
            self.partial_failures.append(f"jobthai (blocked: {e})")
            if not jobs:
                raise
        if listed == 0:
            raise RuntimeError("jobthai: search parsed to 0 jobs (markup changed?)")
        if errors:
            self.partial_failures.append(f"jobthai ({errors} detail pages failed)")
        return jobs
