import httpx
import pytest

from jobradar.http import UA, PoliteClient
from jobradar.sources.base import SourceBlocked


def client(handler, **kw):
    t = [0.0]
    slept = []
    c = PoliteClient(transport=httpx.MockTransport(handler), clock=lambda: t[0],
                     sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)), **kw)
    return c, slept


def test_robots_disallow_is_respected_and_not_fetched():
    seen = []

    def h(req):
        seen.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/")
        return httpx.Response(200, text="ok")

    c, _ = client(h)
    with pytest.raises(SourceBlocked):
        c.get("https://x.test/private/a")
    assert "/private/a" not in seen
    assert c.get("https://x.test/public/a") == "ok"


def test_honest_user_agent_and_cache():
    uas, calls = [], []

    def h(req):
        uas.append(req.headers["user-agent"])
        calls.append(req.url.path)
        return httpx.Response(404 if req.url.path == "/robots.txt" else 200, text="ok")

    c, _ = client(h)
    c.get("https://x.test/a")
    c.get("https://x.test/a")
    assert set(uas) == {UA} and calls.count("/a") == 1


def test_two_seconds_between_requests_to_one_host():
    c, slept = client(lambda r: httpx.Response(404 if r.url.path == "/robots.txt" else 200, text="ok"))
    c.get("https://x.test/a")
    c.get("https://x.test/b")
    assert slept and all(abs(s - 2.0) < 1e-6 or s < 2.0 for s in slept) and sum(slept) >= 4.0 - 1e-6


def test_stops_after_three_consecutive_429():
    n = []

    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        n.append(1)
        return httpx.Response(429)

    c, _ = client(h)
    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            c.get(f"https://x.test/{len(n)}")
    with pytest.raises(SourceBlocked):
        c.get("https://x.test/3")
    assert len(n) == 3


def test_success_resets_block_counter():
    codes = iter([429, 429, 200, 429, 429])

    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(next(codes), text="ok")

    c, _ = client(h)
    for i in range(5):
        try:
            c.get(f"https://x.test/{i}")
        except httpx.HTTPStatusError:
            pass  # never reaches 3 in a row
