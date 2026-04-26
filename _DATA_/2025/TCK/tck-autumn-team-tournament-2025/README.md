# TCK AUTUMN TEAM TOURNAMENT | 2025

**Club:** Tennis Club Kordin (TCK), Malta
**Year:** 2025
**Source:** Club website
**Source URL:** [https://www.tennisclubkordin.com/tournament-archive](https://www.tennisclubkordin.com/tournament-archive)
**Source spreadsheet:** [docs.google.com/spreadsheets/d/146SStSf0_JkjVLHf-Rpmy0-zi_noTpMAtVw7mvDUOkI](https://docs.google.com/spreadsheets/d/146SStSf0_JkjVLHf-Rpmy0-zi_noTpMAtVw7mvDUOkI)
**Extraction method:** HTTP scrape — `tournament-archive` page parsed for `<a aria-label>` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:44 UTC

## Files in this folder

- `TCK AUTUMN TEAM TOURNAMENT 2025.xlsx` (sha256 `6fb569b7db9c…`)
- `raw/archive-page.html` — full archive HTML at scrape time (single page lists every TCK tournament).

## Provenance

Extracted from the public TCK tournament archive by `scripts/scraper/tck.py`.
The site is built on Wix; tournament-to-sheet mapping is recovered from the
`aria-label` attribute on each Wix button.

To re-extract: `python scripts/scraper/tck.py all` (idempotent).
