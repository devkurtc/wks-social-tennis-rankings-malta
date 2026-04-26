"""Local-only HTTP server for triaging the fuzzy-match queue.

Spawned by `cli.py review-server`. Serves a single review page on localhost
with same/different/defer buttons per pending pair. Verdicts are written to
`manual_aliases.json` (same person) and `known_distinct.json` (different).

Why stdlib http.server and not Flask: Phase-0 README explicitly limits the
dep list to "pure stdlib + small set of pinned deps", and a triage tool is
the wrong place to introduce a web framework. The server is single-file,
single-purpose, never deployed (localhost only), and so doesn't need auth,
CORS, or rate limiting.

Threading: ThreadingHTTPServer + a write-mutex around the JSON files so two
concurrent POSTs (e.g. double-click) can't corrupt the file. Reads are
unsynchronized — they're idempotent and the worst case is a slightly stale
queue, which the next page refresh fixes.
"""
from __future__ import annotations

import html
import json
import sqlite3
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DB_PATH = PROJECT_ROOT / "phase0.sqlite"
ALIASES_PATH = SCRIPT_DIR / "manual_aliases.json"
DISTINCT_PATH = SCRIPT_DIR / "known_distinct.json"

# Make `import players` and `import db` work regardless of cwd.
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import players  # noqa: E402

# Single write lock for the JSON files — reads are lock-free.
_FILE_LOCK = threading.Lock()


# ----- Data fetchers --------------------------------------------------------


def _fetch_suggestions(threshold: float = 0.85) -> list[dict]:
    """Return current pending fuzzy suggestions (filtering out already-decided
    pairs). Re-queried on each page load so verdicts disappear immediately
    after they're recorded."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        kd = players.load_known_distinct(str(DISTINCT_PATH))
        return players.suggest_fuzzy_matches(
            conn,
            threshold=threshold,
            same_gender_only=True,
            min_matches=1,
            known_distinct=kd,
        )
    finally:
        conn.close()


def _fetch_player_mini(pid: int) -> dict:
    """Compact summary for the inline expansion: recent matches, partners,
    clubs, alias forms. Helps the reviewer decide without leaving the page."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        info = conn.execute(
            "SELECT canonical_name, gender FROM players WHERE id = ?", (pid,)
        ).fetchone()
        if not info:
            return {"error": "not found"}
        name, gender = info
        # Recent matches (most recent 8) with partner + opponents + score
        rows = conn.execute(
            """
            SELECT
                m.played_on, t.name AS tournament, m.division,
                ms.player1_id, ms.player2_id, ms.games_won,
                opp.player1_id, opp.player2_id, opp.games_won,
                ms.won
            FROM match_sides ms
            JOIN matches m ON m.id = ms.match_id
            JOIN tournaments t ON t.id = m.tournament_id
            JOIN match_sides opp ON opp.match_id = m.id AND opp.side <> ms.side
            WHERE (ms.player1_id = ? OR ms.player2_id = ?)
              AND m.superseded_by_run_id IS NULL
            ORDER BY m.played_on DESC, m.id DESC
            LIMIT 8
            """,
            (pid, pid),
        ).fetchall()
        # Resolve partner / opponent names in one pass
        ids = set()
        for r in rows:
            ids.update((r[3], r[4], r[6], r[7]))
        ids.discard(None)
        ids.discard(pid)
        if ids:
            name_map = dict(
                conn.execute(
                    f"SELECT id, canonical_name FROM players WHERE id IN ({','.join('?'*len(ids))})",
                    tuple(ids),
                ).fetchall()
            )
        else:
            name_map = {}
        recent = []
        for played, tour, div, a1, a2, ga, b1, b2, gb, won in rows:
            partner_id = a2 if a1 == pid else a1
            partner_name = name_map.get(partner_id, "?")
            opp_names = " / ".join(name_map.get(x, "?") for x in (b1, b2) if x)
            recent.append({
                "date": played,
                "tournament": tour,
                "division": div or "",
                "partner": partner_name,
                "opponents": opp_names,
                "score": f"{ga}-{gb}",
                "won": bool(won),
            })
        # Clubs played at
        clubs = [
            r[0] for r in conn.execute(
                """
                SELECT DISTINCT c.slug FROM match_sides ms
                JOIN matches m ON m.id = ms.match_id
                JOIN tournaments t ON t.id = m.tournament_id
                JOIN clubs c ON c.id = t.club_id
                WHERE (ms.player1_id = ? OR ms.player2_id = ?)
                  AND m.superseded_by_run_id IS NULL
                """,
                (pid, pid),
            ).fetchall()
        ]
        # Captain class history
        classes = [
            {"year": r[0], "tournament": r[1], "label": r[2]}
            for r in conn.execute(
                """
                SELECT t.year, t.name, pta.class_label
                FROM player_team_assignments pta
                JOIN tournaments t ON t.id = pta.tournament_id
                WHERE pta.player_id = ?
                ORDER BY t.year DESC, t.id DESC
                """,
                (pid,),
            ).fetchall()
        ]
        # Raw alias forms ever seen
        aliases = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT raw_name FROM player_aliases WHERE player_id = ?",
                (pid,),
            ).fetchall()
        ]
        return {
            "id": pid,
            "name": name,
            "gender": gender,
            "clubs": clubs,
            "aliases": aliases,
            "classes": classes,
            "recent_matches": recent,
        }
    finally:
        conn.close()


# ----- HTML rendering -------------------------------------------------------


def _esc(s) -> str:
    return html.escape("" if s is None else str(s))


PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review queue — RallyRank (local)</title>
<style>
:root {
  --bg: #0f1115; --fg: #e6e6e6; --muted: #8b96a8; --accent: #4ea1ff;
  --card: #1a1f2a; --border: #2a3242;
  --same: #46c281; --different: #e07a7a; --defer: #8b96a8;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg); color: var(--fg);
  margin: 0; padding: 16px 24px; line-height: 1.45;
}
header { margin-bottom: 12px; }
h1 { margin: 0 0 4px 0; font-size: 20px; }
p.lead { color: var(--muted); font-size: 13px; margin: 0; max-width: 900px; }
.banner {
  display: inline-block; background: #2a3a55; color: var(--accent);
  padding: 3px 10px; border-radius: 4px; font-size: 11px; margin-left: 8px;
  text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;
}
.controls {
  margin: 12px 0; display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  font-size: 13px; color: var(--muted);
}
.controls .stat { padding: 4px 10px; background: var(--card); border-radius: 6px; border: 1px solid var(--border); }
.pair {
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  margin-bottom: 12px; padding: 12px 14px;
}
.pair.removing { opacity: 0.3; transition: opacity 0.4s ease-out; }
.pair-head {
  display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap;
}
.pair-conf {
  font-variant-numeric: tabular-nums;
  font-weight: 700; font-size: 14px; padding: 2px 8px;
  border-radius: 4px; background: var(--bg); color: var(--accent);
}
.pair-conf.very-high { color: #ffd58a; }
.pair-conf.high { color: #9fd8a4; }
.pair-conf.medium { color: #9bc1ff; }
.pair-conf.low { color: var(--muted); }
.pair-signals { font-size: 11px; color: var(--muted); flex-basis: 100%; margin-top: 4px; }
.players { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 10px 0; }
.player {
  background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
  padding: 10px;
}
.player .name { font-size: 15px; font-weight: 600; }
.player .meta { color: var(--muted); font-size: 12px; margin-top: 2px; }
.player .links { font-size: 11px; margin-top: 4px; }
.player .expand-btn {
  background: none; color: var(--accent); border: none; cursor: pointer;
  font-size: 11px; padding: 2px 0; text-decoration: underline;
}
.mini-profile {
  margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border);
  font-size: 12px; color: var(--muted); display: none;
}
.mini-profile.open { display: block; }
.mini-profile table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 4px; }
.mini-profile td { padding: 2px 4px; border-bottom: 1px solid var(--border); }
.mini-profile .win { color: var(--same); }
.mini-profile .loss { color: var(--different); }
.actions { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.actions button {
  padding: 8px 16px; border-radius: 6px; border: 1px solid var(--border);
  background: var(--card); color: var(--fg); cursor: pointer; font-size: 13px;
  min-height: 38px; font-weight: 500;
}
.actions button:hover { background: #21283a; }
.actions button.same { color: var(--same); border-color: var(--same); }
.actions button.different { color: var(--different); border-color: var(--different); }
.actions button.defer { color: var(--defer); }
.toast {
  position: fixed; bottom: 24px; right: 24px;
  background: var(--card); border: 1px solid var(--accent);
  padding: 10px 16px; border-radius: 6px; font-size: 13px;
  opacity: 0; transition: opacity 0.2s; pointer-events: none; max-width: 360px;
}
.toast.show { opacity: 1; }
.toast.error { border-color: var(--different); color: var(--different); }
.empty { color: var(--muted); padding: 20px; text-align: center; }
dialog {
  background: var(--card); color: var(--fg); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px; max-width: 480px;
}
dialog::backdrop { background: rgba(0, 0, 0, 0.6); }
dialog h3 { margin-top: 0; }
dialog .pair-info { font-size: 12px; color: var(--muted); margin-bottom: 10px; }
dialog .winner-pick { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
dialog .winner-pick label {
  padding: 6px 12px; background: var(--bg); border: 1px solid var(--border);
  border-radius: 4px; cursor: pointer; font-size: 13px;
}
dialog .winner-pick label.selected {
  border-color: var(--accent); color: var(--accent);
}
dialog input[type=text], dialog textarea {
  width: 100%; background: var(--bg); color: var(--fg);
  border: 1px solid var(--border); padding: 8px; border-radius: 4px;
  font-size: 13px; font-family: inherit;
}
dialog .dialog-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }
dialog button {
  padding: 8px 16px; border-radius: 4px; border: 1px solid var(--border);
  background: var(--bg); color: var(--fg); cursor: pointer; font-size: 13px;
}
dialog button.primary { background: var(--accent); color: var(--bg); border-color: var(--accent); }
@media (max-width: 700px) {
  .players { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<header>
  <h1>Review queue <span class="banner">local · writes verdicts to repo files</span></h1>
  <p class="lead">
    Triage pending fuzzy-match suggestions. Verdicts are written to
    <code>manual_aliases.json</code> (same person) or
    <code>known_distinct.json</code> (different people) in the repo, so they
    survive DB rebuilds and become part of the next site deploy. Public site
    stays read-only.
  </p>
</header>

<div class="controls">
  <span class="stat">Pending: <span id="count-pending">…</span></span>
  <span class="stat">Same this session: <span id="count-same">0</span></span>
  <span class="stat">Different this session: <span id="count-distinct">0</span></span>
  <button id="refresh-btn" style="margin-left:auto; padding:6px 12px; background:var(--card); border:1px solid var(--border); color:var(--fg); border-radius:6px; cursor:pointer;">Refresh queue</button>
</div>

<div id="queue"><p class="empty">Loading…</p></div>

<div class="toast" id="toast"></div>

<dialog id="same-dialog">
  <h3>Confirm same person</h3>
  <div class="pair-info" id="same-pair-info"></div>
  <p style="font-size:12px; color:var(--muted); margin: 8px 0 4px 0;">Pick the winner (the surviving record):</p>
  <div class="winner-pick" id="same-winner-pick"></div>
  <p style="font-size:12px; color:var(--muted); margin: 12px 0 4px 0;">Reason (optional):</p>
  <input type="text" id="same-reason" placeholder="e.g. Spelling variant — same person">
  <div class="dialog-actions">
    <button onclick="closeSameDialog()">Cancel</button>
    <button class="primary" onclick="submitSame()">Record merge</button>
  </div>
</dialog>

<dialog id="distinct-dialog">
  <h3>Confirm different people</h3>
  <div class="pair-info" id="distinct-pair-info"></div>
  <p style="font-size:12px; color:var(--muted); margin: 8px 0 4px 0;">Reason (optional):</p>
  <input type="text" id="distinct-reason" placeholder="e.g. Different surnames; both A1 active">
  <div class="dialog-actions">
    <button onclick="closeDistinctDialog()">Cancel</button>
    <button class="primary" onclick="submitDistinct()">Record as distinct</button>
  </div>
</dialog>

<script>
let queue = [];
let counts = {same: 0, distinct: 0};
let activePair = null; // for dialogs

function classifyConf(c) {
  if (c >= 0.95) return 'very-high';
  if (c >= 0.88) return 'high';
  if (c >= 0.78) return 'medium';
  return 'low';
}

function escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function renderPair(p, idx) {
  const sigs = (p.reasons || []).map(escHtml).join(' · ');
  const aClass = p.a.latest_class ? `, ${escHtml(p.a.latest_class)}` : '';
  const bClass = p.b.latest_class ? `, ${escHtml(p.b.latest_class)}` : '';
  const aClubs = p.a.clubs ? `<div class="meta">clubs: ${escHtml(p.a.clubs)}</div>` : '';
  const bClubs = p.b.clubs ? `<div class="meta">clubs: ${escHtml(p.b.clubs)}</div>` : '';
  return `
  <div class="pair" data-idx="${idx}">
    <div class="pair-head">
      <span class="pair-conf ${classifyConf(p.confidence)}">${p.confidence.toFixed(2)}</span>
      <span style="font-size:12px; color:var(--muted);">id pair: #${p.a.id} / #${p.b.id}</span>
      <div class="pair-signals">${sigs}</div>
    </div>
    <div class="players">
      <div class="player">
        <div class="name">A · ${escHtml(p.a.name)}</div>
        <div class="meta">${p.a.n}m played${aClass}</div>
        ${aClubs}
        <div class="links">
          <a href="/player/${p.a.id}" target="_blank">live page ↗</a> ·
          <button class="expand-btn" onclick="toggleProfile(${idx}, 'a', ${p.a.id})">Show recent ▾</button>
        </div>
        <div class="mini-profile" id="mini-${idx}-a"></div>
      </div>
      <div class="player">
        <div class="name">B · ${escHtml(p.b.name)}</div>
        <div class="meta">${p.b.n}m played${bClass}</div>
        ${bClubs}
        <div class="links">
          <a href="/player/${p.b.id}" target="_blank">live page ↗</a> ·
          <button class="expand-btn" onclick="toggleProfile(${idx}, 'b', ${p.b.id})">Show recent ▾</button>
        </div>
        <div class="mini-profile" id="mini-${idx}-b"></div>
      </div>
    </div>
    <div class="actions">
      <button class="same" onclick="openSameDialog(${idx})">✓ Same person</button>
      <button class="different" onclick="openDistinctDialog(${idx})">✗ Different people</button>
      <button class="defer" onclick="deferPair(${idx})">↷ Defer</button>
    </div>
  </div>`;
}

function renderQueue() {
  const el = document.getElementById('queue');
  document.getElementById('count-pending').textContent = queue.length;
  if (!queue.length) {
    el.innerHTML = '<p class="empty">Queue empty — nothing to review.</p>';
    return;
  }
  el.innerHTML = queue.map(renderPair).join('');
}

async function loadQueue() {
  try {
    const r = await fetch('/api/queue');
    queue = await r.json();
    renderQueue();
  } catch (e) {
    toast('Failed to load queue: ' + e.message, true);
  }
}

async function toggleProfile(idx, side, pid) {
  const el = document.getElementById(`mini-${idx}-${side}`);
  if (el.classList.contains('open')) {
    el.classList.remove('open');
    return;
  }
  if (!el.dataset.loaded) {
    el.innerHTML = '<em>Loading…</em>';
    try {
      const r = await fetch(`/api/player/${pid}`);
      const data = await r.json();
      el.innerHTML = renderProfile(data);
      el.dataset.loaded = '1';
    } catch (e) {
      el.innerHTML = '<em>Failed to load: ' + escHtml(e.message) + '</em>';
    }
  }
  el.classList.add('open');
}

function renderProfile(p) {
  const aliasList = (p.aliases || []).slice(0, 6).map(escHtml).join(', ');
  const classList = (p.classes || []).slice(0, 4).map(c =>
    `${escHtml(c.year)} ${escHtml(c.label)} <span style="opacity:0.6;">(${escHtml(c.tournament)})</span>`
  ).join(' · ');
  const recentRows = (p.recent_matches || []).map(m => `
    <tr>
      <td>${escHtml(m.date)}</td>
      <td>${escHtml(m.tournament.slice(0, 24))}</td>
      <td>w/ ${escHtml(m.partner)}</td>
      <td>vs ${escHtml(m.opponents)}</td>
      <td class="${m.won ? 'win' : 'loss'}">${escHtml(m.score)}</td>
    </tr>`).join('');
  return `
    <div><strong>Aliases seen:</strong> ${aliasList || '<em>none</em>'}</div>
    ${classList ? `<div style="margin-top:4px;"><strong>Classes:</strong> ${classList}</div>` : ''}
    <table>
      ${recentRows || '<tr><td colspan="5"><em>No recent matches</em></td></tr>'}
    </table>`;
}

function toast(msg, isError) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.toggle('error', !!isError);
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 2400);
}

function deferPair(idx) {
  // Just hide locally — verdict NOT recorded; will reappear on next refresh.
  const el = document.querySelector(`.pair[data-idx="${idx}"]`);
  el.classList.add('removing');
  setTimeout(() => el.remove(), 400);
}

// ---- Same-person dialog ----
function openSameDialog(idx) {
  activePair = queue[idx];
  activePair._idx = idx;
  document.getElementById('same-pair-info').textContent =
    `${activePair.a.name} (${activePair.a.n}m) vs ${activePair.b.name} (${activePair.b.n}m)`;
  // Default winner: more matches; tie → non-CAPS; tie → A
  const a = activePair.a, b = activePair.b;
  let defaultWinner;
  if (a.n !== b.n) defaultWinner = a.n > b.n ? 'a' : 'b';
  else if (a.name.toUpperCase() === a.name && b.name.toUpperCase() !== b.name) defaultWinner = 'b';
  else if (b.name.toUpperCase() === b.name && a.name.toUpperCase() !== a.name) defaultWinner = 'a';
  else defaultWinner = 'a';
  const pick = document.getElementById('same-winner-pick');
  pick.innerHTML = `
    <label data-w="a" class="${defaultWinner==='a'?'selected':''}">
      <input type="radio" name="winner" value="a" ${defaultWinner==='a'?'checked':''} style="display:none">
      A: ${escHtml(a.name)}
    </label>
    <label data-w="b" class="${defaultWinner==='b'?'selected':''}">
      <input type="radio" name="winner" value="b" ${defaultWinner==='b'?'checked':''} style="display:none">
      B: ${escHtml(b.name)}
    </label>`;
  pick.querySelectorAll('label').forEach(lbl => lbl.onclick = () => {
    pick.querySelectorAll('label').forEach(x => x.classList.remove('selected'));
    lbl.classList.add('selected');
    lbl.querySelector('input').checked = true;
  });
  document.getElementById('same-reason').value = '';
  document.getElementById('same-dialog').showModal();
}
function closeSameDialog() { document.getElementById('same-dialog').close(); }

async function submitSame() {
  const winnerSide = document.querySelector('input[name="winner"]:checked').value;
  const w = winnerSide === 'a' ? activePair.a : activePair.b;
  const l = winnerSide === 'a' ? activePair.b : activePair.a;
  const reason = document.getElementById('same-reason').value.trim() || 'Same person; confirmed via review UI';
  try {
    const r = await fetch('/api/same', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({winner_name: w.name, loser_name: l.name, reason}),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'unknown error');
    counts.same++;
    document.getElementById('count-same').textContent = counts.same;
    closeSameDialog();
    toast(`Recorded: ${l.name} → ${w.name}`);
    // Remove from queue UI
    const el = document.querySelector(`.pair[data-idx="${activePair._idx}"]`);
    el.classList.add('removing');
    setTimeout(() => {
      el.remove();
      // Update count
      queue = queue.filter((_, i) => i !== activePair._idx);
      document.getElementById('count-pending').textContent = queue.length;
    }, 400);
  } catch (e) {
    toast('Failed: ' + e.message, true);
  }
}

// ---- Different-people dialog ----
function openDistinctDialog(idx) {
  activePair = queue[idx];
  activePair._idx = idx;
  document.getElementById('distinct-pair-info').textContent =
    `${activePair.a.name} (${activePair.a.n}m) vs ${activePair.b.name} (${activePair.b.n}m)`;
  document.getElementById('distinct-reason').value = '';
  document.getElementById('distinct-dialog').showModal();
}
function closeDistinctDialog() { document.getElementById('distinct-dialog').close(); }

async function submitDistinct() {
  const reason = document.getElementById('distinct-reason').value.trim() || 'Different people; confirmed via review UI';
  try {
    const r = await fetch('/api/distinct', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({a_name: activePair.a.name, b_name: activePair.b.name, reason}),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'unknown error');
    counts.distinct++;
    document.getElementById('count-distinct').textContent = counts.distinct;
    closeDistinctDialog();
    toast(`Recorded as distinct`);
    const el = document.querySelector(`.pair[data-idx="${activePair._idx}"]`);
    el.classList.add('removing');
    setTimeout(() => {
      el.remove();
      queue = queue.filter((_, i) => i !== activePair._idx);
      document.getElementById('count-pending').textContent = queue.length;
    }, 400);
  } catch (e) {
    toast('Failed: ' + e.message, true);
  }
}

document.getElementById('refresh-btn').onclick = loadQueue;
loadQueue();
</script>
</body>
</html>
"""


# ----- HTTP handler ---------------------------------------------------------


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "RallyRankReview/1.0"

    def log_message(self, fmt, *args):  # noqa: D401
        # Quieter logging — one line per request, prefixed.
        sys.stderr.write(f"[review-server] {fmt % args}\n")

    def _send_json(self, code: int, body) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_redirect(self, url: str) -> None:
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def do_GET(self):  # noqa: N802 (stdlib API)
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send_html(PAGE_HTML)
        if path == "/api/queue":
            try:
                suggestions = _fetch_suggestions()
                return self._send_json(200, suggestions)
            except Exception as e:
                return self._send_json(500, {"error": str(e)})
        if path.startswith("/api/player/"):
            try:
                pid = int(path.rsplit("/", 1)[-1])
            except ValueError:
                return self._send_json(400, {"error": "bad player id"})
            try:
                return self._send_json(200, _fetch_player_mini(pid))
            except Exception as e:
                return self._send_json(500, {"error": str(e)})
        if path.startswith("/player/"):
            # Convenience: redirect to the live built site for the full player page.
            try:
                pid = int(path.rsplit("/", 1)[-1])
                return self._send_redirect(f"/site/players/{pid}.html")
            except ValueError:
                pass
        if path.startswith("/site/"):
            # Serve a file from the built static site/. Prevents path traversal.
            sub = path[len("/site/"):]
            target = (PROJECT_ROOT / "site" / sub).resolve()
            site_root = (PROJECT_ROOT / "site").resolve()
            try:
                target.relative_to(site_root)
            except ValueError:
                return self._send_json(403, {"error": "forbidden"})
            if not target.is_file():
                return self._send_json(404, {"error": "not found"})
            data = target.read_bytes()
            self.send_response(200)
            ext = target.suffix.lower()
            ct = {
                ".html": "text/html",
                ".css": "text/css",
                ".js": "application/javascript",
            }.get(ext, "application/octet-stream")
            self.send_header("Content-Type", ct + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        return self._send_json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError) as e:
            return self._send_json(400, {"error": f"bad request body: {e}"})

        if path == "/api/same":
            winner = body.get("winner_name", "").strip()
            loser = body.get("loser_name", "").strip()
            reason = body.get("reason", "").strip() or "Same person; confirmed via review UI"
            if not winner or not loser:
                return self._send_json(400, {"error": "winner_name and loser_name required"})
            if winner == loser:
                return self._send_json(400, {"error": "winner and loser cannot be the same"})
            with _FILE_LOCK:
                added = players.record_same_person(
                    str(ALIASES_PATH), winner, loser, reason=reason
                )
            return self._send_json(200, {"added": added, "winner": winner, "loser": loser})

        if path == "/api/distinct":
            a = body.get("a_name", "").strip()
            b = body.get("b_name", "").strip()
            reason = body.get("reason", "").strip() or "Different people; confirmed via review UI"
            if not a or not b:
                return self._send_json(400, {"error": "a_name and b_name required"})
            with _FILE_LOCK:
                added = players.record_distinct(
                    str(DISTINCT_PATH), a, b, reason=reason
                )
            return self._send_json(200, {"added": added, "a": a, "b": b})

        return self._send_json(404, {"error": "not found"})


def serve(port: int = 8765, open_browser: bool = True) -> None:
    """Start the local review server. Blocks until Ctrl-C."""
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")

    addr = ("127.0.0.1", port)
    server = ThreadingHTTPServer(addr, ReviewHandler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Review server: {url}  (Ctrl-C to stop)")
    print(f"  manual_aliases: {ALIASES_PATH}")
    print(f"  known_distinct: {DISTINCT_PATH}")
    if open_browser:
        # Slight delay so the print appears before the browser launches.
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n(stopped)")
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="RallyRank local review server")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true",
                   help="Don't auto-open the browser.")
    args = p.parse_args()
    serve(port=args.port, open_browser=not args.no_browser)
