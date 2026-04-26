# scripts/scraper

One-shot tools for pulling tournament data from external sources into `_DATA_/`.

## vltc.py — VLTC tournament scraper

Pulls every tournament's detail page from www.vltc.com.mt, extracts embedded
Google Sheet links, and downloads each as `.xlsx` into
`_DATA_/VLTC/scraped/<year>/<slug>.xlsx`.

### Why this works (and what doesn't)

VLTC runs ASP.NET WebForms. The tournament list page (`?pid=2`) uses
`__doPostBack` for navigation. Plain HTTP POSTs to that endpoint get bounced
to `/Maintenance.html` — there's an anti-bot guard that requires JavaScript
execution.

**Critical discovery:** the postback's *result* is a clean GET URL —
`tournament.aspx?id=N` — and that endpoint is fully accessible via plain
`curl` with no session, cookies, or JS. The bot guard only fires on the
postback itself, not on the resulting URL.

So this scraper skips the postback entirely and probes the numeric ID space
directly. No browser automation needed.

### Usage

```bash
# 1. Discover all valid tournament IDs by probing a numeric range
python scripts/scraper/vltc.py discover --range 19000:21000

# 2. Download every Google Sheet referenced in the manifest
python scripts/scraper/vltc.py download

# Or do both in one shot:
python scripts/scraper/vltc.py all --range 19000:21000
```

### What you get

- `_DATA_/VLTC/scraped/manifest.json` — every tournament's id, title, year,
  Google Sheet IDs, downloaded file paths, sha256s.
- `_DATA_/VLTC/scraped/<year>/<slug>.xlsx` — one xlsx per Google Sheet.

### Idempotent re-runs

Re-running `download` re-fetches each sheet but only writes to disk if the
content changed (compared against the previous file's sha256). Safe to run
on a cron without burning bandwidth or polluting commits.

### Politeness

- Rate-limited (`--sleep 0.5` default between downloads).
- Default concurrency on discovery is 8.
- All requests use a real Chrome User-Agent.

### Next step after scraping

Each downloaded xlsx can be loaded into the Phase 0 SQLite via:

```bash
python scripts/phase0/cli.py load --file _DATA_/VLTC/scraped/<year>/<slug>.xlsx
python scripts/phase0/cli.py rate
```

The dispatcher in `cli.py` matches filenames against known templates. If the
slug doesn't match any registered template, you'll see a clear error pointing
to the missing parser.
