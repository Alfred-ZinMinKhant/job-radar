import json
from datetime import date
from pathlib import Path

import pytest

from jobradar.models import Job
from jobradar.scoring import max_monthly_salary, required_years, score_job

TODAY = date(2026, 10, 29)


def S(cfg, title="Clerk", desc="", salary="", closes=None):
    return score_job(Job("t", "https://x.test/1", title, description=desc, salary_text=salary,
                         closes_at=closes), cfg, TODAY)


# (rule, title, description, expected reason prefix)
RULES = [
    ("target_role", "Receptionist", "", "+30 title: receptionist"),
    ("target_role thai", "พนักงานต้อนรับ", "", "+30 title: พนักงานต้อนรับ"),
    ("burmese", "Clerk", "Must speak Burmese", "+25 burmese wanted: burmese"),
    ("burmese thai", "Clerk", "ล่ามภาษาพม่า", "+25 burmese wanted"),
    ("chinese", "Clerk", "Chinese speaking preferred", "-100 chinese wanted"),
    ("no_degree thai", "Clerk", "ไม่จำกัดวุฒิการศึกษา", "+25 no degree needed"),
    ("no_degree m6", "Clerk", "วุฒิ ม.6 ขึ้นไป", "+25 no degree needed: ม.6"),
    ("no_degree en", "Clerk", "High school graduates welcome", "+25 no degree needed"),
    ("degree_required", "Clerk", "Bachelor's degree in any major", "-10 degree required"),
    ("degree_required thai", "Clerk", "ปริญญาตรีขึ้นไป", "-10 degree required"),
    ("postgrad", "Clerk", "Master's degree in business", "-100 postgraduate degree required"),
    ("postgrad thai", "Clerk", "ปริญญาโทขึ้นไป", "-100 postgraduate degree required"),
    ("degree_equivalent", "Clerk", "Bachelor or equivalent experience", "-10 degree 'or equivalent'"),
    ("entry_level", "Clerk", "Fresh graduate welcome", "+10 entry level"),
    ("entry_level thai", "Clerk", "ไม่มีประสบการณ์ก็ได้", "+10 entry level"),
    ("exp 2+", "Clerk", "Requires 2+ years experience", "-30 experience 2+ years"),
    ("exp 3 years", "Clerk", "3 years of sales experience", "-30 experience 3+ years"),
    ("exp thai", "Clerk", "ประสบการณ์ 2 ปี", "-30 experience 2+ years"),
    ("exp 1yr", "Clerk", "At least 1 year experience", "-10 experience 1 year"),
    ("exp unspecified", "Clerk", "มีประสบการณ์ในคลินิกมาก่อน", "-10 experience required"),
    ("soft degree", "Clerk", "Bachelor's degree preferred", "-10 degree preferred, not required"),
    ("soft degree thai", "Clerk", "ปริญญาตรี ไม่จำเป็น", "-10 degree preferred"),
    ("soft experience", "Clerk", "3 years experience is a plus, training provided", "-10 experience 3+ years preferred"),
    ("training elsewhere", "Clerk", "Requires 2 years experience.\nFull training provided.", "-10 experience 2+ years preferred"),
    ("training thai", "Clerk", "ประสบการณ์ 3 ปี\nมีอบรมให้", "-10 experience 3+ years preferred"),
    ("seniority", "Front Office Manager", "", "-50 seniority in title: manager"),
    ("seniority thai", "หัวหน้าแผนก", "", "-50 seniority in title: หัวหน้า"),
    ("nationality", "Clerk", "Burmese nationality only", "-100 nationality"),
    ("nationality thai", "Clerk", "สัญชาติพม่า", "-100 nationality"),
    ("low salary", "Clerk", "", "-15 salary 12000 < 15000"),
]


@pytest.mark.parametrize("name,title,desc,expected", RULES, ids=[r[0] for r in RULES])
def test_rule(cfg, name, title, desc, expected):
    salary = "12,000 THB" if name == "low salary" else ""
    r = S(cfg, title, desc, salary)
    assert any(x.startswith(expected) for x in r.reasons), r.reasons


def test_closed_by_date(cfg):
    r = S(cfg, "Receptionist", closes="1 January 2569")  # 2026-01-01
    assert r.excluded


def test_closed_by_text(cfg):
    assert S(cfg, "Receptionist", "ปิดรับสมัครแล้ว").excluded


def test_open_future_date(cfg):
    assert not S(cfg, "Receptionist", closes="28 November 2569").excluded


def test_nationality_not_counted_as_burmese_language(cfg):
    r = S(cfg, "Clerk", "Burmese nationality")
    assert not any("burmese wanted" in x for x in r.reasons)


def test_no_degree_beats_degree_mention(cfg):
    r = S(cfg, "Clerk", "ม.6 ขึ้นไป or bachelor")
    assert r.degree_flag == "not_required" and not any("-10" in x for x in r.reasons)


def test_age_not_read_as_experience():
    assert required_years("experience needed. age 25-39 years old") is None


def test_salary_parsing():
    assert max_monthly_salary("15,001 - 20,000 THB") == 20000
    assert max_monthly_salary("25k") == 25000
    assert max_monthly_salary("Negotiable") is None
    assert max_monthly_salary("500 per hour") is None


# --- the five real-shaped examples (synthetic fixtures) ---
def _fx(cfg):
    from jobradar.sources.fixtures import FixtureSource
    root = Path(cfg["_root"])
    return {j.title: score_job(j, cfg, TODAY) for j in FixtureSource(root / "tests/fixtures/jobs.json").fetch()}


def test_example_yotel_night_shift_excluded(cfg):
    r = _fx(cfg)["Front Office Crew (Night Shift)"]
    assert r.excluded and "shift past 10 PM" in r.reasons[0]


@pytest.mark.parametrize("title,desc", [
    ("Waiter", ""), ("Hostess", ""), ("Restaurant Hostess", ""), ("Bar Staff", ""), ("พนักงานเสิร์ฟ", ""),
])
def test_unwanted_roles_excluded(cfg, title, desc):
    assert S(cfg, title, desc).excluded


@pytest.mark.parametrize("desc", [
    "Night audit duties", "ทำงานกะดึก", "Hours 14:00-22:00", "Shift 2pm - 11pm", "เวลา 15.00 ถึง 23.00",
])
def test_late_shift_excluded(cfg, desc):
    assert S(cfg, "Receptionist", desc).excluded


@pytest.mark.parametrize("title", ["Flight Attendant", "Cabin Crew", "Air Hostess", "แอร์โฮสเตส", "Airline Steward"])
def test_airline_cabin_roles_wanted(cfg, title):
    r = S(cfg, title, "Day shift")
    assert not r.excluded and any(x.startswith("+30") for x in r.reasons)


def test_barista_allowed(cfg):
    assert not S(cfg, "Barista", "Day shift").excluded


@pytest.mark.parametrize("desc", ["Hours 09:00-18:00", "Shift 8am - 5pm", "Mon-Fri 10:00-19:00"])
def test_day_shift_kept(cfg, desc):
    assert not S(cfg, "Receptionist", desc).excluded


def test_example_hyatt(cfg):
    r = _fx(cfg)["Guest Service Officer, Front Office"]
    assert r.degree_flag == "required" and r.score >= 30  # bachelor's is only a mild penalty now


def test_example_burmese_sales(cfg):
    r = _fx(cfg)["Sales Staff (Burmese)"]
    assert r.score <= -50


def test_example_clinic_admin(cfg):
    r = _fx(cfg)["ผู้ช่วยธุรการ"]
    assert r.score >= 50


def test_example_beauty(cfg):
    r = _fx(cfg)["Beauty Consultant (English Speaking)"]
    assert any("+25" in x for x in r.reasons) and any("-10" in x for x in r.reasons)
    assert 0 <= r.score < 30


def test_soft_wording_only_applies_in_same_sentence(cfg):
    r = S(cfg, "Clerk", "Bachelor's degree required. Training provided")
    assert any(x.startswith("-10") for x in r.reasons)
