"""Polite HTTP client for the Thai-board adapters.

Rules (spec 5): honour robots.txt, honest User-Agent, <=1 request / 2 s per host, per-run
page cache, 20 s timeout, stop after 3 consecutive 403/429. No header spoofing, no proxies.
"""
import logging
import time
import urllib.robotparser
from urllib.parse import urlsplit

import httpx

from .sources.base import SourceBlocked

UA = "job-radar/0.1 (personal job search)"
log = logging.getLogger(__name__)


class PoliteClient:
    def __init__(self, min_interval: float = 2.0, max_blocks: int = 3, clock=time.monotonic, sleep=time.sleep, transport=None):
        self.min_interval, self.max_blocks = min_interval, max_blocks
        self._clock, self._sleep = clock, sleep
        self._client = httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True, transport=transport)
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._cache: dict[str, str] = {}
        self._blocks = 0

    def _wait(self, host: str) -> None:
        gap = self.min_interval - (self._clock() - self._last.get(host, -1e9))
        if gap > 0:
            self._sleep(gap)
        self._last[host] = self._clock()

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._wait(parts.netloc)
                r = self._client.get(f"{base}/robots.txt")
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                elif r.status_code in (401, 403):
                    rp.disallow_all = True
                else:
                    rp.allow_all = True
            except httpx.HTTPError:
                rp.allow_all = True  # no robots.txt reachable: nothing forbids us
            self._robots[base] = rp
        return self._robots[base].can_fetch(UA, url)

    def get(self, url: str) -> str:
        if url in self._cache:
            return self._cache[url]
        if not self.allowed(url):
            raise SourceBlocked(f"robots.txt disallows {url}")
        self._wait(urlsplit(url).netloc)
        r = self._client.get(url)
        if r.status_code in (403, 429):
            self._blocks += 1
            if self._blocks >= self.max_blocks:
                raise SourceBlocked(f"{self.max_blocks} consecutive {r.status_code} from {urlsplit(url).netloc}")
            raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
        self._blocks = 0
        r.raise_for_status()
        self._cache[url] = r.text
        return r.text
