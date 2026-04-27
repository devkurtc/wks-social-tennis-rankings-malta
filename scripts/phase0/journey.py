"""Rating-journey data builder.

Pure function: given a sqlite connection and a focal player id, returns the
dict that the rating-journey JS visualization expects on
`window.RATING_DATA`. No file I/O. No assumptions about who the focal is.

Schema (matches mockups/kurt-data.js, with `window_start`/`window_end` now
spanning the focal's full rating history rather than a fixed 12-month window):

    {
      focal_id: int, focal_name: str,
      window_start: "YYYY-MM-DD", window_end: "YYYY-MM-DD",
      chart_pids: [focal_id, ...up to N most-co-played neighbours],
      players: {pid_str: {name, short}},
      events: [
        {match_id, date, tournament, division,
         team1, team2, winner (1|2|0), is_tied,
         score (display string), a_games, b_games,
         expected1 (P(team1 wins) under OpenSkill PL),
         deltas, mu_pre, sigma_pre, new_player, upset}
      ],
      series: {pid_str: [{date, score (mu-3sigma)}, ...]}
    }

If the focal has no rating_history rows under `model_name`, returns None —
caller (generate_site) skips the journey section entirely on that page.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta

from openskill.models import PlackettLuce

# OpenSkill PL defaults — matches scripts/phase0/rating.py constants.
DEFAULT_MU = 25.0
DEFAULT_SIGMA = 25.0 / 3.0

# How many co-played neighbours to draw on the chart in addition to the focal.
DEFAULT_NEIGHBOUR_COUNT = 7


def _title_name(name: str) -> str:
    return " ".join(w.capitalize() for w in name.split()) if name.isupper() else name


def compute_journey_data(
    conn: sqlite3.Connection,
    focal_id: int,
    model_name: str,
    neighbour_count: int = DEFAULT_NEIGHBOUR_COUNT,
) -> dict | None:
    conn.row_factory = sqlite3.Row

    has_history = conn.execute(
        "SELECT 1 FROM rating_history WHERE player_id = ? AND model_name = ? LIMIT 1",
        (focal_id, model_name),
    ).fetchone()
    if not has_history:
        return None

    matches = conn.execute(
        """
        SELECT MIN(m.id) AS match_id, m.played_on, m.division,
               t.name AS tournament,
               msa.player1_id AS a1, msa.player2_id AS a2,
               msa.games_won AS a_games, msa.won AS a_won,
               msb.player1_id AS b1, msb.player2_id AS b2,
               msb.games_won AS b_games, msb.won AS b_won
        FROM matches m
        JOIN tournaments t ON t.id = m.tournament_id
        JOIN match_sides msa ON msa.match_id = m.id AND msa.side = 'A'
        JOIN match_sides msb ON msb.match_id = m.id AND msb.side = 'B'
        WHERE m.superseded_by_run_id IS NULL
          AND ? IN (msa.player1_id, msa.player2_id, msb.player1_id, msb.player2_id)
        GROUP BY m.played_on, msa.player1_id, msa.player2_id,
                 msb.player1_id, msb.player2_id
        ORDER BY m.played_on, MIN(m.id)
        """,
        (focal_id,),
    ).fetchall()
    matches = [dict(m) for m in matches]
    if not matches:
        return None

    involved: set[int] = set()
    for m in matches:
        for k in ("a1", "a2", "b1", "b2"):
            if m[k] is not None:
                involved.add(m[k])

    placeholders = ",".join("?" * len(involved))
    names: dict[int, str] = {}
    for row in conn.execute(
        f"SELECT id, canonical_name FROM players WHERE id IN ({placeholders})",
        tuple(involved),
    ):
        names[row["id"]] = _title_name(row["canonical_name"])

    first_name_counts = Counter(n.split()[0] for n in names.values() if n)
    short_names: dict[int, str] = {}
    for pid, full in names.items():
        parts = full.split()
        if not parts:
            short_names[pid] = full
            continue
        first = parts[0]
        if first_name_counts[first] > 1 and len(parts) > 1:
            short_names[pid] = f"{first} {parts[-1][0]}."
        else:
            short_names[pid] = first

    rh: dict[int, list[dict]] = defaultdict(list)
    for row in conn.execute(
        f"""
        SELECT rh.player_id, rh.match_id, m.played_on, rh.mu_after, rh.sigma_after
        FROM rating_history rh
        JOIN matches m ON m.id = rh.match_id
        WHERE rh.model_name = ? AND rh.player_id IN ({placeholders})
        ORDER BY rh.player_id, m.played_on, rh.match_id
        """,
        (model_name, *involved),
    ):
        rh[row["player_id"]].append(
            {
                "played_on": row["played_on"],
                "match_id": row["match_id"],
                "mu": row["mu_after"],
                "sigma": row["sigma_after"],
            }
        )

    def rating_just_before(pid: int, played_on: str, match_id: int) -> tuple[float, float]:
        prev = None
        for e in rh.get(pid, []):
            same_match = e["match_id"] == match_id
            is_before = e["played_on"] < played_on or (
                e["played_on"] == played_on and e["match_id"] < match_id and not same_match
            )
            if is_before:
                prev = e
            elif e["played_on"] > played_on or same_match:
                break
        if prev:
            return prev["mu"], prev["sigma"]
        return DEFAULT_MU, DEFAULT_SIGMA

    def rating_at_match(pid: int, mid: int) -> tuple[float | None, float | None]:
        for e in rh.get(pid, []):
            if e["match_id"] == mid:
                return e["mu"], e["sigma"]
        return None, None

    pl = PlackettLuce()
    events: list[dict] = []
    for m in matches:
        mid = m["match_id"]
        team_a = [m["a1"]] + ([m["a2"]] if m["a2"] else [])
        team_b = [m["b1"]] + ([m["b2"]] if m["b2"] else [])

        is_tied = (m["a_won"] == 0) and (m["b_won"] == 0)
        if m["a_won"]:
            winner = 1
        elif m["b_won"]:
            winner = 2
        elif (m["a_games"] or 0) > (m["b_games"] or 0):
            winner = 1
        elif (m["b_games"] or 0) > (m["a_games"] or 0):
            winner = 2
        else:
            winner = 0

        pre = {pid: rating_just_before(pid, m["played_on"], mid) for pid in team_a + team_b}
        post = {pid: rating_at_match(pid, mid) for pid in team_a + team_b}

        sets = conn.execute(
            "SELECT side_a_games, side_b_games FROM match_set_scores "
            "WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        score = (
            " ".join(f"{s['side_a_games']}-{s['side_b_games']}" for s in sets)
            if sets
            else f"{m['a_games'] or 0}-{m['b_games'] or 0}"
        )

        ratings_a = [pl.rating(mu=pre[pid][0], sigma=pre[pid][1]) for pid in team_a]
        ratings_b = [pl.rating(mu=pre[pid][0], sigma=pre[pid][1]) for pid in team_b]
        try:
            expected = pl.predict_win([ratings_a, ratings_b])
            ex_a = float(expected[0])
        except Exception:
            ex_a = 0.5

        deltas: dict[int, float] = {}
        for pid in team_a + team_b:
            mu_pre, sig_pre = pre[pid]
            mu_post, sig_post = post[pid]
            score_pre = mu_pre - 3 * sig_pre
            score_post = (mu_post - 3 * sig_post) if mu_post is not None else score_pre
            deltas[pid] = round(score_post - score_pre, 4)

        new_player_flags = {str(pid): pre[pid][1] > 7.0 for pid in team_a + team_b}

        upset = (winner == 1 and ex_a < 0.40) or (winner == 2 and ex_a > 0.60)

        events.append(
            {
                "match_id": mid,
                "date": m["played_on"],
                "tournament": m["tournament"],
                "division": m["division"] or "",
                "team1": team_a,
                "team2": team_b,
                "winner": winner,
                "is_tied": is_tied,
                "score": score,
                "a_games": m["a_games"] or 0,
                "b_games": m["b_games"] or 0,
                "expected1": round(ex_a, 4),
                "deltas": {str(k): v for k, v in deltas.items()},
                "mu_pre": {str(pid): round(pre[pid][0], 3) for pid in team_a + team_b},
                "sigma_pre": {str(pid): round(pre[pid][1], 3) for pid in team_a + team_b},
                "new_player": new_player_flags,
                "upset": upset,
            }
        )

    co_played: Counter[int] = Counter()
    for ev in events:
        for pid in ev["team1"] + ev["team2"]:
            if pid != focal_id:
                co_played[pid] += 1
    chart_pids = [focal_id] + [pid for pid, _ in co_played.most_common(neighbour_count)]

    # Window: one day before the earliest event involving any chart pid → last event date.
    # That gives every chart line a "default starting" point that immediately evolves
    # into their first observed rating, which is what the user requested for 1-match
    # players ("show default starting + 1st match"). For multi-match players it just
    # surfaces the first jump out of the default; visually nicer than starting mid-curve.
    first_dates = []
    for pid in chart_pids:
        ev_dates = [ev["date"] for ev in events if pid in ev["team1"] or pid in ev["team2"]]
        if ev_dates:
            first_dates.append(min(ev_dates))
    if not first_dates:
        return None
    earliest = min(first_dates)
    window_start = (date.fromisoformat(earliest) - timedelta(days=1)).isoformat()
    window_end = max(ev["date"] for ev in events)

    series: dict[int, list[dict]] = {}
    for pid in chart_pids:
        pts: list[dict] = []
        mu0, sig0 = rating_just_before(pid, window_start, 0)
        pts.append({"date": window_start, "score": round(mu0 - 3 * sig0, 4)})
        running_mu, running_sigma = mu0, sig0
        for ev in events:
            if pid in ev["team1"] or pid in ev["team2"]:
                mu_p, sig_p = rating_at_match(pid, ev["match_id"])
                if mu_p is not None:
                    running_mu, running_sigma = mu_p, sig_p
                pts.append({"date": ev["date"], "score": round(running_mu - 3 * running_sigma, 4)})
        if pts[-1]["date"] != window_end:
            pts.append({"date": window_end, "score": round(running_mu - 3 * running_sigma, 4)})
        series[pid] = pts

    return {
        "focal_id": focal_id,
        "focal_name": names.get(focal_id, str(focal_id)),
        "window_start": window_start,
        "window_end": window_end,
        "chart_pids": chart_pids,
        "players": {
            str(pid): {"name": names[pid], "short": short_names[pid]} for pid in involved
        },
        "events": events,
        "series": {str(pid): series[pid] for pid in chart_pids},
    }
