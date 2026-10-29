"""Pure scoring functions. All terms and points come from config['scoring']."""
import re
from dataclasses import dataclass, field
from datetime import date

from .models import Job
from .utils import parse_date


@dataclass
class ScoreResult:
    score: int
    reasons: list[str] = field(default_factory=list)
    degree_flag: str = "none_mentioned"
    excluded: bool = False


def find_term(terms: list[str], text: str) -> str | None:
    """First term found in already-lowercased text. ASCII terms match on word edges."""
    for t in terms:
        t = t.lower()
        if t.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?:s|es)?(?![a-z0-9])", text):
                return t
        elif t == "ม.6":
            if re.search(r"ม\.6(?!\d)", text):
                return t
        elif t in text:
            return t
    return None


_NUM = re.compile(r"(\d+)\s*(\+|-\s*\d+)?\s*(?:years?|yrs?|ปี)", re.I)
_EXP_WORDS = ("experience", "ประสบการณ์")


def required_years(text: str) -> int | None:
    """Highest lower-bound years of experience stated in a segment mentioning experience."""
    lows = []
    for seg in re.split(r"[\n;|•]|\.\s", text):
        if not any(w in seg for w in _EXP_WORDS):
            continue
        for m in _NUM.finditer(seg):
            before = seg[max(0, m.start() - 12):m.start()]
            if re.search(r"age|อายุ", before) or re.match(r"\s*old", seg[m.end():m.end() + 8]):
                continue
            lows.append(int(m.group(1)))
    return max(lows) if lows else None


def _segments(text: str) -> list[str]:
    return re.split(r"[\n;|•]|\.\s", text)


def is_soft(terms: list[str], soft_terms: list[str], text: str) -> bool:
    """True if a sentence containing one of `terms` also has a soft-wording term."""
    return any(find_term(terms, seg) and find_term(soft_terms, seg) for seg in _segments(text))


def max_monthly_salary(salary_text: str) -> int | None:
    """Upper bound of a parseable monthly THB figure, else None."""
    t = salary_text.lower()
    if not t or re.search(r"hour|day|week|year|annum|ต่อปี|รายวัน|ชั่วโมง", t):
        return None
    vals = []
    for m in re.finditer(r"(\d{1,3}(?:,\d{3})+|\d+)(\s*k\b)?", t):
        v = int(m.group(1).replace(",", ""))
        if m.group(2):
            v *= 1000
        if v >= 1000:
            vals.append(v)
    return max(vals) if vals else None


def score_job(job: Job, cfg: dict, today: date | None = None) -> ScoreResult:
    s = cfg["scoring"]
    today = today or date.today()
    title = job.title.lower()
    text = f"{job.title}\n{job.description}".lower()
    score, reasons = 0, []

    def add(rule: str, label: str):
        nonlocal score
        pts = s[rule]["points"]
        score += pts
        reasons.append(f"{pts:+d} {label}")

    # closed / expired -> exclude
    closes = parse_date(job.closes_at)
    closed_hit = find_term(s["closed"]["terms"], text)
    if closed_hit or (closes and closes < today):
        why = f"closed: {closed_hit}" if closed_hit else f"closed on {closes}"
        return ScoreResult(0, [why], excluded=True)

    if (t := find_term(s["target_role"]["terms"], title)):
        add("target_role", f"title: {t}")

    # nationality first, and strip it so "Burmese nationality" is not read as a language wish
    nat = find_term(s["nationality_mismatch"]["terms"], text)
    lang_text = text
    if nat:
        add("nationality_mismatch", f"nationality: {nat}")
        for t in s["nationality_mismatch"]["terms"]:
            lang_text = lang_text.replace(t.lower(), " ")
    if (t := find_term(s["burmese"]["terms"], lang_text)):
        add("burmese", f"burmese wanted: {t}")
    if (t := find_term(s["chinese"]["terms"], lang_text)):
        add("chinese", f"chinese wanted: {t}")

    soft = s["soft_requirement"]["terms"]
    # degree
    no_deg = find_term(s["no_degree"]["terms"], text)
    deg_req = find_term(s["degree_required"]["terms"], text)
    equiv = find_term(s["degree_equivalent"]["terms"], text)
    flag = "none_mentioned"
    if no_deg:
        add("no_degree", f"no degree needed: {no_deg}")
        flag = "not_required"
    elif deg_req and equiv:
        add("degree_equivalent", f"degree '{equiv}'")
        flag = "equivalent_ok"
    elif deg_req and is_soft(s["degree_required"]["terms"], soft, text):
        add("soft_requirement", "degree preferred, not required")
        flag = "equivalent_ok"
    elif deg_req:
        add("degree_required", f"degree required: {deg_req}")
        flag = "required"
    elif equiv:
        flag = "equivalent_ok"

    # experience
    entry = find_term(s["entry_level"]["terms"], text)
    if entry:
        add("entry_level", f"entry level: {entry}")
    years = required_years(text)
    exp_soft = is_soft(list(_EXP_WORDS), soft, text)
    if years is not None and years >= s["experience_2plus"]["min_years"] and exp_soft:
        add("soft_requirement", f"experience {years}+ years preferred, not required")
    elif years is not None and years >= s["experience_2plus"]["min_years"]:
        add("experience_2plus", f"experience {years}+ years")
    elif years == 1:
        add("experience_1yr", "experience 1 year")
    elif years is None and not entry and not exp_soft:
        if (t := find_term(s["experience_unspecified"]["terms"], text)):
            add("experience_unspecified", f"experience required: {t}")

    if (t := find_term(s["seniority"]["terms"], title)):
        add("seniority", f"seniority in title: {t}")

    sal = max_monthly_salary(job.salary_text)
    if sal is not None and sal < cfg["scoring"]["min_salary"]:
        add("low_salary", f"salary {sal} < {cfg['scoring']['min_salary']}")

    return ScoreResult(score, reasons, flag)


def apply_score(job: Job, cfg: dict, today: date | None = None) -> Job:
    r = score_job(job, cfg, today)
    job.score, job.reasons, job.degree_flag, job.excluded = r.score, r.reasons, r.degree_flag, r.excluded
    return job
