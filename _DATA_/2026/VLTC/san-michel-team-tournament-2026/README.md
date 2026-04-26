# SAN MICHEL TEAM TOURNAMENT 2026

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** 2026
**Source:** Club website
**Source URL:** [https://www.vltc.com.mt/tournament.aspx?id=20151](https://www.vltc.com.mt/tournament.aspx?id=20151)
**Extraction method:** HTTP scrape — `tournament.aspx?id=20151` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:56 UTC

## Files in this folder

- `SAN MICHEL TEAM TOURNAMENT 2026.xlsx` (Google Sheet ID `1QCwSDRECLq_YB5bX8PvmVuarjaByHHAY`, sha256 `a448fc18fd87…`)
- `raw/detail-page.html` — original HTML of the tournament detail page at scrape time.

## Provenance

This folder contains data extracted automatically from the VLTC public tournament archive
by `scripts/scraper/vltc.py`. The detail page is captured as raw HTML for audit purposes;
the `.xlsx` files are downloaded via Google Sheets' public `export?format=xlsx` endpoint.

To re-extract: `python scripts/scraper/vltc.py download` (idempotent — only re-writes
files whose Google Sheet content has changed).

## Local file upload

- `Selection for day.xlsx` — local file moved here from `_DATA_/_unsorted/` after the
  reorganization confirmed its year. File mtime: 2026-04-11 02:34 UTC.

The parser dispatcher in `scripts/phase0/cli.py` matches on filename substring
after lowercasing, so this file can be loaded directly with `cli.py load --file <path>`.
