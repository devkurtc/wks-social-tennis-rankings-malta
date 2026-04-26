#!/usr/bin/env python3
"""TCK (Tennis Club Kordin) tournament archive scraper.

Pulls every tournament listed on https://www.tennisclubkordin.com/tournament-archive,
extracts the embedded Google Sheet links, and downloads each as .xlsx into
_DATA_/<year>/TCK/<slug>/source.xlsx.

Architecture: TCK runs on Wix. The archive page is server-rendered HTML with
plain-HTTP-accessible Google Sheet links — each rendered as `<a aria-label="<name>"
href="...spreadsheets/d/<id>...">`. No anti-bot guard, no JavaScript needed.

Usage:
    python scripts/scraper/tck.py all

Outputs:
  _DATA_/_clubs/TCK/manifest.json                    — tournament list + metadata
  _DATA_/<year>/TCK/<slug>/<slug>.xlsx               — Google Sheet as xlsx
  _DATA_/<year>/TCK/<slug>/raw/archive-page.html     — raw archive HTML (full page,
                                                       same for every tournament — kept
                                                       for audit / re-extraction)
  _DATA_/<year>/TCK/<slug>/README.md                 — extraction provenance
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ARCHIVE_URL = "https://www.tennisclubkordin.com/tournament-archive"
GSHEET_EXPORT = "https://docs.google.com/spreadsheets/d/{id}/export?format=xlsx"

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "_DATA_"
CLUB = "TCK"
MANIFEST_PATH = DATA_DIR / "_clubs" / CLUB / "manifest.json"

YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Pair (aria-label, sheet-id) — both orderings of attributes
PAIR_RE_HREF_FIRST = re.compile(
    r'<a[^>]+href="(https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)[^"]*)"[^>]*aria-label="([^"]+)"',
    re.S,
)
PAIR_RE_LABEL_FIRST = re.compile(
    r'<a[^>]+aria-label="([^"]+)"[^>]+href="(https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)[^"]*)"',
    re.S,
)


def http_get(url: str, timeout: int = 30) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (2 ** attempt))
    print(f"http_get failed for {url}: {last_err}", file=sys.stderr)
    return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def slugify(title: str) -> str:
    """Filesystem-safe lowercase slug for directory names. Strips the ` | YYYY`
    separator that TCK headings use, but keeps the year as a trailing token."""
    s = title.replace("|", " ").lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:80]


def title_as_filename(title: str) -> str:
    """Convert title to filename PRESERVING spaces (for parser-dispatcher compat).
    Replaces TCK's ` | ` separator with a single space so e.g. 'TCK AUTUMN TEAM
    TOURNAMENT | 2025' becomes 'TCK AUTUMN TEAM TOURNAMENT 2025'."""
    s = title.replace("|", "")
    s = re.sub(r"[\x00-\x1f/]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120]


def extract_tournaments(html: str) -> list[dict]:
    """Return [{title, year, sheet_id}, ...] from the archive HTML."""
    pairs = []
    for m in PAIR_RE_HREF_FIRST.finditer(html):
        pairs.append((m.group(3), m.group(2)))
    for m in PAIR_RE_LABEL_FIRST.finditer(html):
        pairs.append((m.group(1), m.group(3)))
    seen = set()
    out = []
    for title, sheet_id in pairs:
        # Skip duplicates and obvious non-tournaments
        if (title, sheet_id) in seen:
            continue
        seen.add((title, sheet_id))
        # Trust only labels that look tournament-y (e.g., have a year)
        ymatch = YEAR_RE.search(title)
        if not ymatch:
            continue
        out.append({
            "title": title.strip(),
            "year": int(ymatch.group(1)),
            "sheet_id": sheet_id,
        })
    return out


def download_bytes(url: str, dest: Path) -> tuple[bool, str | None]:
    body = http_get(url)
    if body is None:
        return False, None
    new_sha = sha256_bytes(body)
    if dest.exists() and sha256_bytes(dest.read_bytes()) == new_sha:
        return False, new_sha
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return True, new_sha


def write_readme(t: dict, sha: Optional[str], tournament_dir: Path) -> None:
    short_sha = (sha or "")[:12]
    fn = title_as_filename(t["title"])
    readme = f"""# {t['title']}

**Club:** Tennis Club Kordin (TCK), Malta
**Year:** {t['year']}
**Source:** Club website
**Source URL:** [{ARCHIVE_URL}]({ARCHIVE_URL})
**Source spreadsheet:** [docs.google.com/spreadsheets/d/{t['sheet_id']}](https://docs.google.com/spreadsheets/d/{t['sheet_id']})
**Extraction method:** HTTP scrape — `tournament-archive` page parsed for `<a aria-label>` + Google Sheets `export?format=xlsx`
**Last extracted:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

## Files in this folder

- `{fn}.xlsx` (sha256 `{short_sha}…`)
- `raw/archive-page.html` — full archive HTML at scrape time (single page lists every TCK tournament).

## Provenance

Extracted from the public TCK tournament archive by `scripts/scraper/tck.py`.
The site is built on Wix; tournament-to-sheet mapping is recovered from the
`aria-label` attribute on each Wix button.

To re-extract: `python scripts/scraper/tck.py all` (idempotent).
"""
    tournament_dir.mkdir(parents=True, exist_ok=True)
    (tournament_dir / "README.md").write_text(readme)


def cmd_all(args) -> int:
    print(f"[tck] fetching archive page {ARCHIVE_URL}", file=sys.stderr)
    html_bytes = http_get(ARCHIVE_URL)
    if html_bytes is None:
        print("error: could not fetch TCK archive page", file=sys.stderr)
        return 1
    html = html_bytes.decode("utf-8", errors="replace")
    tournaments = extract_tournaments(html)
    print(f"[tck] found {len(tournaments)} tournaments", file=sys.stderr)

    manifest = {
        "club": "Tennis Club Kordin (TCK)",
        "source_url": ARCHIVE_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tournaments": [],
    }

    for t in tournaments:
        slug = slugify(t["title"])
        tournament_dir = DATA_DIR / str(t["year"]) / CLUB / slug
        tournament_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = tournament_dir / "raw"
        raw_dir.mkdir(exist_ok=True)

        # Save raw archive HTML once per tournament (same for all but kept for audit)
        (raw_dir / "archive-page.html").write_bytes(html_bytes)

        # Download the Google Sheet as xlsx — filename uses the title (with spaces)
        # so scripts/phase0/cli.py's substring-match dispatcher still picks it up.
        xlsx_dest = tournament_dir / f"{title_as_filename(t['title'])}.xlsx"
        url = GSHEET_EXPORT.format(id=t["sheet_id"])
        print(f"[tck] {t['title'][:55]:55s} → {xlsx_dest.relative_to(REPO_ROOT)}", file=sys.stderr)
        changed, sha = download_bytes(url, xlsx_dest)

        write_readme(t, sha, tournament_dir)

        manifest["tournaments"].append({
            **t,
            "slug": slug,
            "xlsx_path": str(xlsx_dest.relative_to(REPO_ROOT)),
            "sha256": sha,
            "downloaded_at": datetime.now(timezone.utc).isoformat() if changed else None,
        })
        time.sleep(args.sleep)

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[tck] wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}", file=sys.stderr)
    print(f"[tck] DONE — {len(manifest['tournaments'])} tournaments")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tck-scraper", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("all", help="Fetch archive, download every Google Sheet.")
    pa.add_argument("--sleep", type=float, default=0.5)
    pa.set_defaults(func=cmd_all)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    return build_parser().parse_args(argv).func(build_parser().parse_args(argv))


if __name__ == "__main__":
    args = build_parser().parse_args()
    sys.exit(args.func(args))
