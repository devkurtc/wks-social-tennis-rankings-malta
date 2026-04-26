#!/usr/bin/env python3
"""Reorganize existing local data files in `_DATA_/VLTC/` into the
year/club/tournament hierarchy used by the scrapers.

What it does:
  - Walks `_DATA_/VLTC/*.xlsx` and `_DATA_/VLTC/Results Sheet/*.xlsx` (the
    legacy flat layout).
  - For each file, infers `(year, tournament-slug)` from the filename.
  - Moves the file (via `git mv` if tracked, plain `os.rename` otherwise) to
    `_DATA_/<year>/VLTC/<slug>/<original-filename>`.
  - Generates / appends a per-tournament README documenting the source as
    "local file upload" (with the file's mtime as the upload date).
  - Files that already share a directory with scraped data sit happily
    alongside — both are valid sources of the same tournament.
  - Templates (any filename containing 'template') go to `_DATA_/_templates/`.
  - Files with no detectable year go to `_DATA_/_unsorted/` with an explanation
    in the per-folder README.

Run:
    python scripts/scraper/organize.py [--dry-run]

By default it moves files. Pass --dry-run to see what would happen.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "_DATA_"
LEGACY_VLTC = DATA_DIR / "VLTC"
TEMPLATES_DIR = DATA_DIR / "_templates"
UNSORTED_DIR = DATA_DIR / "_unsorted"
CLUB = "VLTC"

YEAR_RE = re.compile(r"\b(20\d{2})\b")


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:80]


CLUB_PREFIXES = {
    "TCK": "TCK",  # TCK CHOSEN TOUNAMENT, TCK SINGLES TOURNAMENT, TCK AUTUMN
    # Add more clubs here as we encounter them.
}


def infer_club(filename: str) -> str:
    """Pick a club from a filename prefix; default VLTC (the legacy data folder).
    Examples:
      'TCK CHOSEN TOUNAMENT 2024.xlsx' → TCK
      'San Michel Results 2026.xlsx'  → VLTC (default — VLTC hosts San Michel)
    """
    upper = filename.upper().lstrip()
    for prefix, club in CLUB_PREFIXES.items():
        if upper.startswith(prefix):
            return club
    return CLUB  # default VLTC


def infer_tournament(filename: str) -> tuple[int | None, str | None]:
    """Return (year, slug) or (None, None) for unrecognized filenames."""
    stem = Path(filename).stem.strip()  # strip leading/trailing whitespace
    if "template" in stem.lower():
        return None, None  # template — handled separately
    m = YEAR_RE.search(stem)
    if not m:
        return None, None
    year = int(m.group(1))
    # Build slug from the WHOLE stem — preserves tournament identity. First strip
    # noise BEFORE slugifying (so we work on words, not hyphen-runs).
    cleaned = stem
    for noise in (
        "draws and results", "result sheet", "results with sets",
        "with sets", "imo joe", "results", "draws",
    ):
        cleaned = re.sub(rf"\b{re.escape(noise)}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\(\d+\)\s*", " ", cleaned)  # strip "(1)", "(2)" etc.
    slug = slugify(cleaned)
    return year, slug


def is_git_tracked(path: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            cwd=REPO_ROOT, capture_output=True, check=False,
        )
        return r.returncode == 0
    except Exception:
        return False


def move_file(src: Path, dst: Path, dry_run: bool) -> None:
    """git mv if tracked, otherwise os.rename. Idempotent if src == dst."""
    if src.resolve() == dst.resolve():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        print(f"  [DRY] mv {src.relative_to(REPO_ROOT)}  →  {dst.relative_to(REPO_ROOT)}")
        return
    if is_git_tracked(src):
        subprocess.run(["git", "mv", str(src), str(dst)], cwd=REPO_ROOT, check=True)
    else:
        shutil.move(str(src), str(dst))


def write_or_append_readme(tournament_dir: Path, original_name: str, mtime: datetime) -> None:
    """If README exists (likely from scrape), append a 'Local file' section.
    Otherwise, write a fresh local-file README."""
    readme_path = tournament_dir / "README.md"
    addendum = f"""
## Local file upload

- `{original_name}` — provided as a local file (in `_DATA_/VLTC/` before the
  reorganization). File mtime: {mtime.strftime('%Y-%m-%d %H:%M %Z')}.

This local copy is an additional source for this tournament; the parser
dispatcher in `scripts/phase0/cli.py` substring-matches the filename to pick a
parser, so both this file and any scraped versions can be loaded with `cli.py
load --file <path>`.
"""
    if readme_path.exists():
        existing = readme_path.read_text()
        if "## Local file upload" in existing:
            return  # already documented
        readme_path.write_text(existing.rstrip() + "\n" + addendum)
    else:
        # Pure local-file README (no scrape companion)
        slug = tournament_dir.name
        year_dir = tournament_dir.parent.parent.name
        readme = f"""# {slug.replace('-', ' ').title()}

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** {year_dir}
**Source:** Local file upload
**Source filename:** `{original_name}`
**File mtime:** {mtime.strftime('%Y-%m-%d %H:%M %Z')}
**Last reorganized:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

## Files in this folder

- `{original_name}` — original local file moved here from the legacy flat
  `_DATA_/VLTC/` layout.

## Provenance

This file was present in the project's `_DATA_/VLTC/` directory before the
year/club/tournament reorganization (see project memory: VLTC files are
sourced from the public club website but were committed locally for offline
processing). No automated scrape provenance is recorded for this file —
the source date is the file mtime.

If a `tournament.aspx?id=N` page exists for this tournament on
www.vltc.com.mt, run `python scripts/scraper/vltc.py all` to fetch the live
copy alongside this local one.
"""
        readme_path.write_text(readme)


def organize(dry_run: bool = False) -> None:
    """Walk legacy _DATA_/VLTC/ and reorganize."""
    if not LEGACY_VLTC.exists():
        print(f"[organize] {LEGACY_VLTC.relative_to(REPO_ROOT)} not found — nothing to do")
        return

    moved = 0
    skipped_template = 0
    skipped_unsorted = 0
    skipped_lockfile = 0

    candidates: list[Path] = []
    for p in LEGACY_VLTC.iterdir():
        if p.is_file() and p.suffix.lower() in (".xlsx", ".xls"):
            candidates.append(p)
    rs = LEGACY_VLTC / "Results Sheet"
    if rs.exists():
        for p in rs.iterdir():
            if p.is_file() and p.suffix.lower() in (".xlsx", ".xls"):
                candidates.append(p)
    # Skip the scraped/ subdirectory — that's our own scratch area
    candidates.sort()

    for src in candidates:
        name = src.name
        if name.startswith("~$"):
            skipped_lockfile += 1
            continue
        if "template" in name.lower():
            dst = TEMPLATES_DIR / name.strip()
            move_file(src, dst, dry_run)
            skipped_template += 1
            print(f"[template] {name}  →  {dst.relative_to(REPO_ROOT)}")
            continue

        year, slug = infer_tournament(name)
        if year is None:
            dst = UNSORTED_DIR / name.strip()
            move_file(src, dst, dry_run)
            skipped_unsorted += 1
            print(f"[unsorted] {name}  (no year detected)")
            continue

        # Build target directory — club determined by filename prefix
        club = infer_club(name)
        tournament_dir = DATA_DIR / str(year) / club / slug
        # Preserve the original filename verbatim (parser dispatcher matches by
        # substring after lowercasing — e.g. 'Wilson Autumn Results 2020.xlsx'
        # contains 'wilson autumn results' which the dispatcher knows about).
        dst = tournament_dir / name.strip()
        move_file(src, dst, dry_run)
        if not dry_run:
            mtime = datetime.fromtimestamp(dst.stat().st_mtime, tz=timezone.utc)
            write_or_append_readme(tournament_dir, name.strip(), mtime)
        moved += 1
        print(f"[moved   ] {name}  →  {dst.relative_to(REPO_ROOT)}")

    print()
    print(f"Summary: {moved} moved | {skipped_template} templates | "
          f"{skipped_unsorted} unsorted | {skipped_lockfile} lock files skipped")
    if dry_run:
        print("(dry run — no changes made)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dry-run", action="store_true", help="Don't move anything; just print plan.")
    args = p.parse_args(argv)
    organize(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
