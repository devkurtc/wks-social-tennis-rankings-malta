# BENNY VIDAL PKF TEAM TOURNAMENT | 2024

**Club:** Tennis Club Kordin (TCK), Malta
**Year:** 2024
**Source:** Club website
**Source URL:** [https://www.tennisclubkordin.com/tournament-archive](https://www.tennisclubkordin.com/tournament-archive)
**Source spreadsheet:** [docs.google.com/spreadsheets/d/12TiEdcUrwcbM-kl2gwiyg_4x4sAKGypZQQCxGUG_YYU](https://docs.google.com/spreadsheets/d/12TiEdcUrwcbM-kl2gwiyg_4x4sAKGypZQQCxGUG_YYU)
**Extraction method:** HTTP scrape — `tournament-archive` page parsed for `<a aria-label>` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:44 UTC

## Files in this folder

- `BENNY VIDAL PKF TEAM TOURNAMENT 2024.xlsx` (sha256 `66fe096a8a78…`)
- `raw/archive-page.html` — full archive HTML at scrape time (single page lists every TCK tournament).

## Provenance

Extracted from the public TCK tournament archive by `scripts/scraper/tck.py`.
The site is built on Wix; tournament-to-sheet mapping is recovered from the
`aria-label` attribute on each Wix button.

To re-extract: `python scripts/scraper/tck.py all` (idempotent).
