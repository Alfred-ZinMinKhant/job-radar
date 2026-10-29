from datetime import date
from pathlib import Path

import pytest

from jobradar.scoring import score_job
from jobradar.sources import careerlink, jobbkk, jobthai
from jobradar.sources.base import SourceBlocked
from jobradar.sources.jsonld import find_jobposting

FX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 29)
read = lambda n: (FX / n).read_text(encoding="utf-8")


class Fake:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def get(self, url):
        self.asked.append(url)
        if url not in self.pages:
            raise KeyError(url)
        v = self.pages[url]
        if isinstance(v, Exception):
            raise v
        return v


# ---- JSON-LD
def test_jsonld_plain_and_next_push():
    assert find_jobposting(read("jobbkk_detail_admin.html"))["@type"] == "JobPosting"
    assert find_jobposting(read("jobthai_detail.html"))["title"] == "พนักงานต้อนรับ"


# ---- JobBKK
def test_jobbkk_list_dedupes_by_job_id():
    assert [c[0] for c in jobbkk.parse_list(read("jobbkk_list.html"))] == ["9001", "9002", "9003"]


def test_jobbkk_detail_and_scoring(cfg):
    j = jobbkk.job_from_detail("/jobs/detail/12/9002", read("jobbkk_detail_admin.html"))
    assert j.closes_at == "2026-11-06" and j.salary_text == "18,000–20,000 THB/month"
    r = score_job(j, cfg, TODAY)
    assert r.degree_flag == "not_required" and r.score >= 50  # admin assistant + ม.6 ขึ้นไป


def test_jobbkk_drops_non_bangkok_region():
    assert jobbkk.job_from_detail("/jobs/detail/12/9002", read("jobbkk_detail_upcountry.html")) is None


def test_jobbkk_source_filters_by_title_and_fetches(cfg):
    terms = cfg["scoring"]["target_role"]["terms"]
    pages = {jobbkk.list_url("ธุรการ", 1): read("jobbkk_list.html"),
             "https://www.jobbkk.com/jobs/detailurgent/11/9001": read("jobbkk_detail_admin.html"),
             "https://www.jobbkk.com/jobs/detail/12/9002": read("jobbkk_detail_admin.html")}
    src = jobbkk.JobBKKSource({"keywords": ["ธุรการ"], "max_pages": 1}, terms, client=Fake(pages))
    assert len(src.fetch()) == 2  # the driver ad is skipped before any detail request
    assert src.partial_failures == []


def test_jobbkk_blocked_is_reported(cfg):
    pages = {jobbkk.list_url("ธุรการ", 1): SourceBlocked("3 consecutive 429")}
    src = jobbkk.JobBKKSource({"keywords": ["ธุรการ"]}, cfg["scoring"]["target_role"]["terms"], client=Fake(pages))
    with pytest.raises(SourceBlocked):
        src.fetch()


# ---- JobThai
def test_jobthai_list_url_has_bangkok_province():
    assert "province=01" in jobthai.list_url("ธุรการ", 1)


def test_jobthai_only_bangkok_title_matches_fetched(cfg):
    pages = {jobthai.list_url("พนักงานต้อนรับ", 1): read("jobthai_list.html"),
             "https://www.jobthai.com/th/company/job/7001": read("jobthai_detail.html")}
    fake = Fake(pages)
    src = jobthai.JobThaiSource({"keywords": ["พนักงานต้อนรับ"]}, cfg["scoring"]["target_role"]["terms"], client=fake)
    jobs = src.fetch()
    assert [j.url.rsplit("/", 1)[1] for j in jobs] == ["7001"]
    assert len(fake.asked) == 2  # one list page + one detail page


def test_jobthai_diploma_or_bachelor_counts_as_no_degree_needed(cfg):
    item = jobthai.parse_list(read("jobthai_list.html"))[0]
    j = jobthai.job_from(item, read("jobthai_detail.html"))
    r = score_job(j, cfg, TODAY)
    assert r.degree_flag == "not_required" and j.closes_at == "2026-11-20"
    assert not any("experience required" in x for x in r.reasons)  # "ถ้ามีประสบการณ์จะพิจารณาเป็นพิเศษ" is soft


def test_jobthai_markup_change_is_loud():
    with pytest.raises(ValueError):
        jobthai.parse_list("<html></html>")


# ---- CareerLink
def test_careerlink_list_links_canonical():
    assert careerlink.parse_list(read("careerlink_list.html")) == [
        "https://www.careerlink.co.th/en/job/sales-staff-burmese/1001",
        "https://www.careerlink.co.th/en/job/receptionist/1002"]


def test_careerlink_burmese_sales_example_is_strongly_negative(cfg):
    j = careerlink.job_from_html("https://www.careerlink.co.th/en/job/sales-staff-burmese/1001",
                                 read("careerlink_detail_text.html"))
    r = score_job(j, cfg, TODAY)
    assert j.title == "Sales Staff (Burmese)" and "menu" not in j.description
    assert r.score <= -100 and any("nationality" in x for x in r.reasons)


# ---- jobtopgun

def test_jobtopgun_list_cards_and_bangkok_flag():
    from jobradar.sources import jobtopgun
    items = jobtopgun.parse_list(read("jobtopgun_list.html"))
    assert [i["id"] for i in items] == ["j21417-1139", "j279-1278", "j279-1274", "j279-1042"]
    assert items[0]["title"] == "Call Center Inbound" and items[0]["bangkok"] and not items[3]["bangkok"]


def test_jobtopgun_source_filters_then_fetches_detail(cfg):
    from jobradar.sources import jobtopgun
    pages = {jobtopgun.list_url("customer-service", 1): read("jobtopgun_list.html"),
             "https://www.jobtopgun.com/th/jobs/j21417-1139": read("jobtopgun_detail.html")}
    fake = Fake(pages)
    src = jobtopgun.JobTopGunSource({"fields": ["customer-service"], "max_pages": 1}, ["call center"], client=fake)
    jobs = src.fetch()
    assert [j.url for j in jobs] == ["https://www.jobtopgun.com/th/jobs/j21417-1139"]
    assert jobs[0].source == "jobtopgun" and jobs[0].location and jobs[0].description
    assert len(fake.asked) == 2  # one list page + one matching, Bangkok card


def test_jobtopgun_markup_change_is_loud():
    from jobradar.sources import jobtopgun
    with pytest.raises(ValueError):
        jobtopgun.parse_list("<html></html>")


def test_jobtopgun_blocked_is_reported():
    from jobradar.sources import jobtopgun
    src = jobtopgun.JobTopGunSource({"fields": ["administration"]}, ["admin"], client=Fake({jobtopgun.list_url("administration", 1): SourceBlocked("403")}))
    with pytest.raises(SourceBlocked):
        src.fetch()


def test_jobtopgun_empty_later_page_ends_the_field(cfg):
    from jobradar.sources import jobtopgun
    pages = {jobtopgun.list_url("education", 1): read("jobtopgun_list.html"), jobtopgun.list_url("education", 2): "<html></html>"}
    src = jobtopgun.JobTopGunSource({"fields": ["education"], "max_pages": 3}, ["zzz"], client=Fake(pages))
    assert src.fetch() == []  # no title match, but page 2 being empty is not an error
