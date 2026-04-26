"""Rank a roster of players against the current phase0 ratings DB.

Reads `Players List.xlsx` (sheets `Men`, `Ladies`), looks up each name in
`scripts/phase0/phase0.sqlite` (canonical_name first, then player_aliases,
both case-insensitive), and emits both a text leaderboard (stdout) and a
self-contained HTML page next to the script (`ranking.html`).

Mirrors the column semantics of `scripts/phase0/cli.py:_print_rank_table`
but scoped to the roster — not the global player set.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import html as _html
import sqlite3
from pathlib import Path

import openpyxl

REPO = Path(__file__).resolve().parents[2]
# Match generate_site.py: production DB lives at the repo root (the one in
# scripts/phase0/ is a smaller dev/testing copy left over from earlier work).
DB = REPO / "phase0.sqlite"
ROSTER = REPO / "_ANALYSIS_" / "NewTournamentRanking" / "Players List.xlsx"
HTML_OUT = REPO / "_ANALYSIS_" / "NewTournamentRanking" / "ranking.html"

CHAMPION_MODEL = "openskill_pl"  # matches scripts/phase0/rating.py:CHAMPION_MODEL

# Live deployment of the per-player profile pages (gh-pages branch).
# We link to it absolute so this HTML works wherever it lives.
PLAYER_PAGE_BASE = "https://devkurtc.github.io/wks-social-tennis-rankings-malta/players"


def read_roster(path: Path) -> dict[str, list[str]]:
    """Return {'Men': [...], 'Ladies': [...]}; rosters are de-duped, order-preserving."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out: dict[str, list[str]] = {}
    for sheet_name in ("Men", "Ladies"):
        ws = wb[sheet_name]
        seen: set[str] = set()
        names: list[str] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue
            for col in (0, 2):
                if col + 1 >= len(row):
                    continue
                no, name = row[col], row[col + 1]
                if not isinstance(name, str):
                    continue
                name = name.strip()
                if not name or name.lower().startswith("reserve"):
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                names.append(name)
        out[sheet_name] = names
    return out


def name_order_variants(name: str) -> list[str]:
    """Return plausible name-order variants for a roster name.

    The DB has some players stored as 'Lastname Firstname' (uppercase, from
    team-tournament parsers) and others as 'Firstname Lastname' (title case,
    from older parsers). To bridge that gap when the exact lookup fails, try
    rotating the words.
    """
    parts = name.split()
    if len(parts) < 2:
        return []
    variants: list[str] = []
    # 2 words: 'A B' → 'B A'
    # 3 words: 'A B C' → 'B C A' (last-name-first → first-name-first) and 'C A B' (the reverse)
    if len(parts) == 2:
        variants.append(f"{parts[1]} {parts[0]}")
    elif len(parts) == 3:
        variants.append(f"{parts[2]} {parts[0]} {parts[1]}")
        variants.append(f"{parts[1]} {parts[2]} {parts[0]}")
    elif len(parts) == 4:
        # 'Spiteri Willets Andrew Foo' patterns are rare; try moving last word to front
        variants.append(f"{parts[3]} {parts[0]} {parts[1]} {parts[2]}")
        variants.append(f"{parts[2]} {parts[3]} {parts[0]} {parts[1]}")
    return variants


def lookup_player(cur: sqlite3.Cursor, name: str) -> dict | None:
    """Resolve a roster name → rating row.

    Strategy (case-insensitive at every step):
      1. Exact match on `players.canonical_name`.
      2. Exact match on `player_aliases.raw_name`.
      3. Word-order rotations of the roster name (covers the 'Lastname Firstname'
         ↔ 'Firstname Lastname' inconsistency between parser families).
    Returns None if no strategy resolves.
    """
    sql_base = """
        SELECT p.id, p.canonical_name, p.gender, r.mu, r.sigma, r.n_matches,
            (
                SELECT pta.class_label
                FROM player_team_assignments pta
                JOIN tournaments t ON t.id = pta.tournament_id
                WHERE pta.player_id = p.id
                ORDER BY t.year DESC, t.id DESC
                LIMIT 1
            ) AS captain_class,
            (
                SELECT MAX(m.played_on)
                FROM rating_history rh
                JOIN matches m ON m.id = rh.match_id
                WHERE rh.player_id = p.id AND rh.model_name = ?
            ) AS last_played
        FROM players p
        LEFT JOIN ratings r ON r.player_id = p.id AND r.model_name = ?
        WHERE p.merged_into_id IS NULL
    """

    row = cur.execute(
        sql_base + " AND LOWER(p.canonical_name) = LOWER(?)",
        (CHAMPION_MODEL, CHAMPION_MODEL, name),
    ).fetchone()
    match_kind = "canonical"
    if row is None:
        row = cur.execute(
            sql_base
            + " AND p.id IN (SELECT player_id FROM player_aliases "
            "  WHERE LOWER(raw_name) = LOWER(?)) LIMIT 1",
            (CHAMPION_MODEL, CHAMPION_MODEL, name),
        ).fetchone()
        match_kind = "alias"
    if row is None:
        # Word-order rotations
        for variant in name_order_variants(name):
            row = cur.execute(
                sql_base + " AND LOWER(p.canonical_name) = LOWER(?)",
                (CHAMPION_MODEL, CHAMPION_MODEL, variant),
            ).fetchone()
            if row:
                match_kind = f"reorder→{variant!r}"
                break
            row = cur.execute(
                sql_base
                + " AND p.id IN (SELECT player_id FROM player_aliases "
                "  WHERE LOWER(raw_name) = LOWER(?)) LIMIT 1",
                (CHAMPION_MODEL, CHAMPION_MODEL, variant),
            ).fetchone()
            if row:
                match_kind = f"reorder-alias→{variant!r}"
                break
    if row is None:
        return None

    pid, canonical, gender, mu, sigma, n, cls, last = row
    return {
        "roster_name": name,
        "match_kind": match_kind,
        "id": pid,
        "canonical": canonical,
        "gender": gender,
        "mu": mu,
        "sigma": sigma,
        "n": n,
        "class": cls,
        "last": last,
    }


def fuzzy_candidates(cur: sqlite3.Cursor, name: str, limit: int = 3) -> list[str]:
    all_names = [
        r[0]
        for r in cur.execute(
            "SELECT canonical_name FROM players WHERE merged_into_id IS NULL"
        ).fetchall()
    ]
    return difflib.get_close_matches(name, all_names, n=limit, cutoff=0.6)


def proposed_class_label(rank_idx: int, group_size: int = 6, slots_per_tier: int = 4) -> str:
    """A1, A2, ..., A4, B1, ..., B4, C1, ... from 0-indexed rank.

    With 6 captains: 6 players share each slot, slot advances every 6 ranks,
    tier advances every 24 ranks.
    """
    slot_idx = rank_idx // group_size
    tier_idx = slot_idx // slots_per_tier
    return f"{chr(ord('A') + tier_idx)}{(slot_idx % slots_per_tier) + 1}"


def print_section(title: str, hits: list[dict], misses: list[tuple[str, list[str]]]) -> None:
    print(f"\n{'=' * 96}\n{title}\n{'=' * 96}")

    rated = [h for h in hits if h["mu"] is not None]
    unrated = [h for h in hits if h["mu"] is None]

    rated.sort(key=lambda h: -(h["mu"] - 3 * h["sigma"]))

    print(
        f"\n  Rated: {len(rated)}    In DB but no rating: {len(unrated)}    "
        f"Not found in DB: {len(misses)}    Total in roster: {len(rated) + len(unrated) + len(misses)}\n"
    )
    if rated:
        print(
            f"  {'#':>3}  {'Class':<6}  {'Player':<28}  {'μ':>6}  {'σ':>5}  "
            f"{'μ-3σ':>6}  {'n':>3}  {'last':<10}  via"
        )
        print("  " + "-" * 90)
        for i, h in enumerate(rated, 1):
            cons = h["mu"] - 3 * h["sigma"]
            cls = proposed_class_label(i - 1)
            via = "" if h["roster_name"].lower() == h["canonical"].lower() else f"({h['match_kind']})"
            print(
                f"  {i:>3}  {cls:<6}  {h['canonical'][:28]:<28}  "
                f"{h['mu']:>6.2f}  {h['sigma']:>5.2f}  {cons:>6.2f}  "
                f"{h['n']:>3}  {(h['last'] or '?'):<10}  {via}"
            )

    if unrated:
        print(f"\n  In DB but no rating ({len(unrated)}):")
        for h in unrated:
            print(f"    - {h['canonical']}")

    if misses:
        print(f"\n  Not found in DB ({len(misses)}):")
        for name, suggestions in misses:
            sugg = ", ".join(repr(s) for s in suggestions) if suggestions else "(no close match)"
            print(f"    - {name}   →   suggest: {sugg}")


# --- HTML rendering ---------------------------------------------------------
# Inline CSS (subset of scripts/phase0/generate_site.py:CSS) so the file is
# fully self-contained — no dependency on a separate stylesheet.

_INLINE_CSS = """
:root {
  --bg: #0f1115; --fg: #e6e6e6; --muted: #8b96a8; --accent: #4ea1ff;
  --win: #46c281; --loss: #e07a7a; --row-alt: #161a22;
  --card: #1a1f2a; --border: #2a3242;
}
* { box-sizing: border-box; }
html, body { -webkit-text-size-adjust: 100%; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg); color: var(--fg);
  margin: 0; padding: 16px; line-height: 1.45;
}
header { max-width: 1100px; margin: 0 auto 12px auto; }
header h1 { margin: 0 0 4px 0; font-size: 22px; }
header p { margin: 0; color: var(--muted); font-size: 13px; }
main { max-width: 1100px; margin: 0 auto; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.section-head { display: flex; align-items: baseline; gap: 12px; margin: 28px 0 8px; flex-wrap: wrap; }
.section-head h2 { margin: 0; font-size: 18px; }
.section-head .summary { color: var(--muted); font-size: 13px; }
.pill { display: inline-block; background: var(--card); border: 1px solid var(--border);
        padding: 2px 8px; border-radius: 999px; font-size: 12px; color: var(--muted); }
.pill.ok { color: var(--win); border-color: rgba(70,194,129,0.4); }
.pill.warn { color: #d6b46a; border-color: rgba(214,180,106,0.4); }
.pill.miss { color: var(--loss); border-color: rgba(224,122,122,0.4); }
.table-wrap {
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  background: var(--card); border-radius: 8px; margin-bottom: 8px;
}
table { width: 100%; border-collapse: collapse; font-size: 13px; background: var(--card); }
th, td { padding: 7px 10px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { background: #20283a; color: var(--muted); font-weight: 600; }
tbody tr:nth-child(even) { background: var(--row-alt); }
tbody tr:hover { background: #21283a; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.cls { font-weight: 600; color: var(--accent); }
.muted { color: var(--muted); }
.tag {
  display: inline-block; background: var(--bg); color: var(--muted);
  padding: 1px 6px; border-radius: 4px; font-size: 11px; margin-right: 4px;
}
.player-link { color: var(--fg); }
.player-link:hover { color: var(--accent); }
ul.plain { list-style: none; padding: 0; margin: 0; columns: 2; column-gap: 24px; }
ul.plain li { padding: 4px 0; border-bottom: 1px solid var(--border); break-inside: avoid; }
.legend { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
          padding: 12px 14px; margin: 12px 0 20px; font-size: 13px; color: var(--muted); }
.legend strong { color: var(--fg); }
footer { margin: 32px auto; max-width: 1100px; color: var(--muted); font-size: 12px; }
@media (max-width: 700px) {
  body { padding: 10px; }
  ul.plain { columns: 1; }
  th, td { padding: 6px 8px; font-size: 12px; }
  /* Hide low-value columns on the rated table */
  table.rated th:nth-child(5),  /* μ */
  table.rated td:nth-child(5),
  table.rated th:nth-child(6),  /* σ */
  table.rated td:nth-child(6),
  table.rated th:nth-child(9),  /* last */
  table.rated td:nth-child(9) { display: none; }
}
"""


def _esc(s) -> str:
    return _html.escape("" if s is None else str(s))


def _render_rated_table(rated: list[dict]) -> str:
    body = []
    for i, h in enumerate(rated, 1):
        cons = h["mu"] - 3 * h["sigma"]
        cls = proposed_class_label(i - 1)
        prev_cls = h["class"]
        cls_title = (
            f"previous tournament class: {prev_cls}" if prev_cls
            else "no prior captain class on record"
        )
        link = (
            f'<a class="player-link" href="{PLAYER_PAGE_BASE}/{h["id"]}.html" '
            f'target="_blank" rel="noopener">{_esc(h["canonical"])}</a>'
        )
        # Show roster-name in muted text if the canonical differs (helps spot
        # name-order rewrites the lookup applied).
        if h["roster_name"].strip().lower() != h["canonical"].strip().lower():
            link += f' <span class="muted" title="roster name">({_esc(h["roster_name"])})</span>'
        body.append(
            f'<tr>'
            f'<td class="num">{i}</td>'
            f'<td class="cls" title="{_esc(cls_title)}">{_esc(cls)}</td>'
            f'<td>{link}</td>'
            f'<td class="num"><strong>{cons:.2f}</strong></td>'
            f'<td class="num">{h["mu"]:.2f}</td>'
            f'<td class="num">{h["sigma"]:.2f}</td>'
            f'<td class="num">{h["n"]}</td>'
            f'<td class="num">{_esc(h["last"] or "?")}</td>'
            f'</tr>'
        )
    return f"""
<div class="table-wrap">
<table class="rated">
  <thead><tr>
    <th class="num">#</th><th>Class</th><th>Player</th>
    <th class="num">μ-3σ</th>
    <th class="num">μ</th><th class="num">σ</th>
    <th class="num">n</th>
    <th>Last played</th>
  </tr></thead>
  <tbody>{''.join(body)}</tbody>
</table>
</div>
"""


def _render_section(sheet: str, hits: list[dict], misses: list[tuple[str, list[str]]]) -> str:
    rated = sorted(
        (h for h in hits if h["mu"] is not None),
        key=lambda h: -(h["mu"] - 3 * h["sigma"]),
    )
    unrated = [h for h in hits if h["mu"] is None]
    total = len(rated) + len(unrated) + len(misses)

    parts: list[str] = []
    parts.append(
        f'<div class="section-head">'
        f'<h2>{_esc(sheet)}</h2>'
        f'<span class="summary">'
        f'<span class="pill ok">{len(rated)} rated</span> '
        + (
            f'<span class="pill warn">{len(unrated)} in DB but no rating</span> '
            if unrated else ""
        )
        + f'<span class="pill miss">{len(misses)} not in DB</span> '
        f'<span class="pill">total {total}</span>'
        f'</span></div>'
    )
    if rated:
        parts.append(_render_rated_table(rated))

    if unrated:
        items = "".join(f"<li>{_esc(h['canonical'])}</li>" for h in unrated)
        parts.append(
            f'<h3 class="muted" style="font-size:13px;text-transform:uppercase;'
            f'letter-spacing:0.05em;margin:14px 0 6px;">'
            f'In our DB but unrated ({len(unrated)})</h3>'
            f'<ul class="plain">{items}</ul>'
        )

    if misses:
        items = []
        for name, suggestions in misses:
            sugg = (
                ", ".join(_esc(s) for s in suggestions)
                if suggestions
                else '<span class="muted">no close match</span>'
            )
            items.append(f"<li>{_esc(name)} <span class='muted'>— suggest: {sugg}</span></li>")
        parts.append(
            f'<h3 class="muted" style="font-size:13px;text-transform:uppercase;'
            f'letter-spacing:0.05em;margin:14px 0 6px;">'
            f'Not yet in our system ({len(misses)})</h3>'
            f'<ul class="plain">{"".join(items)}</ul>'
        )
    return "\n".join(parts)


def render_html(
    sections: list[tuple[str, list[dict], list[tuple[str, list[str]]]]],
    *,
    db_last_match: str | None,
    db_match_count: int,
    db_tournament_count: int,
) -> str:
    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    section_html = "\n".join(_render_section(s, h, m) for s, h, m in sections)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<title>VLTC next Tournament (Antes TT) — Roster Ranking</title>
<style>{_INLINE_CSS}</style>
</head>
<body>
<header>
  <h1>VLTC next Tournament (Antes TT)</h1>
  <p>
    Sourced from <code>_ANALYSIS_/NewTournamentRanking/Players List.xlsx</code>
    &middot; ratings from RallyRank (OpenSkill PL, model <code>{_esc(CHAMPION_MODEL)}</code>)
    &middot; generated {generated}.
  </p>
</header>
<main>
  <div class="legend">
    <p style="margin:0 0 6px 0;">
      <strong>How to read this page.</strong> Players are ranked by
      <strong>μ-3σ</strong> — the conservative skill estimate that penalises
      uncertainty (lower σ ⇒ rating you can trust more). Class is the most
      recent captain-assigned slot from a team tournament, when available.
      Click any name for the full match log on the live RallyRank site.
    </p>
    <p style="margin:0;">
      <strong>Coverage.</strong> The current Phase-0 DB has
      <strong>{db_match_count}</strong> matches across
      <strong>{db_tournament_count}</strong> tournaments
      (last match: <strong>{_esc(db_last_match or "?")}</strong>). Players whose
      first-ever tournament is this one will appear in the
      <em>Not yet in our system</em> list — they have no rating yet.
    </p>
  </div>
  {section_html}
</main>
<footer>
  Generated by <code>_ANALYSIS_/NewTournamentRanking/rank_roster.py</code> from
  <code>scripts/phase0/phase0.sqlite</code>. Re-run the script after re-rating
  the DB (<code>python3 scripts/phase0/cli.py rate</code>) to refresh.
</footer>
</body>
</html>
"""


def _db_summary(con: sqlite3.Connection) -> tuple[str | None, int, int]:
    last = con.execute(
        "SELECT MAX(played_on) FROM matches WHERE superseded_by_run_id IS NULL"
    ).fetchone()[0]
    n_matches = con.execute(
        "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
    ).fetchone()[0]
    n_tournaments = con.execute(
        "SELECT COUNT(DISTINCT tournament_id) FROM matches WHERE superseded_by_run_id IS NULL"
    ).fetchone()[0]
    return last, n_matches, n_tournaments


# --- Main -------------------------------------------------------------------


def main() -> None:
    roster = read_roster(ROSTER)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    try:
        sections: list[tuple[str, list[dict], list[tuple[str, list[str]]]]] = []
        for sheet, names in roster.items():
            hits: list[dict] = []
            misses: list[tuple[str, list[str]]] = []
            for n in names:
                r = lookup_player(cur, n)
                if r is None:
                    misses.append((n, fuzzy_candidates(cur, n)))
                else:
                    hits.append(r)
            print_section(f"{sheet}  —  roster size {len(names)}", hits, misses)
            sections.append((sheet, hits, misses))

        last, n_matches, n_tour = _db_summary(con)
        html_doc = render_html(
            sections,
            db_last_match=last,
            db_match_count=n_matches,
            db_tournament_count=n_tour,
        )
    finally:
        con.close()

    HTML_OUT.write_text(html_doc, encoding="utf-8")
    print(f"\n→ wrote {HTML_OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
