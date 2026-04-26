#!/usr/bin/env python3
"""Generate a static HTML site from the Phase-0 SQLite DB.

Output:
    site/
        index.html                       — leaderboard (sortable, men + ladies)
        styles.css                       — shared CSS
        players/<id>.html                — per-player page
        tournaments/<slug>.html          — roster ranking pages (one per entry
                                           in TOURNAMENT_ROSTERS)

Run from project root:
    python3 scripts/phase0/generate_site.py
"""

from __future__ import annotations

import difflib
import hashlib
import html
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = "phase0.sqlite"
OUT_DIR = Path("site")
MODEL = "openskill_pl"

# Tournament roster pages. Each entry produces site/tournaments/<slug>.html
# from the named .xlsx (sheets `Men` and `Ladies`, two name-columns each).
# Add a new dict to publish another roster page.
TOURNAMENT_ROSTERS: list[dict] = [
    {
        "slug": "antes-tt-2026",
        "title": "VLTC next Tournament (Antes TT)",
        "menu_label": "Antes TT 2026 (roster)",
        "roster_xlsx": "_ANALYSIS_/NewTournamentRanking/Players List.xlsx",
        "subtitle": (
            "Pre-tournament roster ranking. Players ordered by μ-3σ "
            "(conservative skill estimate). Class is the proposed slot for "
            "this tournament — 6 captains, so every 6 ranked players advance "
            "to the next slot (A1→A2→A3→A4→B1→…). Hover a class to see the "
            "player's previous-tournament class for reference."
        ),
    },
]


def esc(s) -> str:
    return html.escape("" if s is None else str(s))


def write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# --- CSS ---------------------------------------------------------------------

CSS = """
:root {
  --bg: #0f1115;
  --fg: #e6e6e6;
  --muted: #8b96a8;
  --accent: #4ea1ff;
  --win: #46c281;
  --loss: #e07a7a;
  --row-alt: #161a22;
  --card: #1a1f2a;
  --border: #2a3242;
}
* { box-sizing: border-box; }
html, body { -webkit-text-size-adjust: 100%; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg); color: var(--fg);
  margin: 0; padding: 16px 24px; line-height: 1.45;
}
/* Layout used to be capped at 1200px which forced horizontal scroll on the
   wide match-log tables. Use the full viewport width (with body padding) so
   tables can lay out all columns naturally on desktop. Prose elements
   (h1/p) get their own readable max-width below. */
header { margin: 0 0 12px 0; }
header h1 { margin: 0 0 4px 0; font-size: 20px; max-width: 1100px; }
header p { margin: 0; color: var(--muted); font-size: 13px; max-width: 1100px; }
nav.topnav {
  margin: 0 0 12px 0;
  display: flex; gap: 6px; flex-wrap: wrap; align-items: center;
  padding: 8px 0; border-bottom: 1px solid var(--border);
}
nav.topnav a {
  color: var(--muted);
  padding: 6px 10px; border-radius: 6px;
  font-size: 13px; font-weight: 500;
}
nav.topnav a:hover { background: var(--card); color: var(--fg); text-decoration: none; }
nav.topnav a.active {
  background: var(--card); color: var(--fg);
  border: 1px solid var(--border);
}
nav.topnav .sep { color: var(--border); }
main { width: 100%; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.controls { display: flex; gap: 8px; align-items: center; margin: 12px 0; flex-wrap: wrap; }
.controls input, .controls select {
  background: var(--card); color: var(--fg); border: 1px solid var(--border);
  padding: 8px 10px; border-radius: 6px; font-size: 14px;
  min-height: 38px;
}
.controls input { flex: 1 1 200px; min-width: 140px; }

/* Wrap every table in a div.table-wrap for horizontal scroll on mobile.
   Without this, wide tables blow out the viewport. */
.table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  background: var(--card);
  border-radius: 8px;
  margin-bottom: 8px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: var(--card);
  /* No overflow:hidden here; the scroll container handles clipping.
     overflow:hidden also breaks position:sticky on <th>. */
}
th, td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { background: #20283a; color: var(--muted); font-weight: 600;
     position: sticky; top: 0; cursor: pointer; user-select: none; }
th:hover { color: var(--fg); }
tbody tr:nth-child(even) { background: var(--row-alt); }
tbody tr:hover { background: #21283a; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.cls { font-weight: 600; color: var(--accent); }
.win { color: var(--win); }
.loss { color: var(--loss); }
.gender-M { color: #6cb3ff; }
.gender-F { color: #ff8db5; }
.player-link { color: var(--fg); }
.player-link:hover { color: var(--accent); }
.tag {
  display: inline-block; background: var(--bg); color: var(--muted);
  padding: 1px 6px; border-radius: 4px; font-size: 11px; margin-right: 4px;
}
.muted { color: var(--muted); }
footer { margin: 24px 0; color: var(--muted); font-size: 12px; max-width: 1100px; }

/* Player page */
.profile-head { display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; margin-bottom: 12px; }
.profile-head .name { font-size: 26px; font-weight: 600; margin: 0 0 4px 0; line-height: 1.1; }
.profile-head .meta { color: var(--muted); font-size: 13px; }
.stat-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
  gap: 6px; margin-bottom: 16px;
}
.stat {
  background: var(--card); border: 1px solid var(--border); padding: 10px 8px;
  border-radius: 6px; text-align: center;
}
.stat .label { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; }
.stat .value { font-size: 18px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
.section-title { margin: 20px 0 8px 0; font-size: 14px; color: var(--muted);
                 text-transform: uppercase; letter-spacing: 0.05em; }
.chart {
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px;
}
.chart svg { width: 100%; height: auto; display: block; }
.score { font-variant-numeric: tabular-nums; font-family: ui-monospace, "SF Mono", Menlo, monospace; }

/* Form badges (per-match W/L history) */
.form { display: inline-flex; gap: 3px; flex-wrap: wrap; }
.form .b {
  display: inline-block;
  width: 22px; height: 22px; line-height: 22px; text-align: center;
  border-radius: 4px; font-size: 11px; font-weight: 700;
  font-family: ui-monospace, monospace;
}
.form .b.w { background: rgba(70, 194, 129, 0.18); color: var(--win); }
.form .b.l { background: rgba(224, 122, 122, 0.18); color: var(--loss); }

/* Mobile tweaks */
@media (max-width: 700px) {
  body { padding: 10px; }
  header h1 { font-size: 18px; }
  .profile-head .name { font-size: 22px; }
  th, td { padding: 6px 8px; font-size: 12px; }
  .stat .value { font-size: 16px; }
  /* Hide low-value columns on the leaderboard for narrow screens */
  table.leaderboard th:nth-child(5),     /* μ */
  table.leaderboard td:nth-child(5),
  table.leaderboard th:nth-child(6),     /* σ */
  table.leaderboard td:nth-child(6),
  table.leaderboard th:nth-child(11),    /* games */
  table.leaderboard td:nth-child(11),
  table.leaderboard th:nth-child(12),    /* g% */
  table.leaderboard td:nth-child(12) { display: none; }
}
"""

# Cache-busting fingerprint for styles.css. GH Pages caches assets for 10 min;
# without a query-string version, browsers may serve the old CSS even after a
# fresh deploy. Recomputed automatically every time the CSS changes.
CSS_VERSION = hashlib.sha1(CSS.encode("utf-8")).hexdigest()[:10]


# --- Helpers -----------------------------------------------------------------


def render_nav(rel_root: str, active: str) -> str:
    """Top-of-page navigation bar.

    rel_root  -- prefix for hrefs ('' from index, '../' from sub-pages).
    active    -- which entry to highlight: 'index' or 'tournament:<slug>'.
    """
    parts: list[str] = []
    cls_index = ' class="active"' if active == "index" else ""
    parts.append(f'<a href="{rel_root}index.html"{cls_index}>Leaderboard</a>')
    for t in TOURNAMENT_ROSTERS:
        slug = t["slug"]
        label = t["menu_label"]
        cls = ' class="active"' if active == f"tournament:{slug}" else ""
        parts.append('<span class="sep">·</span>')
        parts.append(f'<a href="{rel_root}tournaments/{esc(slug)}.html"{cls}>{esc(label)}</a>')
    return f'<nav class="topnav">{"".join(parts)}</nav>'


def player_filename(pid: int) -> str:
    return f"players/{pid}.html"


def player_link(pid: int, name: str) -> str:
    return f'<a class="player-link" href="players/{pid}.html">{esc(name)}</a>'


def player_link_from_player_page(pid: int, name: str) -> str:
    return f'<a class="player-link" href="{pid}.html">{esc(name)}</a>'


def fetch_neighbour_index(
    conn: sqlite3.Connection,
) -> dict[str, list[dict]]:
    """Return ranked player lists per gender bucket.

    Buckets:
        'M' — men only (μ-3σ desc)
        'F' — ladies only
        'all' — fallback for players with NULL gender

    Each entry: {pid, name, gender, mu, sigma, mu3s, n, wins, captain_class}.
    Order is a stable rank-1 → rank-N within the bucket.
    """
    rows = conn.execute(
        """
        SELECT
            p.id, p.canonical_name, p.gender,
            r.mu, r.sigma, (r.mu - 3*r.sigma) AS mu3s,
            (SELECT COUNT(*) FROM match_sides ms
             JOIN matches m ON m.id = ms.match_id
             WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
               AND m.superseded_by_run_id IS NULL) AS n,
            (SELECT COUNT(*) FROM match_sides ms
             JOIN matches m ON m.id = ms.match_id
             WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
               AND m.superseded_by_run_id IS NULL AND ms.won = 1) AS wins,
            (SELECT pta.class_label
             FROM player_team_assignments pta
             JOIN tournaments t ON t.id = pta.tournament_id
             WHERE pta.player_id = p.id
             ORDER BY t.year DESC, t.id DESC LIMIT 1) AS captain_class
        FROM ratings r
        JOIN players p ON p.id = r.player_id
        WHERE r.model_name = ? AND p.merged_into_id IS NULL
        ORDER BY mu3s DESC
        """,
        (MODEL,),
    ).fetchall()

    buckets: dict[str, list[dict]] = {"M": [], "F": [], "all": []}
    for (pid, name, gender, mu, sigma, mu3s, n, wins, captain_class) in rows:
        if (n or 0) == 0:
            continue
        entry = {
            "pid": pid, "name": name, "gender": gender,
            "mu": mu, "sigma": sigma, "mu3s": mu3s,
            "n": n, "wins": wins, "captain_class": captain_class or "",
        }
        buckets["all"].append(entry)
        if gender in ("M", "F"):
            buckets[gender].append(entry)
    return buckets


def render_neighbours(neighbours: list[dict], me_pid: int) -> str:
    """Render a small "compare with peers" table: 3 above + me + 3 below."""
    pos = next(
        (i for i, e in enumerate(neighbours) if e["pid"] == me_pid), None
    )
    if pos is None:
        return ""
    lo = max(0, pos - 3)
    hi = min(len(neighbours), pos + 4)  # exclusive
    slice_ = neighbours[lo:hi]

    rows = []
    for i, e in enumerate(slice_, start=lo):
        rank = i + 1
        is_me = e["pid"] == me_pid
        n = e["n"]
        wins = e["wins"]
        losses = n - wins
        win_pct = f"{int(round(wins * 100 / n))}%" if n else "—"
        name_cell = (
            f'<strong>{esc(e["name"])}</strong>'
            if is_me
            else f'<a class="player-link" href="{e["pid"]}.html">{esc(e["name"])}</a>'
        )
        diff_cell = ""
        if not is_me:
            me_entry = neighbours[pos]
            d = e["mu3s"] - me_entry["mu3s"]
            cls = "win" if d < 0 else ("loss" if d > 0 else "muted")
            # d > 0 means peer is above me (better) — show as red gap from my POV
            sign = "+" if d >= 0 else ""
            diff_cell = f'<span class="{cls}">{sign}{d:.2f}</span>'
        else:
            diff_cell = '<span class="muted">—</span>'
        rows.append(
            f'<tr{" style=\"background:#22304a\"" if is_me else ""}>'
            f'<td class="num">{rank}</td>'
            f'<td class="cls">{esc(e["captain_class"])}</td>'
            f'<td>{name_cell}</td>'
            f'<td class="num">{e["mu"]:.2f}</td>'
            f'<td class="num">{e["sigma"]:.2f}</td>'
            f'<td class="num"><strong>{e["mu3s"]:.2f}</strong></td>'
            f'<td class="num">{diff_cell}</td>'
            f'<td class="num">{n}</td>'
            f'<td class="num"><span class="win">{wins}</span>-<span class="loss">{losses}</span></td>'
            f'<td class="num">{win_pct}</td>'
            f'</tr>'
        )
    return f"""
  <h2 class="section-title">Peers (3 above &middot; 3 below)</h2>
  <div class="table-wrap">
  <table>
    <thead><tr>
      <th class="num">#</th><th>Class</th><th>Player</th>
      <th class="num">μ</th><th class="num">σ</th><th class="num">μ-3σ</th>
      <th class="num">Δ vs me</th>
      <th class="num">n</th><th class="num">W-L</th><th class="num">win%</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  </div>
"""


def fetch_player_lookup(conn: sqlite3.Connection) -> dict[int, tuple[int, str]]:
    """Map every player_id (including merged-out ones) to (canonical_id, name).

    Merged-out IDs resolve to their merge target's canonical name + ID, so a
    historical match referencing the old ID still shows the right name and
    links to the surviving page.
    """
    rows = conn.execute(
        "SELECT id, canonical_name, merged_into_id FROM players"
    ).fetchall()
    by_id = {r[0]: r for r in rows}
    out: dict[int, tuple[int, str]] = {}
    for pid, name, merged_into in rows:
        canon_id = pid
        # Walk merge chain (defensive against multi-hop merges).
        seen = {pid}
        while merged_into is not None and merged_into not in seen:
            seen.add(merged_into)
            target = by_id.get(merged_into)
            if target is None:
                break
            canon_id = target[0]
            merged_into = target[2]
        canon_name = by_id[canon_id][1]
        out[pid] = (canon_id, canon_name)
    return out


# --- Index page --------------------------------------------------------------


LEADERBOARD_SQL = """
SELECT
    p.id, p.canonical_name, p.gender,
    r.mu, r.sigma, (r.mu - 3*r.sigma) AS mu3s,
    (
        SELECT COUNT(*) FROM match_sides ms
        JOIN matches m ON m.id = ms.match_id
        WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
          AND m.superseded_by_run_id IS NULL
    ) AS n,
    (
        SELECT COUNT(*) FROM match_sides ms
        JOIN matches m ON m.id = ms.match_id
        WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
          AND m.superseded_by_run_id IS NULL AND ms.won = 1
    ) AS wins,
    (
        SELECT COALESCE(SUM(ms.games_won), 0) FROM match_sides ms
        JOIN matches m ON m.id = ms.match_id
        WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
          AND m.superseded_by_run_id IS NULL
    ) AS gw,
    (
        SELECT COALESCE(SUM(opp.games_won), 0) FROM match_sides ms
        JOIN matches m ON m.id = ms.match_id
        JOIN match_sides opp ON opp.match_id = ms.match_id AND opp.side <> ms.side
        WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
          AND m.superseded_by_run_id IS NULL
    ) AS gl,
    (
        SELECT MAX(m.played_on) FROM match_sides ms
        JOIN matches m ON m.id = ms.match_id
        WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
          AND m.superseded_by_run_id IS NULL
    ) AS last_played,
    (
        SELECT pta.class_label
        FROM player_team_assignments pta
        JOIN tournaments t ON t.id = pta.tournament_id
        WHERE pta.player_id = p.id
        ORDER BY t.year DESC, t.id DESC LIMIT 1
    ) AS captain_class,
    (
        SELECT GROUP_CONCAT(DISTINCT c.slug)
        FROM match_sides ms
        JOIN matches m ON m.id = ms.match_id
        JOIN tournaments t ON t.id = m.tournament_id
        JOIN clubs c ON c.id = t.club_id
        WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
          AND m.superseded_by_run_id IS NULL
    ) AS clubs
FROM ratings r
JOIN players p ON p.id = r.player_id
WHERE r.model_name = ?
  AND p.merged_into_id IS NULL
ORDER BY mu3s DESC
"""


def build_index(conn: sqlite3.Connection) -> str:
    rows = conn.execute(LEADERBOARD_SQL, (MODEL,)).fetchall()
    rows = [r for r in rows if r[6] > 0]  # n_matches > 0

    body_rows = []
    for rank, r in enumerate(rows, 1):
        (pid, name, gender, mu, sigma, mu3s, n, wins, gw, gl,
         last_played, captain_class, clubs) = r
        losses = n - wins
        win_pct = f"{int(round(wins * 100 / n))}%" if n else ""
        gw_pct = f"{int(round(gw * 100 / (gw + gl)))}%" if (gw + gl) else ""
        cls = captain_class or ""
        clubs_str = clubs or ""
        body_rows.append(
            f'<tr data-gender="{esc(gender or "")}" data-class="{esc(cls)}" '
            f'data-clubs="{esc(clubs_str)}">'
            f'<td class="num">{rank}</td>'
            f'<td class="cls">{esc(cls)}</td>'
            f'<td>{player_link(pid, name)}</td>'
            f'<td class="gender-{esc(gender or "")}">{esc(gender or "")}</td>'
            f'<td class="num">{mu:.2f}</td>'
            f'<td class="num">{sigma:.2f}</td>'
            f'<td class="num"><strong>{mu3s:.2f}</strong></td>'
            f'<td class="num">{n}</td>'
            f'<td class="num"><span class="win">{wins}</span>-<span class="loss">{losses}</span></td>'
            f'<td class="num">{win_pct}</td>'
            f'<td class="num">{gw}-{gl}</td>'
            f'<td class="num">{gw_pct}</td>'
            f'<td class="muted">{esc(clubs_str)}</td>'
            f'<td class="muted">{esc(last_played or "")}</td>'
            f'</tr>'
        )

    js = """
    <script>
    function applyFilters() {
      const g = document.getElementById('f-gender').value;
      const q = document.getElementById('f-search').value.toLowerCase();
      const cl = document.getElementById('f-club').value;
      const rows = document.querySelectorAll('tbody tr');
      let visible = 0;
      rows.forEach((row) => {
        const rg = row.dataset.gender;
        const rclubs = row.dataset.clubs;
        const txt = row.textContent.toLowerCase();
        const okG = !g || rg === g;
        const okC = !cl || (rclubs && rclubs.split(',').includes(cl));
        const okQ = !q || txt.includes(q);
        const show = okG && okC && okQ;
        row.style.display = show ? '' : 'none';
        if (show) visible++;
      });
      document.getElementById('count').textContent = visible + ' players';
    }
    document.addEventListener('DOMContentLoaded', () => {
      ['f-gender','f-search','f-club'].forEach((id) => {
        document.getElementById(id).addEventListener('input', applyFilters);
      });
      // Sort on header click
      document.querySelectorAll('th').forEach((th, idx) => {
        th.addEventListener('click', () => {
          const tbody = document.querySelector('tbody');
          const rows = Array.from(tbody.querySelectorAll('tr'));
          const asc = th.dataset.sort !== 'asc';
          th.dataset.sort = asc ? 'asc' : 'desc';
          const numeric = th.classList.contains('num');
          rows.sort((a,b) => {
            const av = a.cells[idx].textContent.trim();
            const bv = b.cells[idx].textContent.trim();
            if (numeric) {
              const an = parseFloat(av.replace(/[^0-9.\\-]/g,'')) || 0;
              const bn = parseFloat(bv.replace(/[^0-9.\\-]/g,'')) || 0;
              return asc ? an - bn : bn - an;
            }
            return asc ? av.localeCompare(bv) : bv.localeCompare(av);
          });
          rows.forEach(r => tbody.appendChild(r));
        });
      });
      applyFilters();
    });
    </script>
    """

    # Collect club slugs for the filter
    club_slugs = sorted({
        s for r in rows if r[12]
        for s in (r[12] or "").split(",") if s
    })
    club_options = "".join(
        f'<option value="{esc(c)}">{esc(c)}</option>' for c in club_slugs
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<title>RallyRank — Leaderboard</title>
<link rel="stylesheet" href="styles.css?v={CSS_VERSION}">
</head>
<body>
<header>
  <h1>RallyRank — Doubles Leaderboard</h1>
  <p>OpenSkill Plackett-Luce ratings &middot; class column = captain-assigned slot from most recent team tournament</p>
</header>
{render_nav("", "index")}
<main>
  <div class="controls">
    <input id="f-search" type="search" placeholder="Search player...">
    <select id="f-gender">
      <option value="">All genders</option>
      <option value="M">Men</option>
      <option value="F">Ladies</option>
    </select>
    <select id="f-club">
      <option value="">All clubs</option>
      {club_options}
    </select>
    <span id="count" class="muted"></span>
  </div>
  <div class="table-wrap">
  <table class="leaderboard">
    <thead>
      <tr>
        <th class="num">#</th>
        <th>Class</th>
        <th>Player</th>
        <th>G</th>
        <th class="num">μ</th>
        <th class="num">σ</th>
        <th class="num">μ-3σ</th>
        <th class="num">n</th>
        <th class="num">W-L</th>
        <th class="num">win%</th>
        <th class="num">games</th>
        <th class="num">g%</th>
        <th>Clubs</th>
        <th>Last</th>
      </tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>
  </div>
</main>
<footer>
  Generated from {DB_PATH} &middot; click any player for trajectory and match history &middot;
  click any column header to sort.
</footer>
{js}
</body>
</html>
"""


# --- Player page -------------------------------------------------------------


PLAYER_INFO_SQL = """
SELECT id, canonical_name, gender FROM players WHERE id = ?
"""

PLAYER_RATING_SQL = """
SELECT mu, sigma FROM ratings WHERE player_id = ? AND model_name = ?
"""

PLAYER_MATCHES_SQL = """
SELECT
    m.id, m.played_on, m.division, m.round, m.walkover,
    t.id AS tour_id, t.name AS tour_name, t.year, c.name AS club_name, c.slug AS club_slug,
    ms.side, ms.player1_id AS my_p1, ms.player2_id AS my_p2,
    ms.games_won AS my_games, ms.sets_won AS my_sets, ms.won AS my_won,
    opp.player1_id AS opp_p1, opp.player2_id AS opp_p2,
    opp.games_won AS opp_games, opp.sets_won AS opp_sets,
    rh.mu_after, rh.sigma_after
FROM match_sides ms
JOIN matches m ON m.id = ms.match_id
JOIN match_sides opp ON opp.match_id = m.id AND opp.side <> ms.side
JOIN tournaments t ON t.id = m.tournament_id
JOIN clubs c ON c.id = t.club_id
LEFT JOIN rating_history rh
    ON rh.match_id = m.id AND rh.player_id = ? AND rh.model_name = ?
WHERE (ms.player1_id = ? OR ms.player2_id = ?)
  AND m.superseded_by_run_id IS NULL
ORDER BY m.played_on, m.id
"""

PLAYER_CLASS_HISTORY_SQL = """
SELECT t.year, t.name, c.name AS club_name, c.slug AS club_slug,
       pta.team_letter, pta.captain_name, pta.class_label
FROM player_team_assignments pta
JOIN tournaments t ON t.id = pta.tournament_id
JOIN clubs c ON c.id = t.club_id
WHERE pta.player_id = ?
ORDER BY t.year, t.id
"""

SET_SCORES_SQL = """
SELECT set_number, side_a_games, side_b_games, was_tiebreak
FROM match_set_scores WHERE match_id = ? ORDER BY set_number
"""


def _resolve(name_lookup, pid):
    return name_lookup.get(pid, (pid, f"#{pid}"))


def render_partner(my_p1, my_p2, me_id, name_lookup) -> str:
    partner_id = my_p2 if my_p1 == me_id else my_p1
    if partner_id is None:
        return '<span class="muted">—</span>'
    cid, name = _resolve(name_lookup, partner_id)
    return player_link_from_player_page(cid, name)


def render_opponents(opp_p1, opp_p2, name_lookup) -> str:
    parts = []
    for pid in (opp_p1, opp_p2):
        if pid:
            cid, name = _resolve(name_lookup, pid)
            parts.append(player_link_from_player_page(cid, name))
    return " / ".join(parts) if parts else '<span class="muted">—</span>'


def render_score(side: str, set_scores: list) -> str:
    """Render set scores from THIS player's perspective (side A or B)."""
    parts = []
    for sn, a, b, tb in set_scores:
        my, opp = (a, b) if side == "A" else (b, a)
        marker = " <span class='muted'>(TB)</span>" if tb else ""
        parts.append(f"{my}-{opp}{marker}")
    return ", ".join(parts) if parts else '<span class="muted">—</span>'


def render_trajectory_svg(history: list[tuple[str, float, float]]) -> str:
    """history = [(date_iso, mu_after, sigma_after), ...] ordered chronologically."""
    if len(history) < 2:
        return '<p class="muted">Not enough rated matches to draw a trajectory.</p>'

    width, height = 920, 280
    pad_l, pad_r, pad_t, pad_b = 50, 16, 14, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    mus = [h[1] for h in history]
    sigs = [h[2] for h in history]
    mu_lo = min(m - 3*s for m, s in zip(mus, sigs)) - 1
    mu_hi = max(m for m in mus) + 2
    if mu_hi - mu_lo < 5:
        mu_hi = mu_lo + 5

    n = len(history)

    def x_at(i): return pad_l + (plot_w * i / (n - 1))
    def y_at(v): return pad_t + plot_h - (plot_h * (v - mu_lo) / (mu_hi - mu_lo))

    # μ line
    mu_pts = " ".join(f"{x_at(i):.1f},{y_at(mus[i]):.1f}" for i in range(n))
    # μ-3σ line (conservative ranking)
    cons_pts = " ".join(
        f"{x_at(i):.1f},{y_at(mus[i] - 3*sigs[i]):.1f}" for i in range(n)
    )

    # Y-axis ticks
    y_ticks = []
    step = 5
    t = int(mu_lo // step * step)
    while t <= mu_hi:
        if t >= mu_lo:
            y = y_at(t)
            y_ticks.append(
                f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" '
                f'stroke="#2a3242" stroke-width="0.5"/>'
                f'<text x="{pad_l-6}" y="{y+3:.1f}" text-anchor="end" '
                f'fill="#8b96a8" font-size="10">{t}</text>'
            )
        t += step

    # X-axis: year markers (when the year in the date string changes)
    x_ticks = []
    last_year = None
    for i, (d, _, _) in enumerate(history):
        yr = d[:4] if d else None
        if yr and yr != last_year:
            x = x_at(i)
            x_ticks.append(
                f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t+plot_h}" '
                f'stroke="#2a3242" stroke-width="0.5" stroke-dasharray="2,2"/>'
                f'<text x="{x:.1f}" y="{height-10}" text-anchor="middle" '
                f'fill="#8b96a8" font-size="10">{yr}</text>'
            )
            last_year = yr

    # σ trajectory (uncertainty over time) — uses a separate y-axis on the right
    sig_lo = max(0, min(sigs) - 0.5)
    sig_hi = max(sigs) + 0.5
    if sig_hi - sig_lo < 1.0:
        sig_hi = sig_lo + 1.0

    def y_sig(v):
        return pad_t + plot_h - (plot_h * (v - sig_lo) / (sig_hi - sig_lo))

    sig_pts = " ".join(f"{x_at(i):.1f},{y_sig(sigs[i]):.1f}" for i in range(n))

    # σ axis labels on right side
    sig_axis = []
    for v in (sig_lo, (sig_lo + sig_hi) / 2, sig_hi):
        y = y_sig(v)
        sig_axis.append(
            f'<text x="{width-pad_r+4}" y="{y+3:.1f}" text-anchor="start" '
            f'fill="#e07a7a" font-size="9">{v:.1f}</text>'
        )

    return f"""
<div class="chart">
<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="rating trajectory">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#1a1f2a"/>
  {''.join(y_ticks)}
  {''.join(x_ticks)}
  <polyline points="{cons_pts}" fill="none" stroke="#8b96a8" stroke-width="1" stroke-dasharray="3,3"/>
  <polyline points="{sig_pts}" fill="none" stroke="#e07a7a" stroke-width="1" stroke-dasharray="2,2" opacity="0.6"/>
  <polyline points="{mu_pts}" fill="none" stroke="#4ea1ff" stroke-width="2"/>
  {''.join(sig_axis)}
  <text x="{width-pad_r}" y="{pad_t+10}" text-anchor="end" fill="#4ea1ff" font-size="11">μ (skill, left axis)</text>
  <text x="{width-pad_r}" y="{pad_t+24}" text-anchor="end" fill="#8b96a8" font-size="11">μ-3σ (conservative)</text>
  <text x="{width-pad_r}" y="{pad_t+38}" text-anchor="end" fill="#e07a7a" font-size="11">σ (uncertainty, right axis)</text>
</svg>
</div>
"""


def compute_form(matches: list, last_n: int = 10) -> str:
    """Return HTML for the last N results as W/L badges (newest first)."""
    recent = list(reversed(matches[-last_n:]))
    if not recent:
        return '<span class="muted">no matches</span>'
    parts = []
    for m in recent:
        won = m[15]
        cls = "w" if won else "l"
        ch = "W" if won else "L"
        parts.append(f'<span class="b {cls}">{ch}</span>')
    return f'<span class="form">{"".join(parts)}</span>'


def compute_streaks(matches: list) -> tuple[int, int, int, str]:
    """Return (longest_win, longest_loss, current, current_kind).
    current_kind is 'W' or 'L' depending on the latest match."""
    if not matches:
        return (0, 0, 0, "")
    longest_w = longest_l = cur = 0
    cur_kind = ""
    last = None
    for m in matches:
        won = bool(m[15])
        if won == last:
            cur += 1
        else:
            cur = 1
        last = won
        if won:
            longest_w = max(longest_w, cur)
        else:
            longest_l = max(longest_l, cur)
    cur_kind = "W" if last else "L"
    return (longest_w, longest_l, cur, cur_kind)


def compute_yearly_summary(matches: list) -> list[dict]:
    """Bucket matches by year. Returns list of dicts ordered by year."""
    by_year: dict[str, dict] = {}
    last_mu_by_year: dict[str, list] = {}
    for m in matches:
        played = m[1] or ""
        year = played[:4] if len(played) >= 4 else "?"
        bucket = by_year.setdefault(year, {
            "year": year, "n": 0, "wins": 0, "losses": 0,
            "games_won": 0, "games_lost": 0,
            "mu_first": None, "mu_last": None, "sigma_last": None,
        })
        bucket["n"] += 1
        if m[15]:
            bucket["wins"] += 1
        else:
            bucket["losses"] += 1
        bucket["games_won"] += (m[13] or 0)
        bucket["games_lost"] += (m[18] or 0)
        if m[20] is not None:
            if bucket["mu_first"] is None:
                bucket["mu_first"] = m[20]
            bucket["mu_last"] = m[20]
            bucket["sigma_last"] = m[21]
    return [by_year[y] for y in sorted(by_year)]


def compute_swings(match_rows_with_delta: list) -> tuple[list, list]:
    """Return (top_3_wins, top_3_losses) as lists of (delta, row_dict).
    Input items: dict with keys delta, played, opps, partner, score, result."""
    sorted_by_delta = sorted(match_rows_with_delta, key=lambda r: r["delta"])
    losses = sorted_by_delta[:3]  # most-negative first
    wins = list(reversed(sorted_by_delta[-3:]))  # most-positive first
    return ([w for w in wins if w["delta"] > 0],
            [l for l in losses if l["delta"] < 0])


def build_player_page(
    conn: sqlite3.Connection,
    pid: int,
    name_lookup: dict[int, str],
    neighbours_by_gender: dict[str, list[dict]] | None = None,
) -> str:
    info = conn.execute(PLAYER_INFO_SQL, (pid,)).fetchone()
    if info is None:
        return ""
    _, name, gender = info

    rating = conn.execute(PLAYER_RATING_SQL, (pid, MODEL)).fetchone()
    mu, sigma = (rating if rating else (None, None))
    mu3s = mu - 3 * sigma if mu is not None else None

    matches = conn.execute(
        PLAYER_MATCHES_SQL, (pid, MODEL, pid, pid)
    ).fetchall()

    class_history = conn.execute(PLAYER_CLASS_HISTORY_SQL, (pid,)).fetchall()

    # Column index map (matches PLAYER_MATCHES_SQL):
    #   0=mid 1=played 2=division 3=round 4=walkover
    #   5=tour_id 6=tour_name 7=year 8=club_name 9=club_slug
    #   10=side 11=my_p1 12=my_p2 13=my_games 14=my_sets 15=my_won
    #   16=opp_p1 17=opp_p2 18=opp_games 19=opp_sets
    #   20=mu_after 21=sigma_after
    n = len(matches)
    wins = sum(1 for m in matches if m[15])
    losses = n - wins
    games_won = sum((m[13] or 0) for m in matches)
    games_lost = sum((m[18] or 0) for m in matches)
    win_pct = f"{int(round(wins * 100 / n))}%" if n else "—"

    # Trajectory: only matches where rating_history exists.
    history = [
        (m[1], m[20], m[21]) for m in matches
        if m[20] is not None and m[21] is not None
    ]
    traj = render_trajectory_svg(history)

    # Peers section: 3 above + me + 3 below in the appropriate gender bucket.
    peers_html = ""
    if neighbours_by_gender:
        bucket_key = gender if gender in ("M", "F") else "all"
        bucket = neighbours_by_gender.get(bucket_key, [])
        peers_html = render_neighbours(bucket, pid)

    # Match rows. Δμ must be computed in chronological order (per match it's
    # mu_after − mu_after_of_prior_match), but the table is rendered newest
    # first. Build the rows then reverse before joining.
    match_rows = []
    swing_data = []  # for biggest-swings analysis
    last_mu, last_sig = None, None
    for m in matches:
        (mid, played, division, rnd, walkover, _tid, tname, tyear, club_name, club_slug,
         side, my_p1, my_p2, my_games, my_sets, my_won,
         opp_p1, opp_p2, opp_games, opp_sets, mu_after, sigma_after) = m
        sets = conn.execute(SET_SCORES_SQL, (mid,)).fetchall()
        partner = render_partner(my_p1, my_p2, pid, name_lookup)
        opps = render_opponents(opp_p1, opp_p2, name_lookup)
        score = render_score(side, sets)
        result_cls = "win" if my_won else "loss"
        result_txt = "W" if my_won else "L"
        d_mu = ""
        delta_val = None
        d_sig = ""
        if mu_after is not None and last_mu is not None:
            delta_val = mu_after - last_mu
            colour = "win" if delta_val > 0 else ("loss" if delta_val < 0 else "muted")
            d_mu = (
                f'<span class="{colour}">'
                f'{"+" if delta_val>=0 else ""}{delta_val:.2f}</span>'
            )
            if last_sig is not None and sigma_after is not None:
                ds = sigma_after - last_sig
                d_sig = (
                    f'<span class="muted">{"+" if ds>=0 else ""}{ds:.2f}</span>'
                )
        if mu_after is not None:
            last_mu, last_sig = mu_after, sigma_after
        mu_cell = f"{mu_after:.2f}" if mu_after is not None else '<span class="muted">—</span>'
        sig_cell = f"{sigma_after:.2f}" if sigma_after is not None else '<span class="muted">—</span>'
        wo = ' <span class="tag">W/O</span>' if walkover else ""
        match_rows.append(
            f'<tr>'
            f'<td>{esc(played)}</td>'
            f'<td><span class="tag">{esc(club_slug)}</span> {esc(tname)} {esc(tyear)}</td>'
            f'<td class="muted">{esc(division or "")} {esc(rnd or "")}</td>'
            f'<td>{partner}</td>'
            f'<td>{opps}</td>'
            f'<td class="score">{score}{wo}</td>'
            f'<td class="num"><span class="{result_cls}">{result_txt}</span> '
            f'{my_games}-{opp_games}</td>'
            f'<td class="num">{mu_cell}</td>'
            f'<td class="num">{d_mu}</td>'
            f'<td class="num">{sig_cell}</td>'
            f'<td class="num">{d_sig}</td>'
            f'</tr>'
        )
        if delta_val is not None:
            swing_data.append({
                "delta": delta_val,
                "played": played,
                "opps_html": opps,
                "partner_html": partner,
                "score_html": score,
                "result_cls": result_cls,
                "result_txt": result_txt,
                "tname": tname,
                "club_slug": club_slug,
            })

    # Form (last 10), streaks, yearly summary, biggest swings
    form_html = compute_form(matches, last_n=10)
    longest_w, longest_l, cur_streak, cur_kind = compute_streaks(matches)
    yearly = compute_yearly_summary(matches)
    biggest_wins, biggest_losses = compute_swings(swing_data)

    def _yearly_row(y):
        mu_range = (
            f"{y['mu_first']:.2f} → {y['mu_last']:.2f}"
            if y["mu_first"] is not None else "—"
        )
        if y["mu_first"] is not None and y["mu_last"] is not None:
            d = y["mu_last"] - y["mu_first"]
            cls = "win" if d > 0 else ("loss" if d < 0 else "muted")
            sign = "+" if d >= 0 else ""
            d_cell = f'<span class="{cls}">{sign}{d:.2f}</span>'
        else:
            d_cell = "—"
        return (
            f'<tr>'
            f'<td><strong>{esc(y["year"])}</strong></td>'
            f'<td class="num">{y["n"]}</td>'
            f'<td class="num"><span class="win">{y["wins"]}</span>-<span class="loss">{y["losses"]}</span></td>'
            f'<td class="num">{int(round(y["wins"]*100/y["n"]))}%</td>'
            f'<td class="num">{y["games_won"]}-{y["games_lost"]}</td>'
            f'<td class="num">{mu_range}</td>'
            f'<td class="num">{d_cell}</td>'
            f'</tr>'
        )

    yearly_rows = "".join(_yearly_row(y) for y in yearly)

    def render_swing_row(s):
        d = s["delta"]
        cls = "win" if d > 0 else "loss"
        return (
            f'<tr>'
            f'<td>{esc(s["played"])}</td>'
            f'<td><span class="tag">{esc(s["club_slug"])}</span> {esc(s["tname"])}</td>'
            f'<td>{s["partner_html"]}</td>'
            f'<td>{s["opps_html"]}</td>'
            f'<td class="score">{s["score_html"]}</td>'
            f'<td class="num"><span class="{s["result_cls"]}">{s["result_txt"]}</span></td>'
            f'<td class="num"><span class="{cls}">{"+" if d>=0 else ""}{d:.2f}</span></td>'
            f'</tr>'
        )

    swings_html = ""
    if biggest_wins or biggest_losses:
        win_rows = "".join(render_swing_row(s) for s in biggest_wins) or \
            '<tr><td colspan="7" class="muted">No positive swings recorded.</td></tr>'
        loss_rows = "".join(render_swing_row(s) for s in biggest_losses) or \
            '<tr><td colspan="7" class="muted">No negative swings recorded.</td></tr>'
        swings_html = f"""
  <h2 class="section-title">Biggest Δμ swings</h2>
  <p class="muted" style="font-size: 12px; margin-top: -4px;">
    Largest single-match rating jumps (signal: upset wins / surprise losses).
  </p>
  <div class="table-wrap">
  <table>
    <thead><tr><th colspan="7" style="background:#1f3a2a; color: var(--win)">Top wins</th></tr>
    <tr><th>Date</th><th>Tournament</th><th>Partner</th><th>Opponents</th><th>Score</th><th class="num">Result</th><th class="num">Δμ</th></tr>
    </thead>
    <tbody>{win_rows}</tbody>
  </table>
  </div>
  <div class="table-wrap">
  <table>
    <thead><tr><th colspan="7" style="background:#3a1f1f; color: var(--loss)">Worst losses</th></tr>
    <tr><th>Date</th><th>Tournament</th><th>Partner</th><th>Opponents</th><th>Score</th><th class="num">Result</th><th class="num">Δμ</th></tr>
    </thead>
    <tbody>{loss_rows}</tbody>
  </table>
  </div>
"""

    class_rows = "".join(
        f'<tr><td>{esc(yr)}</td><td><span class="tag">{esc(slug)}</span> {esc(tn)}</td>'
        f'<td>Team {esc(tl or "?")}</td><td class="muted">{esc(cap or "")}</td>'
        f'<td class="cls">{esc(cl)}</td></tr>'
        for (yr, tn, _cn, slug, tl, cap, cl) in class_history
    )

    if not class_rows:
        class_rows = (
            '<tr><td colspan="5" class="muted">No team-tournament class assignments.</td></tr>'
        )

    streak_value = (
        f'<span class="{"win" if cur_kind=="W" else "loss"}">{cur_streak}{cur_kind}</span>'
        if cur_streak else "—"
    )
    rating_block = ""
    if mu is not None:
        rating_block = f"""
<div class="stat-grid">
  <div class="stat"><div class="label">μ skill</div><div class="value">{mu:.2f}</div></div>
  <div class="stat"><div class="label">σ uncertainty</div><div class="value">{sigma:.2f}</div></div>
  <div class="stat"><div class="label">μ-3σ rank</div><div class="value">{mu3s:.2f}</div></div>
  <div class="stat"><div class="label">matches</div><div class="value">{n}</div></div>
  <div class="stat"><div class="label">W-L</div>
    <div class="value"><span class="win">{wins}</span>-<span class="loss">{losses}</span></div></div>
  <div class="stat"><div class="label">win %</div><div class="value">{win_pct}</div></div>
  <div class="stat"><div class="label">games W-L</div><div class="value">{games_won}-{games_lost}</div></div>
  <div class="stat"><div class="label">current streak</div><div class="value">{streak_value}</div></div>
  <div class="stat"><div class="label">longest W</div><div class="value win">{longest_w}</div></div>
  <div class="stat"><div class="label">longest L</div><div class="value loss">{longest_l}</div></div>
</div>
<div style="margin-bottom: 16px;">
  <div class="muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;">Form (last 10, newest first)</div>
  {form_html}
</div>
"""

    yearly_block = ""
    if yearly:
        yearly_block = f"""
  <h2 class="section-title">Per-year breakdown</h2>
  <div class="table-wrap">
  <table>
    <thead><tr>
      <th>Year</th><th class="num">n</th><th class="num">W-L</th><th class="num">win%</th>
      <th class="num">games</th><th class="num">μ start → end</th><th class="num">Δμ</th>
    </tr></thead>
    <tbody>{yearly_rows}</tbody>
  </table>
  </div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<title>{esc(name)} — RallyRank</title>
<link rel="stylesheet" href="../styles.css?v={CSS_VERSION}">
</head>
<body>
{render_nav("../", "")}
<main>
  <div class="profile-head">
    <div>
      <div class="name gender-{esc(gender or "")}">{esc(name)}</div>
      <div class="meta">
        {esc({"M":"Men", "F":"Ladies"}.get(gender, "Unknown gender"))} &middot;
        Player ID #{pid}
      </div>
    </div>
  </div>

  {rating_block}

  {peers_html}

  <h2 class="section-title">Rating trajectory</h2>
  {traj}

  {yearly_block}

  {swings_html}

  <h2 class="section-title">Captain class assignments</h2>
  <div class="table-wrap">
  <table>
    <thead><tr><th>Year</th><th>Tournament</th><th>Team</th><th>Captain</th><th>Class</th></tr></thead>
    <tbody>{class_rows}</tbody>
  </table>
  </div>

  <h2 class="section-title">Match log ({n})</h2>
  <div class="table-wrap">
  <table>
    <thead><tr>
      <th>Date</th><th>Tournament</th><th>Round</th>
      <th>Partner</th><th>Opponents</th><th>Score</th>
      <th class="num">Result</th>
      <th class="num">μ after</th><th class="num">Δμ</th>
      <th class="num">σ after</th><th class="num">Δσ</th>
    </tr></thead>
    <tbody>{''.join(reversed(match_rows)) if match_rows else '<tr><td colspan="11" class="muted">No matches.</td></tr>'}</tbody>
  </table>
  </div>
</main>
<footer>
  μ after / σ after are the OpenSkill PL values <em>after</em> this match was processed.
  Δμ / Δσ are differences from the prior match (blank for the very first rated match).
</footer>
</body>
</html>
"""


# --- Tournament roster pages -------------------------------------------------
# A roster page ranks a list of players (read from an .xlsx) against the
# current ratings DB. Useful for pre-tournament seeding when you have the
# entry list before any matches have been played.


def _read_roster_xlsx(path: Path) -> dict[str, list[str]]:
    """Return {'Men': [...], 'Ladies': [...]} from a 2-sheet roster file.

    Each sheet is expected to have header row + two name columns at indices
    (1, 3) — i.e. the standard '(No, Name, No, Name)' layout used by
    `_ANALYSIS_/NewTournamentRanking/Players List.xlsx` and similar.
    """
    import openpyxl  # local import; only needed when a roster is configured

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out: dict[str, list[str]] = {}
    for sheet_name in ("Men", "Ladies"):
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        seen: set[str] = set()
        names: list[str] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue
            for col in (0, 2):
                if col + 1 >= len(row):
                    continue
                name = row[col + 1]
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


def _name_order_variants(name: str) -> list[str]:
    """Plausible word-order rotations to bridge 'Lastname Firstname' vs
    'Firstname Lastname' parser conventions."""
    parts = name.split()
    if len(parts) < 2:
        return []
    if len(parts) == 2:
        return [f"{parts[1]} {parts[0]}"]
    if len(parts) == 3:
        return [
            f"{parts[2]} {parts[0]} {parts[1]}",
            f"{parts[1]} {parts[2]} {parts[0]}",
        ]
    if len(parts) == 4:
        return [
            f"{parts[3]} {parts[0]} {parts[1]} {parts[2]}",
            f"{parts[2]} {parts[3]} {parts[0]} {parts[1]}",
        ]
    return []


_ROSTER_LOOKUP_SQL = """
SELECT p.id, p.canonical_name, p.gender, r.mu, r.sigma, r.n_matches,
    (
        SELECT pta.class_label
        FROM player_team_assignments pta
        JOIN tournaments t ON t.id = pta.tournament_id
        WHERE pta.player_id = p.id
        ORDER BY t.year DESC, t.id DESC LIMIT 1
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


def _lookup_roster_player(conn: sqlite3.Connection, name: str) -> dict | None:
    """Resolve a roster name to a rated player.

    Tries: exact canonical match → exact alias match → word-order rotations
    against both canonical and alias tables. Returns None if all attempts
    miss.
    """
    canonical_clause = " AND LOWER(p.canonical_name) = LOWER(?)"
    alias_clause = (
        " AND p.id IN (SELECT player_id FROM player_aliases "
        " WHERE LOWER(raw_name) = LOWER(?)) LIMIT 1"
    )

    def _try(target: str) -> tuple | None:
        row = conn.execute(
            _ROSTER_LOOKUP_SQL + canonical_clause,
            (MODEL, MODEL, target),
        ).fetchone()
        if row:
            return row
        return conn.execute(
            _ROSTER_LOOKUP_SQL + alias_clause,
            (MODEL, MODEL, target),
        ).fetchone()

    row = _try(name)
    if row is None:
        for variant in _name_order_variants(name):
            row = _try(variant)
            if row:
                break
    if row is None:
        return None

    pid, canonical, gender, mu, sigma, n, cls, last = row
    return {
        "roster_name": name,
        "id": pid,
        "canonical": canonical,
        "gender": gender,
        "mu": mu,
        "sigma": sigma,
        "n": n,
        "class": cls,
        "last": last,
    }


def _fuzzy_candidates(conn: sqlite3.Connection, name: str, limit: int = 3) -> list[str]:
    all_names = [
        r[0]
        for r in conn.execute(
            "SELECT canonical_name FROM players WHERE merged_into_id IS NULL"
        ).fetchall()
    ]
    return difflib.get_close_matches(name, all_names, n=limit, cutoff=0.6)


def _proposed_class_label(rank_idx: int, group_size: int = 6, slots_per_tier: int = 4) -> str:
    """Class label (A1, A2, ..., A4, B1, ..., B4, C1, ...) from 0-indexed rank.

    Mirrors the existing player_team_assignments convention: each tier
    (A/B/C/D...) holds `slots_per_tier` slots, and `group_size` players share
    a slot (one per team). With 6 captains and 4 slots per tier, every 6
    positions advance the slot number, and every 24 positions advance the
    tier letter.
    """
    slot_idx = rank_idx // group_size
    tier_idx = slot_idx // slots_per_tier
    within_tier = (slot_idx % slots_per_tier) + 1
    tier_letter = chr(ord("A") + tier_idx)
    return f"{tier_letter}{within_tier}"


def _render_roster_section(
    sheet: str, hits: list[dict], misses: list[tuple[str, list[str]]]
) -> str:
    rated = sorted(
        (h for h in hits if h["mu"] is not None),
        key=lambda h: -(h["mu"] - 3 * h["sigma"]),
    )
    unrated = [h for h in hits if h["mu"] is None]
    total = len(rated) + len(unrated) + len(misses)

    pills = [f'<span class="pill ok">{len(rated)} rated</span>']
    if unrated:
        pills.append(f'<span class="pill warn">{len(unrated)} unrated</span>')
    if misses:
        pills.append(f'<span class="pill miss">{len(misses)} not in DB</span>')
    pills.append(f'<span class="pill">total {total}</span>')

    rows = []
    for i, h in enumerate(rated, 1):
        cons = h["mu"] - 3 * h["sigma"]
        proposed_cls = _proposed_class_label(i - 1)
        prev_cls = h["class"]
        # Hover tooltip on the class cell shows the player's most recent
        # captain-assigned class from a prior tournament, when known.
        cls_title = (
            f'previous tournament class: {prev_cls}' if prev_cls else
            'no prior captain class on record'
        )
        link = (
            f'<a class="player-link" href="../players/{h["id"]}.html">'
            f'{esc(h["canonical"])}</a>'
        )
        if h["roster_name"].strip().lower() != h["canonical"].strip().lower():
            link += (
                f' <span class="muted" title="roster name">'
                f'({esc(h["roster_name"])})</span>'
            )
        rows.append(
            f'<tr>'
            f'<td class="num">{i}</td>'
            f'<td class="cls" title="{esc(cls_title)}">{esc(proposed_cls)}</td>'
            f'<td>{link}</td>'
            f'<td class="num"><strong>{cons:.2f}</strong></td>'
            f'<td class="num">{h["mu"]:.2f}</td>'
            f'<td class="num">{h["sigma"]:.2f}</td>'
            f'<td class="num">{h["n"]}</td>'
            f'<td>{esc(h["last"] or "?")}</td>'
            f'</tr>'
        )
    rated_table = (
        f'<div class="table-wrap"><table>'
        f'<thead><tr>'
        f'<th class="num">#</th><th>Class</th><th>Player</th>'
        f'<th class="num">μ-3σ</th>'
        f'<th class="num">μ</th><th class="num">σ</th>'
        f'<th class="num">n</th><th>Last played</th>'
        f'</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        f'</table></div>'
    ) if rated else ""

    miss_html = ""
    if misses:
        items = []
        for n, suggestions in misses:
            sugg = (
                ", ".join(esc(s) for s in suggestions)
                if suggestions
                else '<span class="muted">no close match</span>'
            )
            items.append(f'<li>{esc(n)} <span class="muted">— suggest: {sugg}</span></li>')
        miss_html = (
            f'<h3 class="section-title">Not yet in our system ({len(misses)})</h3>'
            f'<ul class="plain">{"".join(items)}</ul>'
        )

    unrated_html = ""
    if unrated:
        items = "".join(f"<li>{esc(h['canonical'])}</li>" for h in unrated)
        unrated_html = (
            f'<h3 class="section-title">In DB but unrated ({len(unrated)})</h3>'
            f'<ul class="plain">{items}</ul>'
        )

    return (
        f'<section><div style="display:flex;align-items:baseline;gap:12px;'
        f'flex-wrap:wrap;margin:24px 0 8px;">'
        f'<h2 style="margin:0;">{esc(sheet)}</h2>'
        f'<span>{" ".join(pills)}</span>'
        f'</div>{rated_table}{unrated_html}{miss_html}</section>'
    )


_ROSTER_PAGE_CSS = """
.pill { display: inline-block; background: var(--card); border: 1px solid var(--border);
        padding: 2px 8px; border-radius: 999px; font-size: 12px; color: var(--muted); margin-right:4px;}
.pill.ok { color: var(--win); border-color: rgba(70,194,129,0.4); }
.pill.warn { color: #d6b46a; border-color: rgba(214,180,106,0.4); }
.pill.miss { color: var(--loss); border-color: rgba(224,122,122,0.4); }
ul.plain { list-style: none; padding: 0; margin: 0; columns: 2; column-gap: 24px; }
ul.plain li { padding: 4px 0; border-bottom: 1px solid var(--border); break-inside: avoid; }
@media (max-width: 700px) { ul.plain { columns: 1; } }
"""


def build_tournament_roster_page(conn: sqlite3.Connection, config: dict) -> str:
    """Render one tournament roster ranking page."""
    roster_path = Path(config["roster_xlsx"])
    if not roster_path.exists():
        return ""  # silently skip — caller logs the miss
    roster = _read_roster_xlsx(roster_path)

    sections: list[str] = []
    totals = {"rated": 0, "unrated": 0, "miss": 0, "all": 0}
    for sheet, names in roster.items():
        hits: list[dict] = []
        misses: list[tuple[str, list[str]]] = []
        for n in names:
            r = _lookup_roster_player(conn, n)
            if r is None:
                misses.append((n, _fuzzy_candidates(conn, n)))
            else:
                hits.append(r)
        sections.append(_render_roster_section(sheet, hits, misses))
        totals["rated"] += sum(1 for h in hits if h["mu"] is not None)
        totals["unrated"] += sum(1 for h in hits if h["mu"] is None)
        totals["miss"] += len(misses)
        totals["all"] += len(names)

    # DB summary for the legend
    last = conn.execute(
        "SELECT MAX(played_on) FROM matches WHERE superseded_by_run_id IS NULL"
    ).fetchone()[0]
    n_matches = conn.execute(
        "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
    ).fetchone()[0]
    n_tour = conn.execute(
        "SELECT COUNT(DISTINCT tournament_id) FROM matches WHERE superseded_by_run_id IS NULL"
    ).fetchone()[0]

    nav = render_nav("../", f"tournament:{config['slug']}")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<title>{esc(config['title'])} — RallyRank</title>
<link rel="stylesheet" href="../styles.css?v={CSS_VERSION}">
<style>{_ROSTER_PAGE_CSS}</style>
</head>
<body>
<header>
  <h1>{esc(config['title'])}</h1>
  <p>{esc(config.get('subtitle', ''))}</p>
</header>
{nav}
<main>
  <p class="muted" style="font-size:13px;">
    Source: <code>{esc(config['roster_xlsx'])}</code> &middot;
    rated against <strong>{n_matches}</strong> matches across
    <strong>{n_tour}</strong> tournaments
    (last match: <strong>{esc(last or '?')}</strong>) &middot;
    model <code>{esc(MODEL)}</code> &middot;
    coverage: <strong>{totals['rated']}/{totals['all']}</strong> rated,
    <strong>{totals['miss']}</strong> not yet in system.
  </p>
  {''.join(sections)}
</main>
<footer>
  Click any name to open that player's profile (μ trajectory, match history, peers).
  Players in &ldquo;Not yet in our system&rdquo; will appear after their first
  rated match is loaded.
</footer>
</body>
</html>
"""


# --- Main --------------------------------------------------------------------


def main() -> int:
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(exist_ok=True)
    write(OUT_DIR / "styles.css", CSS)
    # Tell GitHub Pages not to run Jekyll — it would otherwise hide files that
    # start with `_` and may rewrite paths. The site is fully pre-rendered.
    write(OUT_DIR / ".nojekyll", "")

    conn = sqlite3.connect(DB_PATH)
    try:
        name_lookup = fetch_player_lookup(conn)
        neighbours_by_gender = fetch_neighbour_index(conn)

        # Index
        write(OUT_DIR / "index.html", build_index(conn))
        print(f"Wrote {OUT_DIR / 'index.html'}")

        # Per-player pages: only for unmerged players with at least 1 active match.
        eligible = conn.execute("""
            SELECT DISTINCT p.id
            FROM players p
            JOIN match_sides ms ON ms.player1_id = p.id OR ms.player2_id = p.id
            JOIN matches m ON m.id = ms.match_id
            WHERE p.merged_into_id IS NULL AND m.superseded_by_run_id IS NULL
        """).fetchall()
        eligible_ids = [r[0] for r in eligible]
        for pid in eligible_ids:
            html_text = build_player_page(
                conn, pid, name_lookup, neighbours_by_gender
            )
            if html_text:
                write(OUT_DIR / player_filename(pid), html_text)
        print(f"Wrote {len(eligible_ids)} player pages under {OUT_DIR/'players'}/")

        # Tournament roster pages.
        for cfg in TOURNAMENT_ROSTERS:
            roster_path = Path(cfg["roster_xlsx"])
            if not roster_path.exists():
                print(
                    f"  skipped tournament '{cfg['slug']}': "
                    f"roster file not found at {roster_path}",
                    file=sys.stderr,
                )
                continue
            page = build_tournament_roster_page(conn, cfg)
            if page:
                out = OUT_DIR / "tournaments" / f"{cfg['slug']}.html"
                write(out, page)
                print(f"Wrote {out}")
    finally:
        conn.close()
    print(f"\nDone. Open: file://{(OUT_DIR/'index.html').resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
