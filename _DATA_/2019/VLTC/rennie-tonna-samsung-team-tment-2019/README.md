# Rennie Tonna Samsung Team T'ment 2019

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** 2019
**Source:** Club website
**Source URL:** [https://www.vltc.com.mt/tournament.aspx?id=87](https://www.vltc.com.mt/tournament.aspx?id=87)
**Extraction method:** HTTP scrape — `tournament.aspx?id=87` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:55 UTC

## Files in this folder

- `Rennie Tonna Samsung Team T'ment 2019.xlsx` (Google Sheet ID `1QXuosFXS3W0k8gDl-nyC7u0s0aFk6FJzd4MFGQdbEoU`, sha256 `6b9103a34439…`)
- `raw/detail-page.html` — original HTML of the tournament detail page at scrape time.

## Provenance

This folder contains data extracted automatically from the VLTC public tournament archive
by `scripts/scraper/vltc.py`. The detail page is captured as raw HTML for audit purposes;
the `.xlsx` files are downloaded via Google Sheets' public `export?format=xlsx` endpoint.

To re-extract: `python scripts/scraper/vltc.py download` (idempotent — only re-writes
files whose Google Sheet content has changed).
