import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db, notify
from .scoring import apply_score
from .sources import build_sources
from .utils import now_iso

log = logging.getLogger(__name__)


def run(cfg: dict, dry_run: bool = False, only: str | None = None, no_notify: bool = False) -> str:
    """One full pass. Returns the text that was (or would be) sent, for printing."""
    ts = now_iso()
    conn = db.connect(Path(cfg["_root"]) / "data" / "jobs.db", in_memory_copy=dry_run)
    ncfg = cfg["notify"]
    scanned, failed = 0, []

    for src in build_sources(cfg, only):
        try:
            jobs = src.fetch()
        except Exception as e:  # fail soft: one broken source never kills the run
            log.error("source %s failed: %s: %s", src.name, type(e).__name__, e)
            failed.append(src.name)
            db.record_run(conn, src.name, False, 0, f"{type(e).__name__}: {e}"[:500], ts)
            continue
        for job in jobs:
            apply_score(job, cfg)
            db.upsert_job(conn, job, ts)
        scanned += len(jobs)
        failed.extend(getattr(src, "partial_failures", []))
        db.record_run(conn, src.name, True, len(jobs), None, ts)
        db.mark_expired(conn, src.name)

    pending = db.pending_notifications(conn, ncfg["min_score"], ncfg["top_n"])
    tries = []
    if ncfg["worth_a_try"]["enabled"]:
        tries = db.pending_worth_a_try(conn, ncfg["worth_a_try"]["min_score"],
                                       ncfg["min_score"], ncfg["worth_a_try"]["max"])
    messages: list[str] = []
    if pending or tries:
        messages = notify.build_digest(pending, scanned, failed, tries)
    else:
        last = db.get_meta(conn, "last_quiet_ping")
        due = not last or datetime.fromisoformat(last) < datetime.now(timezone.utc) - timedelta(days=ncfg["quiet_ping_days"])
        if failed or due:
            note = "all quiet" if not failed else "no new matches"
            messages = [f"🔎 job-radar: {note}\n{notify.footer(0, scanned, failed)}"]
            if due and not dry_run:
                db.set_meta(conn, "last_quiet_ping", ts)

    if messages and not dry_run and not no_notify:
        notify.send_all(messages)
        db.mark_notified(conn, ncfg["min_score"])
        db.mark_ids_notified(conn, [j.id for j in tries])
    if not dry_run:
        conn.commit()
    conn.close()
    return "\n\n-----\n\n".join(messages) if messages else "(nothing to send)"
