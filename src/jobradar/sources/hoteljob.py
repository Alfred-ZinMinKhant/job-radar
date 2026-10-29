"""hoteljob.in.th adapter.

Lists come from the Bangkok-wide listing (/bangkok/?page=N, newest first), so location is
filtered by the site. Detail pages are fetched only for cards whose title matches a target
role term, to keep the request count (1 per 2 s) low. Dates are Thai Buddhist Era.
Markup verified live on 2026-10-29: <h3><a href=/position/ID/>, detail <dl><div><dt/><dd/>.
"""
import logging
import re
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser

from ..http import PoliteClient
from ..models import Job
from ..scoring import find_term
from ..utils import parse_date, parse_relative
from .base import SourceBlocked

log = logging.getLogger(__name__)
BASE = "https://www.hoteljob.in.th"
SKIP_LABELS = {"เงินเดือน", "สถานที่ทำงาน", "ลงประกาศเมื่อ", "จำนวนที่รับ", "เปิดดูแล้ว"}


@dataclass
class Card:
    id: str
    title: str
    company: str
    salary: str
    location: str
    posted_hint: str


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_list(html: str) -> list[Card]:
    tree = LexborHTMLParser(html)
    cards, seen = [], set()
    for a in tree.css("h3 a"):
        m = re.fullmatch(r"/position/(\d+)/?", a.attributes.get("href") or "")
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        card = a.parent.parent.parent  # h3 -> title column -> card grid
        names = [_clean(c.text()) for c in card.css("a") if (c.attributes.get("href") or "").startswith("/hotels/")]
        company = max(names, key=len, default="")  # the logo link only holds an initial
        ps = [_clean(p.text()) for p in card.css("p")]
        loc = card.css_first("span.truncate")
        rel = re.search(r"\d+\s*\S+(?:ที่แล้ว|ago)", card.text())
        cards.append(Card(m.group(1), _clean(a.text()), company, ps[0] if ps else "",
                          _clean(loc.text()) if loc else "", rel.group(0) if rel else ""))
    return cards


def parse_detail(html: str) -> dict:
    tree = LexborHTMLParser(html)
    h1 = tree.css_first("h1")
    title = _clean(h1.text()) if h1 else ""
    en = ""
    if h1 and h1.next is not None and h1.next.tag == "p":
        en = _clean(h1.next.text())
    fields: dict[str, str] = {}
    salary = ""
    for div in tree.css("dl > div"):
        dt, dd = div.css_first("dt"), div.css_first("dd")
        if not dt or not dd:
            continue
        label = _clean(dt.text())
        if label == "เงินเดือน":
            first = dd.css_first("span")
            salary = _clean((first or dd).text())
        fields[label] = _clean(dd.text(separator=" "))
    body = _clean(tree.body.text(separator=" ")) if tree.body else ""
    closes = re.search(r"รับสมัครถึง\s*(\d{1,2}\s+\S+\s+\d{4})", body)
    sec = next((s for s in tree.css("section") if (h2 := s.css_first("h2")) and _clean(h2.text()) == "รายละเอียดงาน"), None)
    return {"title": title, "title_en": en, "fields": fields, "salary": salary,
            "closes_text": closes.group(1) if closes else "",
            "body": sec.text(separator="\n").strip() if sec else ""}


def job_from(card: Card, detail: dict | None) -> Job:
    title = card.title
    desc, closes, salary, location = "", None, card.salary, card.location
    if detail:
        en = detail["title_en"]
        title = detail["title"] or title
        if en and en.lower() not in title.lower():
            title = f"{title} ({en})"
        salary = detail["salary"] or salary
        location = detail["fields"].get("สถานที่ทำงาน", location)
        closes = detail["closes_text"] or None
        lines = [f"{k}: {v}" for k, v in detail["fields"].items() if k not in SKIP_LABELS]
        desc = "\n".join(lines) + "\n" + detail["body"]
    posted = parse_relative(card.posted_hint)
    return Job(source="hoteljob", url=f"{BASE}/position/{card.id}/", title=title, company=card.company,
               location=location, salary_text=salary, description=desc,
               posted_at=posted.isoformat() if posted else None, closes_at=closes)


class HotelJobSource:
    name = "hoteljob"

    def __init__(self, conf: dict, target_terms: list[str], client: PoliteClient | None = None):
        self.conf, self.terms = conf, target_terms + conf.get("extra_title_terms", [])
        self.client = client or PoliteClient()
        self.partial_failures: list[str] = []

    def fetch(self) -> list[Job]:
        self.partial_failures = []
        cards: list[Card] = []
        try:
            for page in range(1, self.conf.get("max_pages", 5) + 1):
                url = f"{BASE}/bangkok/" + (f"?page={page}" if page > 1 else "")
                found = parse_list(self.client.get(url))
                if not found:
                    break
                cards += found
        except SourceBlocked as e:
            self.partial_failures.append(f"hoteljob (blocked: {e})")
            if not cards:
                raise
        if cards == []:
            raise RuntimeError("hoteljob: list page parsed to 0 jobs (markup changed?)")
        jobs, detail_errors = [], 0
        for c in cards:
            if not find_term(self.terms, c.title.lower()):
                continue
            detail = None
            try:
                detail = parse_detail(self.client.get(f"{BASE}/position/{c.id}/"))
            except SourceBlocked as e:
                self.partial_failures.append(f"hoteljob (blocked: {e})")
                jobs.append(job_from(c, None))
                break
            except Exception as e:
                detail_errors += 1
                log.warning("hoteljob detail %s failed: %s", c.id, type(e).__name__)
            jobs.append(job_from(c, detail))
        if detail_errors:
            self.partial_failures.append(f"hoteljob ({detail_errors} detail pages failed)")
        log.info("hoteljob: %d cards, %d matched title filter", len(cards), len(jobs))
        return jobs
