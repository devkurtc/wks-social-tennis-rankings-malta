#!/usr/bin/env python3
"""VLTC tournament scraper.

Pulls every tournament's detail page from www.vltc.com.mt, extracts the embedded
Google Sheet links, and downloads each sheet as .xlsx into _DATA_/VLTC/scraped/.

The site is ASP.NET WebForms with an anti-bot guard on the postback navigation,
but the resulting detail URL `tournament.aspx?id=N` is plain GET-addressable
without session/cookies/JS — so this scraper skips the postback entirely and
probes the numeric ID space directly.

Usage:
    # 1. discover — build manifest of all valid tournament IDs
    python scripts/scraper/vltc.py discover --range 19000:21000 --concurrency 8

    # 2. download — for each tournament in manifest, fetch its Google Sheets
    python scripts/scraper/vltc.py download

    # 3. one-shot (discover + download)
    python scripts/scraper/vltc.py all --range 19000:21000

Idempotent: re-running download skips files whose sha256 matches the manifest.

Outputs land in:
  _DATA_/VLTC/scraped/manifest.json     — tournaments + sheet IDs + file paths
  _DATA_/VLTC/scraped/<year>/<slug>.xlsx — one .xlsx per Google Sheet
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
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
BASE = "https://www.vltc.com.mt"
GSHEET_EXPORT = "https://docs.google.com/spreadsheets/d/{id}/export?format=xlsx"

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "_DATA_"
CLUB = "VLTC"
MANIFEST_PATH = DATA_DIR / "VLTC" / "scraped" / "manifest.json"

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
SHEET_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
TITLE_PREFIX = "Vittoriosa Lawn Tennis Club (Malta) -"


# ─── HTTP helpers ──────────────────────────────────────────────────────────

def http_get(url: str, timeout: int = 20) -> Optional[bytes]:
    """GET a URL with retries. Returns body bytes or None on failure."""
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


# ─── Discovery ─────────────────────────────────────────────────────────────

def parse_detail_page(body: str) -> Optional[dict]:
    """Return {title, year, sheet_ids[]} if body looks like a tournament detail
    page, else None.
    """
    m = TITLE_RE.search(body)
    if not m:
        return None
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    if title.startswith(TITLE_PREFIX):
        title = title[len(TITLE_PREFIX):].strip()
    # Filter: skip "Tournaments" listing page, member area, etc.
    if not title or title.lower() in {"tournaments", "home", "404"}:
        return None
    # Skip pages with no tournament-y content (server returns a tiny placeholder
    # for unused IDs; valid tournament pages are >11000 bytes)
    if len(body) < 11500:
        return None
    sheet_ids = sorted(set(SHEET_RE.findall(body)))
    year_match = YEAR_RE.search(title)
    year = int(year_match.group(1)) if year_match else None
    return {"title": title, "year": year, "sheet_ids": sheet_ids}


def slugify(title: str) -> str:
    """Produce a filesystem-safe, lowercase slug from a tournament title."""
    s = title.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:80]


def title_as_filename(title: str) -> str:
    """Convert a tournament title to a filesystem-safe filename that PRESERVES
    spaces (so the Phase 0 parser dispatcher can substring-match it after lowercasing).
    Strips chars that are problematic on macOS/Linux (nul, slash) but keeps spaces."""
    s = re.sub(r"[\x00-\x1f/]", "", title)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120]


def discover(id_range: range, concurrency: int) -> list[dict]:
    """Probe the ID range. Return list of tournament records (sorted by id)."""
    print(f"[discover] probing {len(id_range)} IDs with concurrency={concurrency}", file=sys.stderr)

    def probe(id_):
        body = http_get(f"{BASE}/tournament.aspx?id={id_}")
        if body is None:
            return None
        info = parse_detail_page(body.decode("utf-8", errors="replace"))
        if not info:
            return None
        return {"id": id_, **info}

    results: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        for i, res in enumerate(ex.map(probe, id_range)):
            if res:
                results.append(res)
            if i and i % 200 == 0:
                print(f"[discover] {i}/{len(id_range)} probed, {len(results)} hits", file=sys.stderr)
    results.sort(key=lambda r: r["id"])
    print(f"[discover] DONE — {len(results)} tournaments found", file=sys.stderr)
    return results


# ─── Manifest ─────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"generated_at": None, "base_url": BASE, "tournaments": []}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[manifest] wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}", file=sys.stderr)


def merge_discovered(manifest: dict, discovered: list[dict]) -> dict:
    """Merge new discovery data into the manifest, preserving file metadata
    from prior runs (sha256, downloaded_at, file_path)."""
    by_id = {t["id"]: t for t in manifest["tournaments"]}
    for d in discovered:
        existing = by_id.get(d["id"], {})
        # Preserve file metadata; replace sheet_ids and metadata
        existing_files = existing.get("files", [])
        files_by_sheet = {f["sheet_id"]: f for f in existing_files}
        new_files = []
        for sid in d["sheet_ids"]:
            if sid in files_by_sheet:
                new_files.append(files_by_sheet[sid])
            else:
                new_files.append({"sheet_id": sid, "downloaded_at": None, "sha256": None, "path": None})
        merged = {**existing, **d, "files": new_files}
        by_id[d["id"]] = merged
    manifest["tournaments"] = sorted(by_id.values(), key=lambda t: t["id"])
    return manifest


# ─── Download ─────────────────────────────────────────────────────────────

def download_bytes(url: str, dest: Path) -> tuple[bool, str | None]:
    """Download bytes to a file path. Idempotent — skips if existing sha matches.
    Returns (changed?, sha256 of content)."""
    body = http_get(url)
    if body is None:
        return False, None
    new_sha = sha256_bytes(body)
    if dest.exists():
        old_sha = sha256_bytes(dest.read_bytes())
        if old_sha == new_sha:
            return False, new_sha
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return True, new_sha


def write_tournament_readme(t: dict, tournament_dir: Path) -> None:
    """Write/update the per-tournament README documenting source + extraction."""
    detail_url = f"{BASE}/tournament.aspx?id={t['id']}"
    files_md = ""
    for f in t["files"]:
        if f.get("path"):
            files_md += f"- `{Path(f['path']).name}` (Google Sheet ID `{f['sheet_id']}`, sha256 `{(f.get('sha256') or '')[:12]}…`)\n"
    if not files_md:
        files_md = "_No data files attached to this tournament on the source site._\n"
    raw_note = "- `raw/detail-page.html` — original HTML of the tournament detail page at scrape time."
    readme = f"""# {t['title']}

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** {t.get('year') or 'unknown'}
**Source:** Club website
**Source URL:** [{detail_url}]({detail_url})
**Extraction method:** HTTP scrape — `tournament.aspx?id={t['id']}` + Google Sheets `export?format=xlsx`
**Last extracted:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

## Files in this folder

{files_md}{raw_note}

## Provenance

This folder contains data extracted automatically from the VLTC public tournament archive
by `scripts/scraper/vltc.py`. The detail page is captured as raw HTML for audit purposes;
the `.xlsx` files are downloaded via Google Sheets' public `export?format=xlsx` endpoint.

To re-extract: `python scripts/scraper/vltc.py download` (idempotent — only re-writes
files whose Google Sheet content has changed).
"""
    tournament_dir.mkdir(parents=True, exist_ok=True)
    (tournament_dir / "README.md").write_text(readme)


def download_all(manifest: dict, sleep_s: float = 0.5) -> int:
    """Walk the manifest. For each tournament: create _DATA_/<year>/VLTC/<slug>/,
    download raw HTML + every Google Sheet, write README. Returns files-changed count.
    """
    n_changed = 0
    for t in manifest["tournaments"]:
        year = t.get("year") or "unknown"
        slug = slugify(t["title"])
        tournament_dir = DATA_DIR / str(year) / CLUB / slug
        tournament_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = tournament_dir / "raw"
        raw_dir.mkdir(exist_ok=True)

        # Save raw detail-page HTML
        html_url = f"{BASE}/tournament.aspx?id={t['id']}"
        html_dest = raw_dir / "detail-page.html"
        html_changed, _ = download_bytes(html_url, html_dest)
        if html_changed:
            n_changed += 1

        # Download each Google Sheet — filename uses the *title* (with spaces)
        # so scripts/phase0/cli.py's substring-match dispatcher still picks it up.
        title_fn = title_as_filename(t["title"])
        for i, file_entry in enumerate(t["files"]):
            sheet_id = file_entry["sheet_id"]
            suffix = "" if len(t["files"]) == 1 else f" - sheet {i+1}"
            filename = f"{title_fn}{suffix}.xlsx"
            dest = tournament_dir / filename
            url = GSHEET_EXPORT.format(id=sheet_id)
            print(f"[download] id={t['id']:5d} {t['title'][:50]:50s} → {dest.relative_to(REPO_ROOT)}", file=sys.stderr)
            changed, sha = download_bytes(url, dest)
            file_entry["path"] = str(dest.relative_to(REPO_ROOT))
            file_entry["sha256"] = sha
            if changed:
                file_entry["downloaded_at"] = datetime.now(timezone.utc).isoformat()
                n_changed += 1
            time.sleep(sleep_s)

        # Write/refresh per-tournament README
        write_tournament_readme(t, tournament_dir)

    return n_changed


# ─── CLI ───────────────────────────────────────────────────────────────────

def parse_range(spec: str) -> range:
    a, b = spec.split(":")
    return range(int(a), int(b))


def cmd_discover(args) -> int:
    rng = parse_range(args.range)
    discovered = discover(rng, args.concurrency)
    manifest = load_manifest()
    manifest = merge_discovered(manifest, discovered)
    save_manifest(manifest)
    print(f"[discover] {len(discovered)} tournaments in manifest")
    return 0


def cmd_download(args) -> int:
    manifest = load_manifest()
    if not manifest["tournaments"]:
        print("error: no tournaments in manifest. Run `discover` first.", file=sys.stderr)
        return 1
    n = download_all(manifest, sleep_s=args.sleep)
    save_manifest(manifest)
    total = sum(len(t["files"]) for t in manifest["tournaments"])
    print(f"[download] {n} files written/updated, {total} total tracked")
    return 0


def cmd_all(args) -> int:
    rc = cmd_discover(args)
    if rc != 0:
        return rc
    return cmd_download(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vltc-scraper", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser("discover", help="Probe ID range and (re)build manifest.")
    pd.add_argument("--range", default="19000:21000", help="ID range (inclusive:exclusive). Default: 19000:21000")
    pd.add_argument("--concurrency", type=int, default=8, help="HTTP concurrency. Default: 8")
    pd.set_defaults(func=cmd_discover)

    pdl = sub.add_parser("download", help="Download Google Sheets per manifest.")
    pdl.add_argument("--sleep", type=float, default=0.5, help="Seconds between downloads. Default: 0.5")
    pdl.set_defaults(func=cmd_download)

    pa = sub.add_parser("all", help="discover + download in one shot.")
    pa.add_argument("--range", default="19000:21000")
    pa.add_argument("--concurrency", type=int, default=8)
    pa.add_argument("--sleep", type=float, default=0.5)
    pa.set_defaults(func=cmd_all)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
