from jobradar.models import Job
from jobradar.notify import LIMIT, build_digest, format_job


def test_html_escaped():
    j = Job("s", "https://x.test/?a=1&b=2", "<script>", company="A & B", reasons=["+1 x<y"])
    out = format_job(j)
    assert "<script>" not in out and "&lt;script&gt;" in out and "A &amp; B" in out


def test_split_under_limit():
    jobs = [Job("s", f"https://x.test/{i}", "T" * 100, reasons=["r" * 200]) for i in range(60)]
    msgs = build_digest(jobs, 100, ["linkedin"])
    assert len(msgs) > 1 and all(len(m) <= LIMIT for m in msgs)
    assert "failed today: linkedin" in msgs[-1]


def test_single_message_footer():
    msgs = build_digest([Job("s", "https://x.test/1", "T")], 5, [])
    assert len(msgs) == 1 and "1 new / 5 scanned" in msgs[0]


def test_worth_a_try_section():
    t = Job("s", "https://x.test/t", "Receptionist", reasons=["+30 title: receptionist", "-40 degree required: bachelor"])
    msgs = build_digest([], 3, [], [t])
    assert "Worth a try" in msgs[0] and "0 new" not in msgs[0].split("\n")[-1]
