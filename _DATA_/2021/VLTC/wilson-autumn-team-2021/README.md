# Wilson Autumn Team 2021

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** 2021
**Source:** Club website
**Source URL:** [https://www.vltc.com.mt/tournament.aspx?id=107](https://www.vltc.com.mt/tournament.aspx?id=107)
**Extraction method:** HTTP scrape — `tournament.aspx?id=107` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:51 UTC

## Files in this folder

- `Wilson Autumn Team 2021.xlsx` (Google Sheet ID `1luKwJtXcOj7ETEKEmFqWJKGLFuZccKJH`, sha256 `770d20686968…`)
- `raw/detail-page.html` — original HTML of the tournament detail page at scrape time.

## Provenance

This folder contains data extracted automatically from the VLTC public tournament archive
by `scripts/scraper/vltc.py`. The detail page is captured as raw HTML for audit purposes;
the `.xlsx` files are downloaded via Google Sheets' public `export?format=xlsx` endpoint.

To re-extract: `python scripts/scraper/vltc.py download` (idempotent — only re-writes
files whose Google Sheet content has changed).
