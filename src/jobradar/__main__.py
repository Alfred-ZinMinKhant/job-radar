import argparse
import logging
import sys
from pathlib import Path

from . import db, notify, runner
from .config import load_config


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="jobradar")
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true", help="print digest, write nothing")
    r.add_argument("--source", metavar="NAME")
    r.add_argument("--no-notify", action="store_true")
    sub.add_parser("sources")
    sub.add_parser("stats")
    sub.add_parser("notify-test")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines print the bot token URL
    cfg = load_config(args.config)
    dbpath = Path(cfg["_root"]) / "data" / "jobs.db"

    if args.cmd == "run":
        print(runner.run(cfg, args.dry_run, args.source, args.no_notify))
    elif args.cmd == "notify-test":
        notify.send("job-radar: test message ✅")
        print("sent")
    elif args.cmd == "sources":
        conn = db.connect(dbpath)
        rows = conn.execute("""SELECT source, MAX(started_at) last_run,
              MAX(CASE WHEN ok=1 THEN started_at END) last_ok,
              MAX(CASE WHEN ok=0 THEN started_at END) last_fail FROM runs GROUP BY source""").fetchall()
        enabled = cfg["sources"]["enabled"]
        print("enabled:", ", ".join(enabled))
        for x in rows:
            print(f"{x['source']:<12} last ok: {x['last_ok'] or '-'}  last failure: {x['last_fail'] or '-'}")
    elif args.cmd == "stats":
        conn = db.connect(dbpath)
        for x in conn.execute("SELECT source, COUNT(*) n, SUM(expired) exp FROM jobs GROUP BY source"):
            print(f"{x['source']:<12} {x['n']} jobs ({x['exp'] or 0} expired)")
        today = conn.execute("SELECT COUNT(*) FROM jobs WHERE date(first_seen_at)=date('now')").fetchone()[0]
        print("new today:", today)
        print("top scores:")
        for x in conn.execute("SELECT score, title, company FROM jobs WHERE expired=0 "
                              "ORDER BY score DESC LIMIT 10"):
            print(f"  {x['score']:>4}  {x['title']} — {x['company']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
