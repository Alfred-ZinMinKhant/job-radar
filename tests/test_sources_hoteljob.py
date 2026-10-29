from datetime import date
from pathlib import Path

from jobradar.scoring import score_job
from jobradar.sources.hoteljob import HotelJobSource, job_from, parse_detail, parse_list

FX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 29)


def read(n):
    return (FX / n).read_text(encoding="utf-8")


def test_parse_list():
    cards = parse_list(read("hoteljob_list.html"))
    assert [c.id for c in cards] == ["1001", "1002", "1003"]
    c = cards[0]
    assert (c.title, c.company, c.salary) == ("Front Office Crew", "YOTEL Bangkok (synthetic)", "15,001 - 20,000 บาท")
    assert c.location == "กรุงเทพ · เขตวัฒนา" and c.posted_hint == "3 ชั่วโมงที่แล้ว"


def test_parse_detail_and_buddhist_date():
    d = parse_detail(read("hoteljob_detail_yotel.html"))
    assert d["salary"] == "15,001 - 20,000 บาท"
    assert d["closes_text"] == "28 พฤศจิกายน 2569"
    assert d["fields"]["ประสบการณ์"] == "1 ปีขึ้นไป"
    assert "งานคล้ายกัน" not in d["body"] and "ปริญญาตรี" not in d["body"]  # similar-jobs block ignored


def _score(cfg, detail_file, card_idx):
    card = parse_list(read("hoteljob_list.html"))[card_idx]
    job = job_from(card, parse_detail(read(detail_file)))
    return job, score_job(job, cfg, TODAY)


def test_yotel_scores_positive_with_experience_reduction(cfg):
    job, r = _score(cfg, "hoteljob_detail_yotel.html", 0)
    assert job.closes_at == "28 พฤศจิกายน 2569" and "Front Office Crew" in job.title
    assert r.degree_flag == "not_required" and r.score >= 30
    assert any("experience 1 year" in x for x in r.reasons)


def test_hyatt_degree_penalty_lands_in_worth_a_try_range(cfg):
    _, r = _score(cfg, "hoteljob_detail_hyatt.html", 1)
    assert r.degree_flag == "required" and r.score < 30
    assert any("degree required" in x for x in r.reasons)


def test_source_filters_titles_and_fetches_details(cfg):
    pages = {"https://www.hoteljob.in.th/bangkok/": read("hoteljob_list.html"),
             "https://www.hoteljob.in.th/bangkok/?page=2": "<html></html>",
             "https://www.hoteljob.in.th/position/1001/": read("hoteljob_detail_yotel.html"),
             "https://www.hoteljob.in.th/position/1002/": read("hoteljob_detail_hyatt.html")}

    class Fake:
        def get(self, url):
            return pages[url]

    src = HotelJobSource({"max_pages": 2}, cfg["scoring"]["target_role"]["terms"], client=Fake())
    jobs = src.fetch()
    assert [j.url.rsplit("/", 2)[-2] for j in jobs] == ["1001", "1002"]  # Housekeeper skipped
    assert src.partial_failures == []


def test_blocked_source_is_reported_not_fatal(cfg):
    from jobradar.sources.base import SourceBlocked

    class Blocked:
        n = 0

        def get(self, url):
            self.n += 1
            if self.n == 1:
                return read("hoteljob_list.html")
            raise SourceBlocked("3 consecutive 429")

    src = HotelJobSource({"max_pages": 1}, cfg["scoring"]["target_role"]["terms"], client=Blocked())
    jobs = src.fetch()
    assert len(jobs) == 1 and "blocked" in src.partial_failures[0]
