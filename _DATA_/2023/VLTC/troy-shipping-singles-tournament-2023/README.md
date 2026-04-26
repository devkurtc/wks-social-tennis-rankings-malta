# Troy Shipping Singles Tournament 2023

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** 2023
**Source:** Club website
**Source URL:** [https://www.vltc.com.mt/tournament.aspx?id=122](https://www.vltc.com.mt/tournament.aspx?id=122)
**Extraction method:** HTTP scrape — `tournament.aspx?id=122` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:56 UTC

## Files in this folder

- `Troy Shipping Singles Tournament 2023.xlsx` (Google Sheet ID `1GXMvopB_hgG4lxrhSba_SuSjzOB_PtS4`, sha256 `97be9756d55d…`)
- `raw/detail-page.html` — original HTML of the tournament detail page at scrape time.

## Provenance

This folder contains data extracted automatically from the VLTC public tournament archive
by `scripts/scraper/vltc.py`. The detail page is captured as raw HTML for audit purposes;
the `.xlsx` files are downloaded via Google Sheets' public `export?format=xlsx` endpoint.

To re-extract: `python scripts/scraper/vltc.py download` (idempotent — only re-writes
files whose Google Sheet content has changed).
