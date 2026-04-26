# H & S Solutions Singles Tournament 2026

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** 2026
**Source:** Club website
**Source URL:** [https://www.vltc.com.mt/tournament.aspx?id=20152](https://www.vltc.com.mt/tournament.aspx?id=20152)
**Extraction method:** HTTP scrape — `tournament.aspx?id=20152` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:56 UTC

## Files in this folder

- `H & S Solutions Singles Tournament 2026 - sheet 1.xlsx` (Google Sheet ID `15_jYda78UuvH1SmSJM4J02FdP7poKPOo`, sha256 `72a0ef3c464e…`)
- `H & S Solutions Singles Tournament 2026 - sheet 2.xlsx` (Google Sheet ID `1eojvqu-EDfwriocopeRHZj15NHnXtlUk`, sha256 `58b50f2c2732…`)
- `raw/detail-page.html` — original HTML of the tournament detail page at scrape time.

## Provenance

This folder contains data extracted automatically from the VLTC public tournament archive
by `scripts/scraper/vltc.py`. The detail page is captured as raw HTML for audit purposes;
the `.xlsx` files are downloaded via Google Sheets' public `export?format=xlsx` endpoint.

To re-extract: `python scripts/scraper/vltc.py download` (idempotent — only re-writes
files whose Google Sheet content has changed).
