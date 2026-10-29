import logging
import random
import time
from datetime import date

from tenacity import Retrying, stop_after_attempt, wait_exponential

from ..models import Job

log = logging.getLogger(__name__)
INTERVAL = {"yearly": "year", "monthly": "month", "weekly": "week", "daily": "day", "hourly": "hour"}


def _s(v) -> str:
    """DataFrame cell -> clean string ('' for None/NaN)."""
    if v is None or v != v:
        return ""
    return str(v).strip()


def _salary(row) -> str:
    lo, hi = _s(row.get("min_amount")), _s(row.get("max_amount"))
    if not lo and not hi:
        return ""
    fmt = lambda x: f"{float(x):,.0f}" if x else ""
    amount = "–".join(x for x in (fmt(lo), fmt(hi)) if x)
    interval = INTERVAL.get(_s(row.get("interval")).lower(), "")
    return f"{amount} {_s(row.get('currency')) or 'THB'}" + (f"/{interval}" if interval else "")


class JobSpySource:
    """LinkedIn + Indeed (Thailand) through python-jobspy. Fail-soft per query."""
    name = "jobspy"

    def __init__(self, conf: dict, sleep=time.sleep):
        self.conf = conf
        self.sleep = sleep
        self.partial_failures: list[str] = []

    def _scrape(self, site: str, query: str):
        from jobspy import scrape_jobs  # imported lazily: heavy (pandas) and not needed for other sources
        c = self.conf
        kw = dict(site_name=[site], search_term=query, location=c["location"],
                  results_wanted=c["results_wanted"], country_indeed="Thailand",
                  linkedin_fetch_description=bool(c.get("fetch_description", False)), verbose=0)
        # Indeed Thailand silently returns 0 rows when hours_old is set (verified live);
        # its rows are age-filtered in fetch() instead.
        if site != "indeed":
            kw["hours_old"] = c["hours_old"]
        return scrape_jobs(**kw)

    def _scrape_with_retry(self, site: str, query: str):
        # LinkedIn answers bursts with HTTP 429: back off, retry twice, then give up on this query.
        for attempt in Retrying(stop=stop_after_attempt(3), reraise=True,
                                wait=wait_exponential(multiplier=self.conf.get("retry_wait", 20), max=120),
                                sleep=self.sleep):
            with attempt:
                return self._scrape(site, query)

    def _too_old(self, posted: str) -> bool:
        try:
            return (date.today() - date.fromisoformat(posted[:10])).days * 24 > self.conf["hours_old"]
        except ValueError:
            return False  # no usable date: keep the job

    def fetch(self) -> list[Job]:
        self.partial_failures = []
        queries, sites = self.conf["queries"], self.conf["sites"]
        lo, hi = self.conf.get("sleep_between_queries", [20, 30])
        jobs: dict[str, Job] = {}
        raw = {s: 0 for s in sites}  # rows returned before our age filter
        errors = {s: 0 for s in sites}
        for i, q in enumerate(queries):
            if i:
                self.sleep(random.uniform(lo, hi))
            for site in sites:
                try:
                    df = self._scrape_with_retry(site, q)
                except Exception as e:
                    errors[site] += 1
                    log.error("jobspy %s query %r failed: %s: %s", site, q, type(e).__name__, e)
                    continue
                raw[site] += len(df)
                for row in df.to_dict("records"):
                    url, posted = _s(row.get("job_url")), _s(row.get("date_posted"))
                    if not url or not _s(row.get("title")):
                        continue
                    if site == "indeed" and posted and self._too_old(posted):
                        continue
                    job = Job(source=site, url=url, title=_s(row.get("title")),
                              company=_s(row.get("company")), location=_s(row.get("location")),
                              salary_text=_salary(row), description=_s(row.get("description")),
                              posted_at=posted or None)
                    jobs.setdefault(job.id, job)
        if all(errors[s] == len(queries) for s in sites):
            raise RuntimeError("every jobspy query failed on every site (blocked or rate-limited?)")
        for site in sites:
            if errors[site]:
                self.partial_failures.append(f"{site} ({errors[site]}/{len(queries)} queries failed)")
            elif raw[site] == 0:
                self.partial_failures.append(f"{site} (0 results, possibly blocked)")
        return list(jobs.values())
