# Social Tennis — Doubles Ranking System: Plan

**Status:** Draft for review · **Owner:** Kurt Carabott · **Last updated:** 2026-04-25

This document captures the plan, the alternatives considered, and the tradeoffs of each major decision. It's intentionally argumentative — every recommendation is paired with the strongest counter-arguments so we can push back before writing code.

---

## 1. Problem & goals

Build a multi-club tennis doubles ranking system that:

1. **Ranks doubles players** continuously (UTR/WTN-style: each new match updates ratings).
2. **Recommends optimal pair combinations** when assembling team-tournament rosters — including modeling partner chemistry, not just summing individual skill.
3. **Ingests tournament results agentically** — club admins upload spreadsheets/PDFs and an LLM-driven pipeline extracts results into a normalized schema with admin review.

**Success looks like:** a self-hosted web app where (a) any visitor can browse rankings and player history, (b) club admins can drop new tournament files in and have them flow into the rating engine within minutes, and (c) team captains can input a roster and get back data-driven pairing suggestions.

**Non-goals (for now):**
- Singles ranking as a primary product (we may rate singles incidentally, but this is a doubles tool).
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

`_DATA_/VLTC/` — ~40 Excel files from Vittoriosa Lawn Tennis Club, 2017–2026.

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

**Recommendation: OpenSkill (Plackett-Luce).** Bayesian uncertainty matters here because most VLTC players will have <20 matches in the dataset — pretending we have high confidence in their rating would be dishonest. The team-native API removes a class of bugs in how we aggregate partner ratings.

**Score margin** is added as a "match weight" multiplier: a 6-0 6-0 win counts more than a 7-6 7-6 win. Specific weighting function is tunable in Phase 0.

**Pair chemistry** is a separate residual model: for each pair that has played together ≥N times, compute (actual win rate − model-predicted win rate). Use this residual as a bonus/penalty when the pair recommender considers that combination. For pairs with no shared history, residual = 0 (assume neutral chemistry).

### 5.3 Ingestion approach

| Option | Pros | Cons |
|---|---|---|
| **Agentic (Claude API + admin review)** *(recommended)* | Handles arbitrary new spreadsheet formats without writing parsers; future-proof against new clubs; admin review keeps a human in the loop on ambiguous matches | API costs (~$0.05–0.20 per file); accuracy 80–90% on first pass; needs robust review UI |
| Hand-written parsers per template | Deterministic; free to run; debuggable | Every new tournament format = new code; will eventually hit a layout we can't parse cleanly |
| Hybrid: try parser first, fall back to agent | Cheapest in steady state | Most complex to maintain; two failure modes |

**Recommendation: Agentic, with hand-written parsers used only in Phase 1 to bulk-load existing VLTC history.** Once the agent ingestion is built, retire the hand-written parsers — they're not worth maintaining alongside the agent.

**Open question:** vision (screenshot → Claude vision model) vs structured (XLSX → cells → Claude with text). Probably structured for XLSX, vision fallback for PDFs and image scans. Decide during Phase 3.

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
ingestion_runs(id, source_file_id, status, agent_version, started_at, completed_at, raw_extraction_jsonb)

tournaments(id, club_id, name, year, format, source_file_id)
  -- format: 'doubles_division' | 'doubles_team' | 'singles_*'

matches(id, tournament_id, played_on, match_type, division, round)
  -- match_type: 'doubles' (singles deferred)

match_sides(match_id, side, player1_id, player2_id, sets_won, games_won, won)
  -- two rows per match (side 'A' and 'B')

match_set_scores(match_id, set_number, side_a_games, side_b_games, was_tiebreak)

-- Ratings
ratings(player_id, mu, sigma, last_updated_at, n_matches)
rating_history(player_id, match_id, mu_after, sigma_after, computed_at)
pair_chemistry(player1_id, player2_id, residual, n_matches_together, last_updated_at)

-- Audit
audit_log(id, ts, actor_user_id, action, entity_type, entity_id, before_jsonb, after_jsonb, ip)
```

This is a sketch — column types and indexes get refined when we write the migration. The shape carries from SQLite (Phase 0) to Postgres (Phase 1+) unchanged.

---

## 7. Phased roadmap

| Phase | Deliverable | Estimated effort | Exit criterion |
|---|---|---|---|
| **0. Local proof** | SQLite + manual parser for one VLTC file + OpenSkill ratings + CLI showing top players + pair recommender (Hungarian algorithm). Run locally only. | 1–2 focused days | Rankings on real VLTC data look intuitively correct to a knowledgeable observer (Kurt). |
| **1. Data foundation** | Postgres schema + hand-written parsers for ~4 dominant VLTC template families + bulk-load all existing VLTC files + alias/merge CLI + rating engine producing leaderboards. Still no UI. | 2–3 weeks part-time | All VLTC data ingested, deduplication done, reproducible rankings exist. |
| **2. Web app skeleton** | Next.js + Postgres + auth + public rankings page + player profile w/ rating history chart + admin player-merge UI + audit log writes. Deployed to Proxmox via docker-compose. | 2–3 weeks | Site is publicly browsable; you can do a player merge through the UI; audit trail exists. |
| **3. Agentic ingestion** | Upload UI for admins → Redis job → Python worker calls Claude API → extracted matches go to a review screen → admin confirms → matches land in DB. Original file kept in MinIO. | 3–4 weeks | An admin can drop an unfamiliar tournament file in and have it processed end-to-end. |
| **4. Pair recommender** | Roster input UI + chemistry residual model + constraint-aware optimization (pairs across men/women × division A/B/C/D). | 1–2 weeks | Captain can input team availability and get a justified pairing suggestion. |
| **5. Multi-club** | Onboard a second club; cross-club player linking flow; per-club admin permission isolation. | Ongoing | Second club's admin can use the system without seeing or affecting the first club's admin operations. |

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

---

## 9. Open questions

1. **Stack final answer**: Next.js + Python worker, or all-Python (Django/FastAPI)? Recommendation in §5.1 is Next.js, but pushback welcome.
2. **Ingestion review granularity**: confirm every extracted match, or only those flagged low-confidence by the agent? Earlier conversation said "trust admins" — leaning toward "show all extractions on one screen with low-confidence rows highlighted; admin clicks Approve."
3. **Public visibility**: are all rankings public, or do players opt in? GDPR-adjacent — Malta is in the EU. Recommend: club controls visibility per club, default-public, with a per-player opt-out.
4. **Singles data**: some files are singles tournaments. Ignore them entirely, or store them too (without a rating for now)? Recommend: store everything we ingest, but don't compute singles ratings in v1.
5. **Backfill cutoff**: ingest all 40 historical files, or start from 2024 onward? Recommend: ingest everything — historical depth gives the rating model more signal even if older matches are weighted down by time decay.
6. **Time decay on ratings**: should a player's rating decay if they stop playing for a year? UTR does this. Recommend yes; tune in Phase 1.
7. **Domain & branding**: is there a chosen name for this product? Affects the Next.js project name and the eventual public URL.

---

## 10. What I'd change after one week of using it

Things I expect we'll learn and have to revisit:

- The pair-chemistry residual will probably be too noisy in v1 → may need to switch to a proper hierarchical model.
- The agentic extraction may struggle most on the team-tournament Day-N sheets (they're the most freeform). Hand-parsers may have to stay for those long-term.
- The "merge two players" UI will need to handle three- and four-way merges (someone has been split into multiple records over the years).
- We'll discover that some "pairs" in the data are typos and need a different fix than merging players.

These are knowable unknowns — flagged here so we don't pretend the v1 design is final.

---

## 11. Decisions still needed from Kurt before Phase 0 starts

- [ ] Confirm Next.js + Python worker (or argue for Django/all-Python)
- [ ] Confirm OpenSkill (Plackett-Luce) is OK as the starting rating model
- [ ] Confirm the phasing — specifically that internal tool (Phase 0–1) ships before web app (Phase 2)
- [ ] Pick an answer for each open question in §9 (or punt to later, but mark explicitly)
- [ ] Pick a project name (or defer until Phase 2)
