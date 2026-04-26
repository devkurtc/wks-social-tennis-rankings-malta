# Sports Experience Chosen Doubles 2023

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** 2023
**Source:** Club website
**Source URL:** [https://www.vltc.com.mt/tournament.aspx?id=125](https://www.vltc.com.mt/tournament.aspx?id=125)
**Extraction method:** HTTP scrape — `tournament.aspx?id=125` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:56 UTC

## Files in this folder

- `Sports Experience Chosen Doubles 2023.xlsx` (Google Sheet ID `17xms9nTccUQBe5wpfjU_DBf_RdeXL-xP`, sha256 `8998f54760e6…`)
- `raw/detail-page.html` — original HTML of the tournament detail page at scrape time.

## Provenance

This folder contains data extracted automatically from the VLTC public tournament archive
by `scripts/scraper/vltc.py`. The detail page is captured as raw HTML for audit purposes;
the `.xlsx` files are downloaded via Google Sheets' public `export?format=xlsx` endpoint.

To re-extract: `python scripts/scraper/vltc.py download` (idempotent — only re-writes
files whose Google Sheet content has changed).
