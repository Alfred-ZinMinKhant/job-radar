"""Pull a schema.org JobPosting out of a page. Handles plain <script type=ld+json> and the
Next.js form where the JSON is a string inside a __next_s push (seen on jobthai.com)."""
import json
import re

from selectolax.lexbor import LexborHTMLParser

from ..utils import parse_date

_PLAIN = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_NEXT = re.compile(r'"type":"application/ld\+json","children":("(?:[^"\\]|\\.)*")')
UNIT = {"MONTH": "month", "YEAR": "year", "WEEK": "week", "DAY": "day", "HOUR": "hour"}


def _walk(obj):
    if isinstance(obj, list):
        for o in obj:
            yield from _walk(o)
    elif isinstance(obj, dict):
        yield obj
        yield from _walk(obj.get("@graph", []))


def find_jobposting(html: str) -> dict | None:
    blobs = [m.group(1) for m in _PLAIN.finditer(html)]
    for m in _NEXT.finditer(html):
        try:
            blobs.append(json.loads(m.group(1)))  # JS string literal -> the JSON text
        except ValueError:
            continue
    for b in blobs:
        try:
            data = json.loads(b)
        except ValueError:
            continue
        for o in _walk(data):
            if o.get("@type") == "JobPosting":
                return o
    return None


def _text(s: str) -> str:
    if "<" in s:
        s = LexborHTMLParser(s).text(separator="\n")
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def posting_fields(jp: dict) -> dict:
    org = jp.get("hiringOrganization") or {}
    addr = (jp.get("jobLocation") or {}).get("address", {}) if isinstance(jp.get("jobLocation"), dict) else {}
    sal = ""
    val = (jp.get("baseSalary") or {}).get("value") or {}
    if isinstance(val, dict) and (val.get("minValue") or val.get("maxValue")):
        lo, hi = val.get("minValue"), val.get("maxValue")
        amt = "–".join(f"{float(x):,.0f}" for x in (lo, hi) if x)
        sal = f"{amt} {jp['baseSalary'].get('currency', 'THB')}/{UNIT.get(str(val.get('unitText')).upper(), 'month')}"
    closes = parse_date(jp.get("validThrough"))
    extra = []
    for key in ("qualifications", "educationRequirements", "experienceRequirements", "skills"):
        v = jp.get(key)
        if isinstance(v, dict):
            v = v.get("credentialCategory") or v.get("name") or json.dumps(v, ensure_ascii=False)
        if v:
            extra.append(_text(str(v)))
    return {"title": _text(jp.get("title", "")), "description": "\n".join([_text(jp.get("description", "")), *extra]).strip(),
            "company": org.get("name", "") if isinstance(org, dict) else str(org),
            "locality": addr.get("addressLocality", ""), "region": addr.get("addressRegion", ""),
            "salary": sal, "closes": closes.isoformat() if closes else None,
            "posted": (jp.get("datePosted") or "")[:10] or None}
