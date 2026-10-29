"""jobbkk.com adapter. Verified live 2026-10-29: Bangkok list URL pattern
/jobs/lists/<page>/หางาน,<keyword>,กรุงเทพมหานคร,ทั้งหมด.html, job links /jobs/detail[urgent]/<emp>/<job>,
detail pages carry JSON-LD JobPosting plus labelled education/experience lines."""
import logging
import re
from urllib.parse import quote

from selectolax.lexbor import LexborHTMLParser

from ..http import PoliteClient
from ..models import Job
from ..scoring import find_term
from .base import SourceBlocked
from .jsonld import find_jobposting, posting_fields

log = logging.getLogger(__name__)
BASE = "https://www.jobbkk.com"
LINK = re.compile(r"/jobs/detail(?:urgent)?/(\d+)/(\d+)")


def list_url(keyword: str, page: int) -> str:
    return BASE + quote(f"/jobs/lists/{page}/หางาน,{keyword},กรุงเทพมหานคร,ทั้งหมด.html", safe="/,.")


def parse_list(html: str) -> list[tuple[str, str, str]]:
    """-> [(job_id, path, anchor_text)] unique by job id."""
    out, seen = [], set()
    for a in LexborHTMLParser(html).css("a"):
        m = LINK.search(a.attributes.get("href") or "")
        if m and m.group(2) not in seen:
            seen.add(m.group(2))
            out.append((m.group(2), m.group(0), re.sub(r"\s+", " ", a.text(separator=" ")).strip()))
    return out


def qualification_lines(html: str) -> str:
    """'label \\n : \\n value' pairs from the คุณสมบัติ section -> 'label: value' lines."""
    tree = LexborHTMLParser(html)
    for n in tree.css("script,style,svg"):
        n.decompose()
    txt = re.sub(r"\s*\n\s*:\s*\n\s*", ": ", tree.body.text(separator="\n")) if tree.body else ""
    txt = re.sub(r"\n\s*\n+", "\n", txt)
    a = txt.find("คุณสมบัติ\n")
    b = txt.find("สวัสดิการ", a if a >= 0 else 0)
    return txt[a:b].strip() if a >= 0 and b > a else ""


def job_from_detail(path: str, html: str) -> Job | None:
    jp = find_jobposting(html)
    if not jp:
        return None
    f = posting_fields(jp)
    if f["region"] and "กรุงเทพ" not in f["region"]:
        return None
    return Job(source="jobbkk", url=BASE + path, title=f["title"], company=f["company"],
               location=" ".join(x for x in (f["locality"], f["region"]) if x), salary_text=f["salary"],
               description=f"{qualification_lines(html)}\n{f['description']}", posted_at=f["posted"],
               closes_at=f["closes"])


class JobBKKSource:
    name = "jobbkk"

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
                    cards = parse_list(self.client.get(list_url(kw, page)))
                    listed += len(cards)
                    for jid, path, text in cards:
                        if jid in seen or not find_term(self.terms, text.lower()):
                            continue
                        seen.add(jid)
                        try:
                            job = job_from_detail(path, self.client.get(BASE + path))
                        except SourceBlocked:
                            raise
                        except Exception as e:
                            errors += 1
                            log.warning("jobbkk detail %s failed: %s", jid, type(e).__name__)
                            continue
                        if job:
                            jobs.append(job)
        except SourceBlocked as e:
            self.partial_failures.append(f"jobbkk (blocked: {e})")
            if not jobs:
                raise
        if listed == 0:
            raise RuntimeError("jobbkk: list pages parsed to 0 jobs (markup changed?)")
        if errors:
            self.partial_failures.append(f"jobbkk ({errors} detail pages failed)")
        return jobs
