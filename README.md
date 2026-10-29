# job-radar

A small private job-alert tool. It checks job sites on a schedule, scores each
posting against a candidate profile, remembers what it has already seen
(SQLite), and sends a daily Telegram digest of **new** relevant postings.

It never applies to anything, never logs in to any site, and never tries to get
around blocks. If a site refuses, the failure is recorded and shown in the digest.

## Setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env            # then fill in the two Telegram values
.venv/bin/python -m pytest      # sanity check
```

### Telegram

1. In Telegram, talk to **@BotFather**, send `/newbot`, and copy the token into
   `TELEGRAM_BOT_TOKEN` in `.env`.
2. Open a chat with your new bot and send it any message.
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy
   `message.chat.id` into `TELEGRAM_CHAT_ID`.
4. `python -m jobradar notify-test` should deliver a test message.

## Commands

```bash
python -m jobradar run --dry-run     # print the digest, write nothing
python -m jobradar run               # real run: store, notify, mark notified
python -m jobradar run --source jobthai
python -m jobradar sources           # enabled sources, last ok / last failure
python -m jobradar stats             # job counts and top scores
python -m jobradar notify-test
```

Sources: `jobspy` (Indeed; LinkedIn is off because it blocks GitHub's servers), `hoteljob`, `jobbkk`, `jobthai`, `jobtopgun`, and
`careerlink`. CareerLink is **unverified** (its robots.txt blocks Claude's
crawlers, so it was built without live access). Paste Bangkok search-result URLs
from your own browser into `careerlink.search_urls` in `config.yaml` and add
`careerlink` to `sources.enabled`. If its markup differs, the run reports it as
failed instead of crashing.

JobsDB and Jobstreet are deliberately not scraped.

## Scheduling (cron)

```bash
scripts/install_cron.sh             # 08:30 Asia/Bangkok daily
scripts/install_cron.sh --evening   # also 18:00
```

The script prints the crontab lines and asks before installing. Output goes to
`data/run.log`, trimmed automatically. The machine must be awake at the
scheduled time. macOS cron ignores `CRON_TZ`, so there the Mac's own clock decides.

## GitHub Actions

`.github/workflows/run.yml` runs daily at 08:30 Bangkok time (cron `30 1 * * *`
UTC) and can be started by hand from the Actions tab. Repository secrets needed:
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `CONFIG_LOCAL` (the contents of
`config.local.yaml`). GitHub runner IPs are often blocked by LinkedIn (hence off) and
sometimes Indeed, so those may come back empty; the digest footer names any source that
failed. The database is kept between runs with `actions/cache`, which can be
evicted after 7 days without use, so old jobs might then be re-sent. To switch
it off, add `if: false` under `run:` in the workflow. Don't run both cron and
Actions, or you will get two digests.

## Public repo note

Personal details live in `config.local.yaml`, which is gitignored and merged over
`config.yaml` at load time. `.env`, `data/` and `HANDOVER.md` are gitignored too.
Never commit tokens. Check `git status` before the first push.

## Tuning the scoring

Everything is in `config.yaml` under `scoring`: terms and points for target
roles, languages (Burmese, Chinese), degree and experience requirements,
seniority, nationality, and salary. Examples:

- Raise `notify.min_score` for a shorter digest, lower it for a longer one.
- Add a job title to `scoring.target_role.terms` to treat it as a target role.
- Add a language wish to `scoring.chinese.terms` (or Burmese) to match it.
- A degree or experience mention in the same sentence as soft wording
  ("preferred", "will train", "ไม่จำเป็น") gets a small penalty instead of the
  full one. Edit `scoring.soft_requirement.terms` to change that.
- Jobs that fit by role or Burmese but are held back by degree or experience
  appear in the digest's "worth a try" section (`notify.worth_a_try`).

Check a change with `python -m jobradar run --dry-run`.

## Adding a source

1. Create `src/jobradar/sources/<name>.py` with a class that has `name` and
   `fetch()` returning a list of `Job`. Use `PoliteClient` from `jobradar.http`
   for all requests (robots.txt, 2 s per host, honest User-Agent, stops after
   3 blocks in a row).
2. Register it in `build_sources` in `sources/__init__.py`.
3. Add a section for it in `config.yaml` and the name to `sources.enabled`.
4. Save a real page into `tests/fixtures/` and write a parser test.

Report partial problems by appending to the source's `partial_failures` list;
the digest footer lists them.
