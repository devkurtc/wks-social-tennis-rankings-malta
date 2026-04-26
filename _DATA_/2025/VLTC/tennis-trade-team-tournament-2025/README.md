# Tennis Trade Team Tournament 2025

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** 2025
**Source:** Club website
**Source URL:** [https://www.vltc.com.mt/tournament.aspx?id=20149](https://www.vltc.com.mt/tournament.aspx?id=20149)
**Extraction method:** HTTP scrape — `tournament.aspx?id=20149` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:44 UTC

## Files in this folder

- `Tennis Trade Team Tournament 2025 - sheet 1.xlsx` (Google Sheet ID `1eojvqu-EDfwriocopeRHZj15NHnXtlUk`, sha256 `58b50f2c2732…`)
- `Tennis Trade Team Tournament 2025 - sheet 2.xlsx` (Google Sheet ID `1t1BSOGEZ2jTVX8U2j5YMqomhrlIZD9H4`, sha256 `c870e8e18ee2…`)
- `raw/detail-page.html` — original HTML of the tournament detail page at scrape time.

## Provenance

This folder contains data extracted automatically from the VLTC public tournament archive
by `scripts/scraper/vltc.py`. The detail page is captured as raw HTML for audit purposes;
the `.xlsx` files are downloaded via Google Sheets' public `export?format=xlsx` endpoint.

To re-extract: `python scripts/scraper/vltc.py download` (idempotent — only re-writes
files whose Google Sheet content has changed).
