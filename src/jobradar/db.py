import json
import sqlite3
from pathlib import Path

from .models import Job
from .utils import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, source TEXT, url TEXT, title TEXT, company TEXT, location TEXT,
  salary_text TEXT, description TEXT, posted_at TEXT, closes_at TEXT,
  first_seen_at TEXT, last_seen_at TEXT, score INTEGER, reasons TEXT, degree_flag TEXT,
  notified INTEGER DEFAULT 0, expired INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, source TEXT, ok INTEGER,
  fetched INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: str | Path, in_memory_copy: bool = False) -> sqlite3.Connection:
    """in_memory_copy: work on a throwaway copy (dry-run); nothing touches the file."""
    path = Path(path)
    if in_memory_copy:
        mem = sqlite3.connect(":memory:")
        if path.exists():
            src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            src.backup(mem)
            src.close()
        conn = mem
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_job(conn: sqlite3.Connection, job: Job, ts: str | None = None) -> None:
    ts = ts or now_iso()
    conn.execute(
        """INSERT INTO jobs(id,source,url,title,company,location,salary_text,description,
             posted_at,closes_at,first_seen_at,last_seen_at,score,reasons,degree_flag)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             title=excluded.title, company=excluded.company, location=excluded.location,
             salary_text=excluded.salary_text, description=excluded.description,
             posted_at=excluded.posted_at, closes_at=excluded.closes_at,
             last_seen_at=excluded.last_seen_at, score=excluded.score,
             reasons=excluded.reasons, degree_flag=excluded.degree_flag, expired=0""",
        (job.id, job.source, job.url, job.title, job.company, job.location, job.salary_text,
         job.description, job.posted_at, job.closes_at, ts, ts,
         -999 if job.excluded else job.score, json.dumps(job.reasons, ensure_ascii=False),
         job.degree_flag))


def pending_notifications(conn: sqlite3.Connection, min_score: int, limit: int) -> list[Job]:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE notified=0 AND expired=0 AND score>=? "
        "ORDER BY score DESC, first_seen_at LIMIT ?", (min_score, limit)).fetchall()
    return [_row_to_job(r) for r in rows]


def _row_to_job(r: sqlite3.Row) -> Job:
    return Job(source=r["source"], url=r["url"], title=r["title"], company=r["company"] or "",
               location=r["location"] or "", salary_text=r["salary_text"] or "",
               description=r["description"] or "", posted_at=r["posted_at"],
               closes_at=r["closes_at"], score=r["score"],
               reasons=json.loads(r["reasons"] or "[]"), degree_flag=r["degree_flag"])


def pending_worth_a_try(conn: sqlite3.Connection, floor: int, below: int, limit: int) -> list[Job]:
    """Un-notified jobs under the main threshold whose role/language fits but which lost
    points only for degree/experience (no nationality or seniority problem)."""
    rows = conn.execute("SELECT * FROM jobs WHERE notified=0 AND expired=0 AND score>=? AND score<? "
                        "ORDER BY score DESC, first_seen_at", (floor, below)).fetchall()
    out = []
    for j in map(_row_to_job, rows):
        r = " | ".join(j.reasons)
        fits = "title:" in r or "burmese wanted" in r
        held_back = "degree required" in r or "experience" in r
        blocked = "nationality" in r or "seniority" in r
        if fits and held_back and not blocked:
            out.append(j)
    return out[:limit]


def mark_ids_notified(conn: sqlite3.Connection, ids: list[str]) -> None:
    conn.executemany("UPDATE jobs SET notified=1 WHERE id=?", [(i,) for i in ids])


def mark_notified(conn: sqlite3.Connection, min_score: int) -> None:
    """Mark every un-notified job at/above min_score, including ones past top_n, so
    the next digest does not resurrect yesterday's overflow."""
    conn.execute("UPDATE jobs SET notified=1 WHERE notified=0 AND score>=?", (min_score,))


def record_run(conn, source: str, ok: bool, fetched: int, error: str | None, ts: str) -> None:
    conn.execute("INSERT INTO runs(started_at,source,ok,fetched,error) VALUES(?,?,?,?,?)",
                 (ts, source, int(ok), fetched, error))


def mark_expired(conn: sqlite3.Connection, source: str, misses: int = 3) -> int:
    """Expire jobs unseen in the last `misses` successful runs of this source."""
    rows = conn.execute("SELECT started_at FROM runs WHERE source=? AND ok=1 "
                        "ORDER BY started_at DESC LIMIT ?", (source, misses)).fetchall()
    if len(rows) < misses:
        return 0
    cutoff = rows[-1]["started_at"]
    cur = conn.execute("UPDATE jobs SET expired=1 WHERE source=? AND expired=0 AND last_seen_at<?",
                       (source, cutoff))
    return cur.rowcount


def get_meta(conn, key: str) -> str | None:
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
