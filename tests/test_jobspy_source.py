import pandas as pd
import pytest

from jobradar.sources.jobspy_source import JobSpySource

CONF = {"sites": ["linkedin", "indeed"], "location": "Bangkok, Thailand", "results_wanted": 5,
        "hours_old": 72, "queries": ["a", "b"], "sleep_between_queries": [0, 0], "retry_wait": 0}


def df(rows):
    return pd.DataFrame(rows)


ROW = dict(site="indeed", job_url="https://th.indeed.com/viewjob?jk=1&utm_source=x", title="Receptionist",
           company="Hotel", location="Bangkok, TH", description="desc", min_amount=15000.0,
           max_amount=20000.0, interval="monthly", currency="THB", date_posted=None)


def make(responses):
    src = JobSpySource(CONF, sleep=lambda s: None)
    it = iter(responses)

    def fake(site, q):
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r
    src._scrape = fake
    return src


def L(**kw):
    return {**ROW, "site": "linkedin", "job_url": "https://linkedin.com/jobs/view/9", **kw}


def test_maps_rows_and_dedupes():
    # 2 queries x 2 sites = 4 calls in order: li/q1, in/q1, li/q2, in/q2
    src = make([df([L()]), df([ROW]), df([L()]), df([ROW])])
    jobs = src.fetch()
    assert len(jobs) == 2
    j = next(x for x in jobs if x.source == "indeed")
    assert j.salary_text == "15,000–20,000 THB/month" and j.company == "Hotel"
    assert src.partial_failures == []


def test_query_retried_then_succeeds():
    src = make([RuntimeError("429"), df([L()]), df([ROW]), df([L()]), df([ROW])])
    assert len(src.fetch()) == 2 and src.partial_failures == []


def test_site_with_zero_results_is_named():
    src = make([df([L()]), df([]), df([L()]), df([])])
    src.fetch()
    assert any(f.startswith("indeed") for f in src.partial_failures)


def test_one_site_failing_is_named_and_other_kept():
    err = RuntimeError("blocked")
    src = make([err, err, err, df([ROW]), err, err, err, df([ROW])])
    jobs = src.fetch()
    assert [j.source for j in jobs] == ["indeed"]
    assert "linkedin (2/2 queries failed)" in src.partial_failures


def test_everything_failing_raises():
    src = make([RuntimeError("x")] * 12)
    with pytest.raises(RuntimeError):
        src.fetch()


def test_old_indeed_rows_filtered():
    src = make([df([L()]), df([{**ROW, "date_posted": "2020-01-01"}]), df([L()]), df([{**ROW, "date_posted": "2020-01-01"}])])
    assert [j.source for j in src.fetch()] == ["linkedin"]


def test_stale_only_site_is_not_reported_as_blocked():
    old = {**ROW, "date_posted": "2020-01-01"}
    src = make([df([L()]), df([old]), df([L()]), df([old])])
    src.fetch()
    assert src.partial_failures == []
