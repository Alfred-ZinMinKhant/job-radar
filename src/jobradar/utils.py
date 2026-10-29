import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"fbclid", "gclid", "trk", "trackingid", "refid", "ref", "from", "source"}
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = sorted((k, v) for k, v in parse_qsl(parts.query)
                   if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(query), ""))


def job_id(source: str, url: str) -> str:
    return hashlib.sha1((source + canonical_url(url)).encode()).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_THAI_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
_THAI_ABBR = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
for _i, (_full, _abbr) in enumerate(zip(_THAI_MONTHS, _THAI_ABBR), 1):
    _MONTHS[_full] = _MONTHS[_abbr] = _i
for _name, _i in list(_MONTHS.items()):
    if _name.isascii():
        _MONTHS[_name[:3]] = _i


def parse_date(text: str | None) -> date | None:
    """Parse ISO, '28 November 2569' or '28 พฤศจิกายน 2569'. Years above 2400 are Buddhist Era (-543)."""
    if not text:
        return None
    text = text.strip()
    if (m := re.search(r"(\d{4})-(\d{2})-(\d{2})", text)):
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif (m := re.search(r"(\d{1,2})\s+([^\s\d]+?)\.?,?\s+(\d{4})", text)) and \
            (mo := _MONTHS.get(m.group(2).lower()) or _MONTHS.get(m.group(2).lower() + ".")):
        year, month, day = int(m.group(3)), mo, int(m.group(1))
    else:
        return None
    if year > 2400:
        year -= 543
    try:
        return date(year, month, day)
    except ValueError:
        return None


_REL = [(r"นาที|minute", 0), (r"ชั่วโมง|hour", 0), (r"วัน|day", 1), (r"สัปดาห์|week", 7), (r"เดือน|month", 30)]


def parse_relative(text: str | None, today: date | None = None) -> date | None:
    """'3 ชั่วโมงที่แล้ว' / '2 days ago' -> a date. Only a hint; first_seen_at stays the truth."""
    if not text:
        return None
    today = today or date.today()
    if "เมื่อวาน" in text or "yesterday" in text.lower():
        return today - timedelta(days=1)
    m = re.search(r"(\d+)\s*([^\d\s]+)", text)
    if not m:
        return None
    for pat, days in _REL:
        if re.search(pat, m.group(2), re.I):
            return today - timedelta(days=int(m.group(1)) * days)
    return None


def is_older_than(posted_at: str | None, cutoff: date) -> bool:
    """True only when posted_at parses to a date before cutoff; undated postings are kept."""
    d = parse_date(posted_at)
    return d is not None and d < cutoff
