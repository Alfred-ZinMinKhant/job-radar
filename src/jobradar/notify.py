import logging
import os
from html import escape

import httpx

from .models import Job

LIMIT = 4000
DEGREE_LABEL = {"required": "degree required", "equivalent_ok": "degree or equivalent",
                "none_mentioned": "degree not mentioned", "not_required": "no degree needed"}
log = logging.getLogger(__name__)


def format_job(job: Job) -> str:
    company = f", {escape(job.company)}" if job.company else ""
    return (f"<b>{escape(job.title)}</b>{company}\n"
            f"💰 {escape(job.salary_text or 'n/a')} · 📍 {escape(job.location or 'n/a')} · "
            f"🎓 {DEGREE_LABEL.get(job.degree_flag, job.degree_flag)}\n"
            f"why: {escape('; '.join(job.reasons) or 'n/a')}\n"
            f"{escape(job.url)}")


def footer(new: int, scanned: int, failed: list[str]) -> str:
    text = f"{new} new / {scanned} scanned"
    if failed:
        text += f" · failed today: {escape(', '.join(failed))}"
    return text


TRY_HEADING = "🤔 <b>Worth a try</b> (asks for a degree or experience, but the role fits)"


def build_digest(jobs: list[Job], scanned: int, failed: list[str],
                 tries: list[Job] | None = None) -> list[str]:
    """Split into messages of at most LIMIT characters, on job boundaries."""
    tries = tries or []
    head = f"🔎 <b>job-radar: {len(jobs)} new</b>" + (f" + {len(tries)} worth a try" if tries else "")
    foot = footer(len(jobs) + len(tries), scanned, failed)
    blocks = [format_job(j) for j in jobs]
    if tries:
        blocks += [TRY_HEADING] + [format_job(j) for j in tries]
    messages, cur = [], head
    for b in blocks:
        if len(cur) + len(b) + 2 > LIMIT - len(foot) - 2 and cur != head:
            messages.append(cur)
            cur = ""
        cur = f"{cur}\n\n{b}" if cur else b
    messages.append(f"{cur}\n\n{foot}")
    return messages


def send(text: str) -> None:
    """Send to every chat id in TELEGRAM_CHAT_ID (comma-separated)."""
    token, raw = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    chats = [c.strip() for c in (raw or "").split(",") if c.strip()]
    if not token or not chats:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set (see .env.example)")
    errors = []
    for chat in chats:
        try:
            r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                           json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                                 "disable_web_page_preview": True})
            r.raise_for_status()
        except httpx.HTTPError as e:
            # httpx error text contains the URL, which contains the bot token
            errors.append(f"{chat}: {type(e).__name__} "
                          f"{getattr(getattr(e, 'response', None), 'status_code', '')}")
    if errors:
        raise RuntimeError("Telegram send failed: " + "; ".join(errors))


def send_all(messages: list[str]) -> None:
    for m in messages:
        send(m)
