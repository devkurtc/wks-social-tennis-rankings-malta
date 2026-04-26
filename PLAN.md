# RallyRank — Doubles Tennis Ranking System: Plan

**Public product name:** RallyRank · **Status:** ✅ Phase 0 complete (2026-04-26) · Phase 1 ready to begin · **Owner:** Kurt Carabott · **Last updated:** 2026-04-26
**Repo:** https://github.com/devkurtc/wks-social-tennis-rankings-malta (internal repo name kept descriptive)

This document captures the plan, the alternatives considered, and the tradeoffs of each major decision. It's intentionally argumentative — every recommendation is paired with the strongest counter-arguments so we can push back before writing code.

---

## 1. Problem & goals

Build a multi-club tennis doubles ranking system that:

1. **Ranks doubles players** continuously (UTR/WTN-style: each new match updates ratings).
2. **Recommends optimal pair combinations** when assembling team-tournament rosters — including modeling partner chemistry, not just summing individual skill.
3. **Ingests tournament results agentically** — club admins upload spreadsheets/PDFs and an LLM-driven pipeline extracts results into a normalized schema with admin review.

**Success looks like:** a self-hosted web app where (a) any visitor can browse rankings and player history, (b) club admins can drop new tournament files in and have them flow into the rating engine within minutes, and (c) team captains can input a roster and get back data-driven pairing suggestions.

**Non-goals (for now):**
- Singles ranking — **fully out of scope** (decided 2026-04-25). Bulk-load parsers in Phase 1 skip singles files. Agentic ingestion in Phase 3 detects singles format, archives the file in MinIO, and reports "out of scope — no DB rows created." The schema's `match_type` column reserves the option to add singles later if scope expands.
- Live match scoring / on-court data entry.
- Tournament management / draws / scheduling.
- Mobile app (web is responsive; native apps later if needed).
- Public user accounts beyond admins. Public is read-only.

---

## 2. Users

| Role | What they do | Trust level |
|---|---|---|
| **Public** | Browse rankings, player profiles, rating history. No login. | Read-only |
| **Club admin** | Upload tournament documents, review/confirm extracted matches, merge duplicate players, edit match data. | Trusted, but every action audited |
| **Super admin** | Manage clubs, manage admin accounts, run cross-club operations (player linking across clubs). | Fully trusted |
| *(Future)* **Player** | View own profile, claim their player record, opt out of public listing. | Verified-only |

---

## 3. Data sources (current)

`_DATA_/VLTC/` — ~40 Excel files from Vittoriosa Lawn Tennis Club, 2017–2026. These are publicly available from the VLTC club website, so re-hosting them in this repo carries no additional disclosure risk.

**Backfill scope (decided 2026-04-25):** all doubles tournaments 2017–2026 are in scope for ingestion. Singles are out of scope (§1). Old matches don't distort current ratings because of time decay — see §5.2.

Two structural patterns observed:

1. **Division-style doubles**: fixed pairs (e.g. `"Duncan D'Alessandro/Clayton Zammit Cesare"`) play round-robins within a division. One sheet per division.
2. **Team tournaments** (e.g. Antes/Joe Carabott Memorial): teams A–F with rotating partners per night. "Day N" sheets list each rubber with both players named individually per side.

Characteristics of the data:
- Presentation-shaped, not data-shaped (merged headers, blank spacer rows, totals via formulas).
- Player names are free text — same person appears with curly vs straight apostrophes, abbreviated first names, occasional typos.
- No player IDs, no match IDs, no normalized table.
- Set scores recorded (e.g. 6-4, 6-3) plus sometimes a 10-point match tiebreak.

**Implication:** Whatever ingests these has to do real entity resolution. This is the single highest-risk part of the project for data quality.

---

## 4. Architecture

```
┌───────────────────────────────────────────────────────────────┐
│  Proxmox host                                                 │
│                                                               │
│  ┌─ LXC or VM running docker-compose ────────────────────┐    │
│  │                                                       │    │
│  │  Caddy (TLS, reverse proxy)                           │    │
│  │     │                                                 │    │
│  │     ▼                                                 │    │
│  │  Next.js (web + API routes, NextAuth)                 │    │
│  │     │ ──────────────► Postgres (data + audit_log)     │    │
│  │     │ ──── enqueue ─► Redis ──── consumed by ─┐       │    │
│  │     │                                          ▼      │    │
│  │     │                              Python worker      │    │
│  │     │                              ├─ rating engine   │    │
│  │     │                              └─ ingestion agent │    │
│  │     ▼                                          │      │    │
│  │  MinIO (uploaded files, retained) ◄────────────┘      │    │
│  │                                                       │    │
│  └───────────────────────────────────────────────────────┘    │
│                                                               │
│  External: Claude API (used by ingestion agent only)          │
└───────────────────────────────────────────────────────────────┘
```

**Why split Next.js and a Python worker?** The rating engine (OpenSkill) and the ingestion agent are both Python-native. Next.js handles auth, UI, and API. They communicate via Redis job queue. The split also means ingestion or recompute jobs don't block web responses.

---

## 5. Major decisions — pros & cons

For each decision: alternatives considered, then the recommendation.

### 5.1 Web framework

| Option | Pros | Cons |
|---|---|---|
| **Next.js + TypeScript** *(recommended)* | Mature ecosystem; server components reduce client JS; NextAuth handles auth well; one repo, two surfaces (UI + API); Postgres clients are excellent | Two languages in the project (TS + Python); type duplication between frontend types and Python worker schemas |
| Django + HTMX | One language end-to-end; admin UI for free; mature ORM; auth built in | UI is server-rendered HTML — fine for admin, weaker for richer interactions like the pair recommender; smaller modern frontend ecosystem |
| FastAPI + React (Vite) | Cleanest API/frontend separation; Python end-to-end on backend | More moving parts than Next.js; you build auth yourself |
| SvelteKit | Smaller bundle, simpler reactivity model | Smaller ecosystem; less library support for the niche needs we'll hit |

**Recommendation: Next.js + TypeScript.** The pair recommender and rating-history charts are interactive enough to want client-side reactivity, and NextAuth removes a meaningful amount of work. The TS/Python split is real but manageable — we share schemas via JSON Schema or a Pydantic→Zod codegen.

**Counter-argument worth considering:** if you're more comfortable in Python than TS, Django + HTMX is genuinely competitive and removes the second-language tax. Worth being honest about.

### 5.2 Rating algorithm

| Option | Pros | Cons |
|---|---|---|
| **OpenSkill (Plackett-Luce)** *(recommended)* | Bayesian (skill + uncertainty); native team support; MIT-licensed; pure Python; faster than TrueSkill; multiple model variants if Plackett-Luce underperforms | Less name recognition than UTR; needs custom score-margin handling |
| TrueSkill (Microsoft) | Well-known; native team support; uncertainty | Older; slower than OpenSkill; less actively developed |
| Glicko-2 | Simple; well-documented; tennis-proven | Designed for 1v1 — you hand-roll team aggregation, losing information |
| Custom UTR-style Elo | Score margin native; matches mental model tennis players already have | No uncertainty; reinventing what OpenSkill gives you for free; harder to defend "why is Player X's rating exactly 4.7?" |
| Bayesian custom (PyMC / Stan) | Most flexible; can model partner effects, court surface, time decay all jointly | Massive overkill for a few thousand matches; harder to maintain; slow to update incrementally |

**Recommendation: OpenSkill (Plackett-Luce) as the primary / champion model.** Bayesian uncertainty matters here because most VLTC players will have <20 matches in the dataset — pretending we have high confidence in their rating would be dishonest. The team-native API removes a class of bugs in how we aggregate partner ratings.

The system runs a *configurable set* of models, not just one — see §5.7 for the champion/challenger architecture and the phased rollout. OpenSkill PL is what drives public rankings; other models run in shadow.

**Score margin (revised 2026-04-26 after `_RESEARCH_/Doubles_Tennis_Ranking_System.docx` §4):** the actual-score input to the rating math is the **universal games-won proportion**:

```
S_A  =  games_won_A  /  (games_won_A  +  games_won_B)
S_B  =  1 - S_A
```

Range `[0, 1]`. A 6-0 6-0 win → `S_A = 1.0`; 7-6 7-5 win → `S_A ≈ 0.56`; even split → `0.5` (no rating movement, mathematically correct — draws are uninformative). This naturally normalizes 18-game format events vs 2-set matches with no special-casing — the same formula works everywhere.

This replaces the earlier "tanh weight multiplier" approach. Adopting `S` as the actual score (rather than a multiplier on Δ) plugs cleanly into OpenSkill's existing actual-vs-expected mechanism instead of bolting on a side channel.

**Forfeit / walkover handling (per `_RESEARCH_/...` §11.4):** record as `S_winner = 0.90`, `S_loser = 0.10` — NOT `1.0 / 0.0`. A walkover is not a played match; treating it as a max-signal win over-rewards the recipient. The 0.90/0.10 split preserves a small rating effect without dominating.

**Time decay (decided 2026-04-25):** enabled via OpenSkill's `tau` parameter (sigma drift per rating period). During inactivity, μ stays frozen while σ grows — the system becomes less certain about a player it hasn't observed. Returning players' new matches then move μ sharply because the prior uncertainty is high. Rating period defaults to monthly; `tau` and the period length are tunable in Phase 0. Independently, the public leaderboard's default view filters to "active in the last N months" (UX concern, not a rating-engine concern); inactive players are still rated, just not surfaced by default.

**Pair chemistry** is a separate residual model: for each pair that has played together ≥N times, compute (actual win rate − model-predicted win rate). Use this residual as a bonus/penalty when the pair recommender considers that combination. For pairs with no shared history, residual = 0 (assume neutral chemistry). Equivalent to "Partner Synergy" in `_RESEARCH_/...` §12.

#### 5.2.1 Future enhancements queued for Phase 1+

The following ideas (sourced from `_RESEARCH_/Doubles_Tennis_Ranking_System.docx`) are deliberately deferred — Phase 0's job is to validate the *base* approach before layering tunables on top. Each is a candidate for the Phase 0 retrospective (T-P0-010) to schedule.

| Enhancement | Source | Phase | Notes |
|---|---|---|---|
| **Rating drift toward division mean for long absences** | §9.2 | 1 | Beyond pure σ-growth, also drift μ toward the player's division mean for absences ≥3 missed periods (1%/period for 3-5, 2%/period for 6-11, 4%/period for 12+). Attacks the "ghost rating" problem where a long-absent player's μ is pinned at peak indefinitely. |
| **Division K-factor multipliers** | §8.1, §8.2 | 1 | Per-division weight on rating updates (M1=1.0, M2=0.9, M3=0.8, M4=0.7; L1=1.0, L2=0.87, L3=0.73). Requires per-division calibration data — not Phase 0. |
| **Tournament-type K multipliers** | §8.3 | 1 | Championship Finals=1.20×, Standard=1.0×, Friendly=0.30×, etc. Requires a new `tournaments.tier` schema column populated during Phase 1 bulk-load. |
| **Per-division starting ratings (the *pattern*, not the numbers)** | §2.2 | 1 | Seed new players at division-specific μ rather than a global default. Their numbers are Glicko-2 scale (~1500); OpenSkill PL is on a μ=25 scale — calibrate during Phase 1. |
| **Investigate: OpenSkill PL native team apportionment vs explicit partner-weighting** | §7 | 0/1 | Their "Modified Glicko-2" requires explicit `Δ × weight × 2` per player to handle teams (because base Glicko-2 is 1v1). OpenSkill PL handles teams natively — open question whether its apportionment is similar. Owned by `rating-engine-expert` agent during T-P0-006. If they diverge meaningfully, layer an explicit weighting on top of OpenSkill too. |

### 5.3 Ingestion approach

| Option | Pros | Cons |
|---|---|---|
| **Agentic (Claude API + admin review)** *(recommended)* | Handles arbitrary new spreadsheet formats without writing parsers; future-proof against new clubs; admin review keeps a human in the loop on ambiguous matches | API costs (~$0.05–0.20 per file); accuracy 80–90% on first pass; needs robust review UI |
| Hand-written parsers per template | Deterministic; free to run; debuggable | Every new tournament format = new code; will eventually hit a layout we can't parse cleanly |
| Hybrid: try parser first, fall back to agent | Cheapest in steady state | Most complex to maintain; two failure modes |

**Recommendation: Agentic, with hand-written parsers used only in Phase 1 to bulk-load existing VLTC history.** Once the agent ingestion is built, retire the hand-written parsers — they're not worth maintaining alongside the agent.

**Open question:** vision (screenshot → Claude vision model) vs structured (XLSX → cells → Claude with text). Probably structured for XLSX, vision fallback for PDFs and image scans. Decide during Phase 3.

#### 5.3.1 Ingestion review pattern (decided 2026-04-25)

**Pattern: auto-accept with post-hoc quality report and re-process workflow.** No human review gate before matches land in the DB; instead, every ingestion run produces a quality report the admin reviews after the fact. If the admin spots a mistake, they trigger a re-process which cleanly supersedes the previous run's matches.

**Required architectural properties:**

1. **Idempotent, reversible ingestion.** Each upload of a file creates an `ingestion_runs` row with a unique `id`. Every match produced carries `ingestion_run_id` as a foreign key. Re-processing a file means: mark all matches from prior runs of that source file as `superseded_by_run_id = <new run>`; the rating engine ignores superseded matches and recomputes affected ratings from `rating_history` forward.
2. **Quality report per run.** Generated automatically at the end of each ingestion. Sections:
   - Summary: matches detected, players detected, run duration, agent/model version
   - Low-confidence rows (highlighted) with reason: missing date, ambiguous player name, score that violates tennis rules, etc.
   - New player names that don't match any existing alias (proposed merges)
   - Anomalies: dates outside the file's apparent year, scores like 6-7 in a best-of-3 set where no tiebreak is recorded, rubbers where one side has only one player named
   - Diff vs the previous run of the same file (if any)
3. **Visible-everywhere unreviewed reports.** Dashboard widget on admin home: "X ingestion reports unreviewed" with a click-through. Optional email digest. Login banner if any report is older than N days unreviewed. Quiet reports = ignored reports.
4. **Re-process action** is one click on the report page → confirms → enqueues a new ingestion run on the same source file → previous run's matches are marked superseded → ratings recompute → audit_log entry `ingestion.reprocessed` with reason text.

**Pros:**
- Zero workflow friction in the steady state — uploads land immediately
- Quality report catches problems without blocking ingestion
- Re-process gives a clean fix path that doesn't require manual DB edits
- Admin attention is spent on detected issues, not on the 95% of routine matches

**Cons:**
- **Human-skip risk**: if admins don't read reports, bad data persists. Mitigated by visibility (dashboard widget, banner, optional email) but not eliminated.
- Ratings may be briefly wrong between ingestion and admin re-process. Acceptable for this domain — tournament rankings are not safety-critical.
- Idempotency complexity in the schema (`ingestion_run_id`, `superseded_by_run_id`) and rating-engine logic (skip superseded matches, recompute on supersede). Real but contained.

**Out of scope for this pattern:**
- Public users seeing pending/under-review matches separately from confirmed ones — there's no "pending" state, just current and superseded.
- Partial supersede (replace some matches from a run, keep others) — too complex; if anything is wrong, re-process the whole file.

### 5.4 Player identity (entity resolution)

The hardest non-obvious problem. Three layers:

1. **Within a single file**: "Duncan D'Alessandro" with curly vs straight apostrophe should be one player. → Normalize whitespace, apostrophes, casing on read.
2. **Within a club, across files/years**: "Kurt Carabott" in 2024 and 2026 is the same player. → Fuzzy match (Levenshtein + initials) → propose match → admin confirms.
3. **Across clubs**: "Kurt Carabott" at VLTC and "K. Carabott" at another club is the same player. → Same flow; propose, admin confirms, link records.

**Schema implication:** `players` has a global `id`. `player_aliases` table records every name variant ever seen, with the source. `player_club_memberships` is many-to-many. Merging two players is a first-class operation, audited.

**Pros of this approach:** correctness, auditability, recoverable from mistakes.
**Cons:** the merge UI is real work. We can't fully automate it because false-positive merges are catastrophic (mixing two real people's careers).

### 5.5 Audit logging

| Option | Pros | Cons |
|---|---|---|
| **App-layer audit_log table** *(recommended)* | Captures intent (`match.edited` not `UPDATE matches`); easy to filter by action type; structured JSON before/after | Code must remember to log; if developer forgets, action is invisible |
| Postgres triggers | Can't be bypassed; uniform | Captures only row-level diffs without semantic context; reconstructing intent is painful |
| Both | Belt and suspenders | Doubles the work; conflicts of truth |

**Recommendation: app-layer.** Wrap mutations in a small helper that takes `(actor, action, entity, before, after)` and writes to `audit_log` in the same transaction. Catch the "developer forgot" risk by review, not by triggers.

### 5.6 Hosting & deployment

Already locked: Proxmox host, LXC or VM, docker-compose. Open sub-questions:

- **LXC vs VM?** LXC is lighter and snapshots faster; VM gives stronger isolation. For this workload (modest, single-tenant infrastructure) LXC is fine.
- **Backups?** Postgres dumps daily to a Proxmox-mounted volume + a remote (S3-compatible) target. MinIO bucket replicated. Snapshot the LXC weekly.
- **TLS?** Caddy with automatic Let's Encrypt against your domain. If the box isn't internet-exposed for ACME, use a DNS challenge.
- **Secrets?** `.env` files inside the LXC, not in git. Consider Doppler / SOPS later if multiple admins manage deployment.

### 5.7 Multi-model evaluation (champion / challenger)

**Recommendation: schema is model-agnostic from day one; multiple models in operation are phased in over time.**

Single-model rating systems hide their own bugs. When OpenSkill ranks Player X very differently from Glicko-2, that disagreement is valuable — usually it flags a data-quality issue specific to that player, sometimes a property of the model that doesn't fit our use case. Multi-model surfaces it; single-model doesn't.

**Architecture (champion / challenger pattern):**

```
Match lands ──► fan-out to N evaluators (worker jobs)
              ├─ OpenSkill PL  ─► ratings(model='openskill_pl')   ← CHAMPION
              ├─ OpenSkill BT  ─► ratings(model='openskill_bt')   ← challenger (Phase 1+)
              ├─ Glicko-2      ─► ratings(model='glicko2')        ← challenger (Phase 1+)
              └─ ...
```

The CHAMPION drives public rankings and pair recommendations. CHALLENGERS run alongside in shadow — they emit ratings and predictions but don't affect what users see.

**Champion promotion is data-driven:** each model emits a `P(team A wins)` prediction before each match. When the match resolves, log Brier score (or log-loss) per model to `model_scoreboard`. A challenger can be promoted to champion when it has lower mean loss over a defined rolling window — and only via an audited two-step admin confirmation.

**Phasing:**
- **Phase 0** — schema includes `model_name` column; only OpenSkill PL runs. Goal is validating *any* model on the data.
- **Phase 1** — add Glicko-2 (or one OpenSkill variant) as the first challenger. Compare leaderboards by hand. No dashboard yet.
- **Phase 2** — admin dashboard: side-by-side leaderboards, "biggest disagreements" view, predictive-accuracy chart per model.
- **Phase 3+** — more challengers if useful; promotion automation only if a clear winner emerges.

**Pros:**
- Catches model bugs and data quality issues early (disagreements are diagnostic)
- Defensible: "four models agree this player is top 10" is harder to argue with than one
- Enables data-driven model promotion via predictive scoring
- Engineering cost is one-time (schema); per-model addition after that is cheap

**Cons:**
- ~Nx compute per recompute (still trivial at this scale; each rating update is microseconds)
- Schema cost (`model_name` column on every rating-related table)
- Admin UI for the dashboard and promotion flow is real Phase 2 work
- "Ensemble paralysis" risk — admin can't decide which model is right when they confidently disagree

### 5.8 Human-in-the-loop feedback channels

**Recommendation: a small set of typed feedback channels, each producing a structured signal a model or admin queue can act on. Avoid generic "comments" boxes.**

Generic free-text feedback degenerates into a graveyard of unactionable text. Typed channels stay actionable.

**Channels (built incrementally with the underlying features):**

| Channel | Phase | Signal | Action |
|---|---|---|---|
| Player merge | 1 | "these two records are the same person" | merge records, recompute affected ratings, audit |
| Match exclusion | 2 | "this match should not count, reason: walkover / wrong-division / etc." | exclude from rating computation, audit |
| Score correction | 2 | "set 2 was 6-3 not 6-4" | edit match, recompute affected ratings, audit |
| Informal match upload | 3 | "add these informal results" | new ingestion source, marked `informal=true` in schema |
| Pair-rec accept / reject | 4 | captain accepted suggestion B instead of recommended A | passive log → signal for chemistry-residual model |
| Manual rating pin | 5+ | "freeze this player's rating at X for Y reason" | rare escape hatch; very loud audit log entry; resist as long as possible |

**Rules common to all channels:**
- Every action writes to `audit_log` with a semantic type (e.g. `match.excluded`, `player.merged`).
- Auto-applying feedback to ratings is allowed for typed signals (merges, exclusions, corrections) — never for unstructured text.
- Pair-rec accept/reject feeds a separate `model_feedback` table that the chemistry-residual model can train on.
- Rating pins require justification text + admin two-step confirm + a visible badge on the affected player's public profile ("rating manually adjusted, reason: X").

**Out of scope (deliberately):**
- Subjective "rate this player 1–10" feedback — bias-prone, low signal value
- Public crowd-sourced corrections — admin-only for v1
- Auto-acting on a single feedback signal without admin confirmation for high-impact actions (merges, pins)

### 5.9 Public visibility (decided 2026-04-25)

**Decision: all rankings, profiles, and match histories are fully public. No opt-out workflow built in v1.**

Rationale: source data is already public from each contributing club's website; this product re-presents and enriches that public information. User opted to keep visibility binary and operationally simple.

**What this means for v1:**
- No `visibility` flag on `players`
- No "Hidden Player" placeholder rendering
- No opt-out request workflow
- Simpler leaderboard, profile, and match-card UI

**What's still required for legal compliance (cheap to add later, NOT built upfront):**
- An admin "remove player" action — for **GDPR Article 17 (Right to Erasure)** requests, which cannot be contractually waived under EU law. When a request arrives: admin uses the action; player record + their `match_sides` rows are deleted; ratings recomputed; `audit_log` records the takedown with reason and requesting party.
- A privacy notice on the public site stating what's processed, the lawful basis (legitimate interest + public sources), and how to file a Right-to-Erasure request. Add in Phase 2.
- The admin action can be added on first request — no need to pre-build.

**Escalation path:** if takedown requests become routine (>1/month sustained), revisit and add a per-player `visibility` boolean (the "Option B" we deliberately skipped). Cheap migration: add column + surface the admin action through the existing player profile UI.

---

## 6. Data model (initial sketch)

```sql
-- Identity
clubs(id, name, slug, created_at)
users(id, email, name, role)  -- role: 'super_admin' | 'club_admin' | 'viewer'
user_club_roles(user_id, club_id, role)

players(id, canonical_name, gender, dob_year, created_at, merged_into_id)
player_aliases(id, player_id, raw_name, source_file_id, first_seen_at)
player_club_memberships(player_id, club_id, joined_year, left_year)

-- Tournaments and matches
source_files(id, club_id, original_filename, storage_key, sha256, uploaded_by, uploaded_at)

ingestion_runs(id, source_file_id, status, agent_version, started_at, completed_at,
               raw_extraction_jsonb, quality_report_jsonb,
               reviewed_at, reviewed_by_user_id, supersedes_run_id)
  -- status: 'running' | 'completed' | 'failed' | 'superseded'
  -- quality_report_jsonb: structured per §5.3.1 (low-conf rows, anomalies, new aliases)
  -- supersedes_run_id: filled when this run is a re-process of a previous run

tournaments(id, club_id, name, year, format, source_file_id)
  -- format: 'doubles_division' | 'doubles_team' | 'singles_*'

matches(id, tournament_id, played_on, match_type, division, round,
        ingestion_run_id, superseded_by_run_id, informal)
  -- match_type: 'doubles' only in v1; 'singles' reserved but not used (§1 non-goals)
  -- superseded_by_run_id: NULL = active; non-NULL = this match was replaced by a re-process
  -- informal: TRUE for matches added via the informal-upload HITL channel
  -- Active-match index: WHERE superseded_by_run_id IS NULL

match_sides(match_id, side, player1_id, player2_id, sets_won, games_won, won)
  -- two rows per match (side 'A' and 'B')

match_set_scores(match_id, set_number, side_a_games, side_b_games, was_tiebreak)

-- Ratings (model-agnostic from day one — see §5.7)
ratings(player_id, model_name, mu, sigma, last_updated_at, n_matches)
  -- PRIMARY KEY (player_id, model_name)
rating_history(id, player_id, model_name, match_id, mu_after, sigma_after, computed_at)
pair_chemistry(player1_id, player2_id, model_name, residual, n_matches_together, last_updated_at)
  -- PRIMARY KEY (player1_id, player2_id, model_name)

-- Multi-model evaluation
model_predictions(id, match_id, model_name, side_a_win_prob, predicted_at)
model_scoreboard(id, model_name, period_start, period_end, n_predictions,
                 mean_brier_score, mean_log_loss)
champion_history(id, model_name, promoted_at, promoted_by_user_id, demoted_at, reason)

-- HITL feedback signals (typed — see §5.8)
model_feedback(id, ts, source, signal_type, payload_jsonb)
  -- source: 'pair_rec_accept' | 'pair_rec_reject' | 'match_excluded' | ...

-- Audit
audit_log(id, ts, actor_user_id, action, entity_type, entity_id, before_jsonb, after_jsonb, ip)
```

This is a sketch — column types and indexes get refined when we write the migration. The shape carries from SQLite (Phase 0) to Postgres (Phase 1+) unchanged.

---

## 7. Phased roadmap

| Phase | Deliverable | Estimated effort | Exit criterion |
|---|---|---|---|
| **0. Local proof** | SQLite (model-agnostic schema) + manual parser for one VLTC file + OpenSkill ratings + CLI for top players + pair recommender (Hungarian algorithm). Run locally only. | 1–2 focused days | Rankings on real VLTC data look intuitively correct to a knowledgeable observer (Kurt). |
| **1. Data foundation** | Postgres schema + hand-written parsers for ~4 dominant VLTC template families + bulk-load all existing VLTC files + alias/merge CLI + champion rating engine + **first challenger model running in shadow** + player-merge HITL channel. No web UI yet. | 2–3 weeks part-time | All VLTC data ingested, deduplication done, two models producing leaderboards that can be compared by hand. |
| **2. Web app skeleton** | Next.js + Postgres + auth + public rankings + player profile w/ rating-history chart + admin player-merge UI + **multi-model dashboard (side-by-side leaderboards, disagreements, predictive scoreboard)** + **HITL channels: match exclusion, score correction** + audit log writes. Deployed to Proxmox via docker-compose. | 3–4 weeks | Site is publicly browsable; admin can merge players, exclude matches, and compare model leaderboards through the UI; audit trail exists. |
| **3. Agentic ingestion** | Upload UI for admins → Redis job → Python worker calls Claude API → matches land in DB immediately tagged with `ingestion_run_id` → quality report generated → admin reviews report after the fact and can re-process if needed (matches superseded; ratings recomputed). Original file kept in MinIO. **Adds informal-match upload HITL channel.** Dashboard widget surfaces unreviewed reports. | 3–4 weeks | An admin can drop a tournament file in and have it processed end-to-end; quality report is visible; re-process flow works idempotently. |
| **4. Pair recommender** | Roster input UI + chemistry-residual model + constraint-aware optimization (pairs across men/women × division A/B/C/D). **Adds pair-rec accept/reject HITL logging.** | 1–2 weeks | Captain can input team availability and get a justified pairing suggestion; choices are logged for chemistry-model training. |
| **5. Multi-club & polish** | Onboard a second club; cross-club player linking flow; per-club admin permission isolation. Manual rating-pin escape hatch only if a real need has emerged by now. | Ongoing | Second club's admin can use the system without seeing or affecting the first club's admin operations. |

**What ships first to real users:** end of Phase 2. Phase 3 follows but doesn't block public rankings being live.

---

## 8. Risks (called out honestly)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Agentic extraction accuracy is worse than 80% on messy real-world sheets | Medium | High — review burden becomes the bottleneck | Phase 3 includes a calibration step on 10 real files before declaring it production-ready; fall back to per-template parsers if needed |
| Player entity resolution produces silent duplicates → ratings split across two records | High if unguarded | Catastrophic for credibility | Aggressive fuzzy-match on insert; admin review queue for any new name with >0.7 similarity to existing; merging is a first-class operation |
| Pair chemistry signal is too sparse to be useful | Medium | Medium — recommender degrades to "pair the strongest" | Honest fallback: if pair has <N=5 matches together, residual=0; surface this to the user as "low data" |
| OpenSkill ratings don't match intuition on small datasets | Medium | High — kills user trust early | Phase 0 *exists* specifically to validate this before any infrastructure investment |
| Postgres on a single Proxmox host becomes a SPOF | Low (this domain) | Medium | Daily dumps + offsite backups; accept the tradeoff vs running HA Postgres for hobby-scale traffic |
| Self-hosted Caddy / TLS / domain setup has a misconfiguration that exposes admin endpoints | Medium | High | Network policy: admin routes require login + IP allowlist option; security review before public DNS goes live |
| Scope creep into singles, tournament management, or live scoring | High | Medium — slows the doubles core | Re-read §1 non-goals before adding any feature outside it |
| Auto-accept ingestion (§5.3.1) lands bad data that admin never reviews | Medium | High — silent corruption of public ratings | Dashboard widget for unreviewed reports; login banner for reports >N days unreviewed; optional email digest; quality report defaults to grouping low-confidence + anomalies at top |
| GDPR Article 17 takedown requests with no built-in opt-out workflow (per §5.9) | Low–medium | Medium — manual ad-hoc handling required | Build admin "remove player" action when first request arrives; publish privacy notice on the public site in Phase 2; if requests become routine, add per-player `visibility` flag |

---

## 9. Open questions

1. **Stack final answer**: Next.js + Python worker, or all-Python (Django/FastAPI)? Recommendation in §5.1 is Next.js, but pushback welcome.
2. ~~**Ingestion review granularity**~~ — **decided 2026-04-25**: auto-accept with post-hoc quality report and re-process workflow. See §5.3.1.
3. ~~**Public visibility**~~ — **decided 2026-04-25**: fully public, no opt-out workflow. See §5.9. Privacy notice + admin "remove player" action deferred until Phase 2 / first request.
4. ~~**Singles data**~~ — **decided 2026-04-25**: ignore singles entirely. See §1 non-goals.
5. ~~**Backfill cutoff**~~ — **decided 2026-04-25**: full backfill of all doubles tournaments 2017–2026. See §3 backfill scope.
6. ~~**Time decay on ratings**~~ — **decided 2026-04-25**: enabled via OpenSkill sigma drift (`tau` parameter); plus an "active in last N months" leaderboard filter. See §5.2 Time decay paragraph.
7. ~~**Domain & branding**~~ — **decided 2026-04-25**: public product name is **RallyRank**. Repo name stays descriptive (`wks-social-tennis-rankings-malta`). Domain availability + trademark + social-handle reservation is a Phase 2 follow-up.

---

## 10. What I'd change after one week of using it

Things I expect we'll learn and have to revisit:

- The pair-chemistry residual will probably be too noisy in v1 → may need to switch to a proper hierarchical model.
- The agentic extraction may struggle most on the team-tournament Day-N sheets (they're the most freeform). Hand-parsers may have to stay for those long-term.
- The "merge two players" UI will need to handle three- and four-way merges (someone has been split into multiple records over the years).
- We'll discover that some "pairs" in the data are typos and need a different fix than merging players.

These are knowable unknowns — flagged here so we don't pretend the v1 design is final.

### 10.1 Phase 0 retrospective (2026-04-26)

**Phase 0 closed with 32 of 32 doubles tournaments parsed (3,651 matches, 998 canonical players, 138 tests passing).** Below is what we learned doing the work, sorted by impact for Phase 1+.

#### What worked

- **Plan → Tasks → Execute, in that order.** PLAN.md captured decisions+rationale; TASKS.md kept the operational state; the build phase was fast because every task's *why* was already settled. Re-ordering this (e.g., starting code before plan) would've cost more than the planning time saved.
- **Multi-agent parallelism for parsers.** Three parser-implementer subagents ran concurrently in two waves (Wilson + mixed + team-tournament; then legacy-team + Elektra-2022 + TCK-2024). Each wrote spec + parser + tests + dispatch entry in ~10-15min wall-clock. Total: ~45min for 6 parsers. Sequential would've been ~3 hours.
- **TASKS.md "lock" pattern (commit + push to claim a task)** prevented file conflicts even with 3 agents touching `cli.py` dispatch. Substring-match-first-wins ordering guaranteed precedence.
- **Model-agnostic schema from day one (`model_name` discriminator).** When upset amplification was added late in the session, no schema migration was needed. Same for the eventual Modified Glicko-2 challenger (T-P1-009) — schema is ready.
- **Audit log + soft-delete via `merged_into_id`.** 188 player merges performed, 0 data lost. Every merge has an `audit_log` row with before/after JSON.
- **Conservative ranking convention (μ-3σ).** Kept new players (4 matches, high σ) from dominating the leaderboard with raw μ. Saved several "Sebastian Sanchez at #1!" embarrassments.
- **Agent definitions in `.claude/agents/`** — even though they don't auto-load mid-session, future sessions opened in this repo will have them ready. Contributors get them automatically.

#### What surprised us

- **Pervasive case-sensitivity / apostrophe-variance in the data.** Originally scoped as "Phase 1 fuzzy-match merge." Reality: 188 case-only + apostrophe-variant duplicates among 1,186 records (16%). Built a `merge-case-duplicates` CLI mid-Phase-0 to address it. Phase 1's fuzzy-match merge tool will need to handle name-without-apostrophe vs with ("Angele Pule" vs "Angele Pule'") and parser-quirk-name pollution ("(pro)" / "(dem)" notations stuck in names).
- **"Men A ≡ Men Div 1" tier mapping was a domain insight** Kurt provided after seeing initial output. Initial design treated team-rubber categories and division names as separate. Tier abstraction emerged late but was clean to retrofit because constants were keyed by name (we just added more keys with same values). Should have asked the domain expert this question earlier.
- **Single-tournament data was insufficient for evaluation.** Initial T-P0-009 with one tournament (SE 2025) showed Div 2 winners outranking Div 1. Filed T-P0-014 (bulk-load) accelerated from Phase 1 to make ranking accuracy testable. **Lesson:** validate with cross-population data, not single-tournament data.
- **OpenSkill *did* implement upset weighting natively** via the `S − E` mechanism, but the magnitude was modest. Kurt's "lose to worse should drop more" feedback was about *amplification*, not absence. Added explicit `upset_k_multiplier` (UPSET_ALPHA=1.0) to make it more reactive.
- **A Python default-args bug**: `def upset_k_multiplier(alpha=UPSET_ALPHA)` binds the default at function-definition time. Tests couldn't override the global. Switched to `alpha=None → look up at call time` pattern.
- **The Wilson "format" turned out to be team-tournament**, not division round-robin as initially assumed. Reused the team_tournament tier system seamlessly.
- **5 of 6 "deferred" files in the second batch parsed cleanly** (PKF / Tennis Trade 2023 / San Michel pre-2025 etc.) — they shared an older single-sheet "DAY" template. The 6th turned out to be the same San Michel format under a different filename. One agent → 5 files → 777 matches.
- **Backtick (`` ` ``) used as apostrophe** in some Maltese-club Excel exports. `Pule\`` meant `Pule'`. Caught only when re-running `merge-case-duplicates` revealed Duncan D'Alessandro split across apostrophe variants.

#### Tuning landed (final values for the Phase 0 baseline rating engine)

```
Per-tier starting μ:
  Men Tier 1 (A/Div 1)  33.0   Lad Tier 1   31.0
  Men Tier 2 (B/Div 2)  28.0   Lad Tier 2   26.0
  Men Tier 3 (C/Div 3)  23.0   Lad Tier 3   21.0
  Men Tier 4 (D/Div 4)  18.0   Lad Tier 4   16.0

Per-tier K (rating-update multiplier):
  Tier 1   1.00          Tier 3   0.70
  Tier 2   0.85          Tier 4   0.60

Per-tier μ ceiling / floor:
  Men T1   floor=28, no ceiling      Lad T1   floor=26, no ceiling
  Men T2   floor=23, ceiling=32      Lad T2   floor=21, ceiling=30
  Men T3   floor=18, ceiling=27      Lad T3   floor=16, ceiling=25
  Men T4   no floor,  ceiling=22     Lad T4   no floor,  ceiling=20

Score (universal games-won):  S = games_won / (games_won + opp_games_won)
Walkover handling:            S = 0.90 / 0.10  (not 1.0 / 0.0)
Game-volume K_volume:         total_games / 18, clamped [0.5, 1.5]; walkover = 0.5
Upset amplification:          K_upset = 1 + UPSET_ALPHA × |S − E|
                              UPSET_ALPHA = 1.0 (50% upset → 1.5×; total → 1.8×)
Sigma drift (inactivity):     σ' = sqrt(σ² + N × τ²); τ = 0.0833; period = 30 days
Champion model:               OpenSkill PlackettLuce, model_name = 'openskill_pl'
Sort key:                     μ − 3σ  (conservative Bayesian rating)
```

#### Parser quirks worth knowing for Phase 1

| Quirk | Where | Workaround |
|---|---|---|
| ALL CAPS player names | Older legacy files (PKF, San Michel 2023, Wilson 2017-2018) | `merge-case-duplicates` CLI (Phase 0); fuzzy match in Phase 1 |
| Backtick (`` ` ``) used for apostrophe | Some Maltese exports (Pule, D'Alessandro variants) | Added to `players._APOSTROPHE_TABLE` |
| Sub-tier suffixes (`LAD A1`, `LAD A 1`, `LAD A02`) | Legacy team-tournament files | `team_tournament_legacy.py` collapses to canonical `Lad A` |
| `(pro)` / `(dem)` substitute notations stuck in player names | Various team-tournament files | NOT handled in Phase 0; Phase 1 fuzzy-match merge cleanup needed |
| Different super-tiebreak rules across tournaments | Wilson, modern team-tournament, Elektra 2022 | Each parser handles per local convention; ~309 Wilson rubbers stored as `won=0` (unrecorded) |
| No per-match dates | Sports Experience 2025 | Tournament-year-Jan-1 placeholder; rating engine falls back to insertion order |
| Cross-tab matrix layout | Elektra 2022 only | Dedicated `elektra_2022.py` parser walks upper triangle |
| Walkover encoding variants (`W/O`, `W/0`, `WO`, `SCRATCHED`) | TCK Chosen 2024 | Tolerant matcher in `tck_chosen_2024.py` |
| Different apostrophe in same player name (no apostrophe vs with) | "Angele Pule" vs "Angele Pule'" | NOT handled; needs Phase 1 fuzzy match |
| Re-load creates duplicate `tournaments` row | All parsers | Tolerated for Phase 0 (rating engine filters by active matches); Phase 1 should dedupe on `source_files.sha256` |
| SE parser hardcodes `tournament.year=2025` | `sports_experience_2025.py` | SE 2024 file shows `year=2025` in DB; cosmetic; Phase 1 fix |

#### Phase 0 statistics

```
Span:           One extended session, 2026-04-25 → 2026-04-26
Commits:        ~30 to main
Lines of code:  ~5,000 Python (parsers + rating + cli + tests)
Lines of docs:  ~2,500 markdown (PLAN, TASKS, parser specs, READMEs)
Tests:          138 unit + integration, all passing
Subagents:      6 successful (3 explorer + 3 implementer pairs)
Player merges:  188 audited
Tournaments:    32 / ~32 doubles tournaments in dataset
Matches:        3,651
Players:        998 canonical (1,186 raw)
```

#### Tasks promoted from Phase 1 to Phase 0 during the work

- T-P1-014 → T-P0-014: bulk-load all VLTC tournaments (originally Phase 1)
- T-P1-008 partial: case+apostrophe merge tool (full fuzzy-match still Phase 1)
- T-P0-011, T-P0-012: division weights + game-volume K (originally Phase 1 enhancement)
- Upset amplification (UPSET_ALPHA): not in original plan; added late in Phase 0

#### What the next session should do

1. Run T-P0-009 acceptance one more time with the locked baseline (Kurt eyeballs the leaderboards)
2. Move directly to Phase 1: Postgres migration (T-P1-001) is the natural starting point
3. Modified Glicko-2 challenger (T-P1-009) is the next big-impact rating work — runs alongside OpenSkill PL via the model-agnostic schema
4. Player merge fuzzy-match tooling (T-P1-008) — much higher priority than originally scoped given how pervasive case/apostrophe variance turned out

**Phase 0 status: ✅ COMPLETE.**

---

## 11. Decisions still needed from Kurt before Phase 0 starts

- [x] Stack — **Next.js + TS + Python worker** (Option A, 2026-04-25)
- [x] Champion rating model — **OpenSkill (Plackett-Luce)** (2026-04-25). Challengers added in Phase 1+ per §5.7.
- [x] Schema **model-agnostic from day one** — `model_name` discriminator on rating tables; new tables for predictions, scoreboard, champion history, feedback (2026-04-25). See §5.7, §5.8, §6.
- [x] Phasing — **sequential Phase 0 → 1 → 2 → 3 → 4 → 5** (Option A, 2026-04-25)
- [x] Ingestion review — **auto-accept with post-hoc quality report + re-process workflow** (Option D variant, 2026-04-25). See §5.3.1.
- [x] Public visibility — **fully public, no opt-out** (2026-04-25). See §5.9.
- [x] Singles data — **out of scope** (Option A, 2026-04-25). See §1 non-goals.
- [x] Backfill — **full doubles 2017–2026** (Option A, 2026-04-25). See §3.
- [x] Time decay — **OpenSkill sigma drift + leaderboard activity filter** (Option A, 2026-04-25). See §5.2 Time decay.
- [x] Repo name — `wks-social-tennis-rankings-malta` (2026-04-25)
- [x] Public product name — **RallyRank** (2026-04-25)

**All blocking decisions resolved. Phase 0 can begin.**
