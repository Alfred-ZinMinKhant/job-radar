from datetime import datetime, timedelta, timezone

from jobradar import db
from jobradar.models import Job
from jobradar.utils import canonical_url, job_id, parse_date


def mk(url="https://x.test/a", score=50):
    return Job("s", url, "T", score=score)


def test_canonical_url_strips_tracking_and_fragment():
    assert canonical_url("https://X.test/a?utm_source=z&id=1#frag") == "https://x.test/a?id=1"
    assert job_id("s", "https://x.test/a?utm_x=1") == job_id("s", "https://x.test/a")


def test_buddhist_date():
    assert str(parse_date("28 November 2569")) == "2026-11-28"
    assert str(parse_date("2026-11-28")) == "2026-11-28"


def test_dedupe_and_notified(tmp_path):
    c = db.connect(tmp_path / "j.db")
    db.upsert_job(c, mk(), "2026-01-01T00:00:00")
    assert len(db.pending_notifications(c, 30, 25)) == 1
    db.mark_notified(c, 30)
    db.upsert_job(c, mk(), "2026-01-02T00:00:00")  # seen again
    assert db.pending_notifications(c, 30, 25) == []
    row = c.execute("SELECT first_seen_at,last_seen_at FROM jobs").fetchone()
    assert row[0] == "2026-01-01T00:00:00" and row[1] == "2026-01-02T00:00:00"


def test_min_score_filter(tmp_path):
    c = db.connect(tmp_path / "j.db")
    db.upsert_job(c, mk(score=10))
    assert db.pending_notifications(c, 30, 25) == []


def test_expire_after_three_missed_runs(tmp_path):
    c = db.connect(tmp_path / "j.db")
    db.upsert_job(c, mk(), "2026-01-01T00:00:00")
    for d in (1, 2, 3):
        db.record_run(c, "s", True, 0, None, f"2026-01-0{d + 1}T00:00:00")
    assert db.mark_expired(c, "s") == 1


def test_failed_runs_do_not_expire(tmp_path):
    c = db.connect(tmp_path / "j.db")
    db.upsert_job(c, mk(), "2026-01-01T00:00:00")
    for d in (1, 2, 3):
        db.record_run(c, "s", False, 0, "boom", f"2026-01-0{d + 1}T00:00:00")
    assert db.mark_expired(c, "s") == 0


def test_dry_run_copy_does_not_write(tmp_path):
    p = tmp_path / "j.db"
    db.connect(p).close()
    c = db.connect(p, in_memory_copy=True)
    db.upsert_job(c, mk())
    c.close()
    assert db.connect(p).execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_worth_a_try_selection(tmp_path):
    c = db.connect(tmp_path / "j.db")
    good = Job("s", "https://x.test/1", "Receptionist", score=0,
               reasons=["+30 title: receptionist", "-40 degree required: bachelor", "+10 entry level"])
    senior = Job("s", "https://x.test/2", "Receptionist Manager", score=0,
                 reasons=["+30 title: receptionist", "-50 seniority in title: manager", "-40 degree required"])
    nat = Job("s", "https://x.test/3", "Sales", score=0, reasons=["-100 nationality: x", "+25 burmese wanted", "-30 experience 3+ years"])
    for j in (good, senior, nat):
        db.upsert_job(c, j)
    got = db.pending_worth_a_try(c, 0, 30, 5)
    assert [j.url for j in got] == ["https://x.test/1"]
