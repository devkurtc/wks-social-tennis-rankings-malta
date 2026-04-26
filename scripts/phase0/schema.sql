-- RallyRank — Phase 0 SQLite schema
-- See PLAN.md §6 for the canonical schema design. This file is the Phase 0
-- subset (model-agnostic from day one per PLAN.md §5.7). Phase 1 ports this
-- shape to Postgres and adds the tables noted as "skipped" at the bottom.
--
-- All scripts use this schema by calling db.init_db() — never raw sqlite3.
-- All connections must enable foreign keys (PRAGMA foreign_keys = ON).
--
-- Conventions:
--   * INTEGER PRIMARY KEY → ROWID, autoincrement-ish
--   * Dates stored as TEXT in ISO 8601 (YYYY-MM-DD or full timestamp);
--     SQLite has no native date type and ISO sorts lexically
--   * Booleans stored as INTEGER 0/1 (SQLite has no bool type)
--   * Columns ending in _jsonb hold JSON in TEXT (SQLite has no JSONB)
--   * CREATE TABLE IF NOT EXISTS everywhere — init_db() is idempotent

-- ─────────────────────────────────────────────────────────────────────────────
-- Identity
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS clubs (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    slug        TEXT    NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS players (
    id              INTEGER PRIMARY KEY,
    canonical_name  TEXT    NOT NULL UNIQUE,   -- after NFKC + apostrophe + whitespace normalization (T-P0-005)
    gender          TEXT    CHECK (gender IN ('M', 'F') OR gender IS NULL),
    dob_year        INTEGER,                   -- nullable
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    merged_into_id  INTEGER REFERENCES players(id)   -- non-null = this record was merged into another (Phase 1+)
);

CREATE TABLE IF NOT EXISTS player_aliases (
    id              INTEGER PRIMARY KEY,
    player_id       INTEGER NOT NULL REFERENCES players(id),
    raw_name        TEXT    NOT NULL,
    source_file_id  INTEGER REFERENCES source_files(id),  -- nullable: aliases may pre-date a file
    first_seen_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (player_id, raw_name)
);

CREATE INDEX IF NOT EXISTS idx_player_aliases_raw_name ON player_aliases (raw_name);

-- ─────────────────────────────────────────────────────────────────────────────
-- Tournaments and matches (with idempotent re-process semantics per §5.3.1)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS source_files (
    id                INTEGER PRIMARY KEY,
    club_id           INTEGER NOT NULL REFERENCES clubs(id),
    original_filename TEXT    NOT NULL,
    storage_key       TEXT,                              -- nullable in Phase 0 (no MinIO)
    sha256            TEXT    NOT NULL,
    uploaded_by       INTEGER,                           -- nullable in Phase 0 (no users table)
    uploaded_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id                    INTEGER PRIMARY KEY,
    source_file_id        INTEGER NOT NULL REFERENCES source_files(id),
    status                TEXT    NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'superseded')),
    agent_version         TEXT,
    started_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at          TEXT,
    raw_extraction_jsonb  TEXT,
    quality_report_jsonb  TEXT,
    reviewed_at           TEXT,
    reviewed_by_user_id   INTEGER,                       -- nullable in Phase 0
    supersedes_run_id     INTEGER REFERENCES ingestion_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source ON ingestion_runs (source_file_id);

CREATE TABLE IF NOT EXISTS tournaments (
    id              INTEGER PRIMARY KEY,
    club_id         INTEGER NOT NULL REFERENCES clubs(id),
    name            TEXT    NOT NULL,
    year            INTEGER NOT NULL,
    format          TEXT    NOT NULL CHECK (format IN ('doubles_division', 'doubles_team')),
    source_file_id  INTEGER REFERENCES source_files(id)
);

CREATE TABLE IF NOT EXISTS matches (
    id                    INTEGER PRIMARY KEY,
    tournament_id         INTEGER NOT NULL REFERENCES tournaments(id),
    played_on             TEXT    NOT NULL,                                    -- ISO 8601 date
    match_type            TEXT    NOT NULL DEFAULT 'doubles' CHECK (match_type IN ('doubles', 'singles')),
    division              TEXT,                                                -- e.g. 'Men Div 1'
    round                 TEXT,                                                -- nullable
    ingestion_run_id      INTEGER NOT NULL REFERENCES ingestion_runs(id),
    superseded_by_run_id  INTEGER REFERENCES ingestion_runs(id),               -- NULL = active match
    informal              INTEGER NOT NULL DEFAULT 0,                          -- bool: HITL informal upload (Phase 3+)
    walkover              INTEGER NOT NULL DEFAULT 0                           -- bool: triggers S=0.90/0.10 in rating (PLAN.md §5.2)
);

-- Active-match index per PLAN.md §5.3.1
CREATE INDEX IF NOT EXISTS idx_matches_active
    ON matches (tournament_id, played_on)
    WHERE superseded_by_run_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_matches_run ON matches (ingestion_run_id);

CREATE TABLE IF NOT EXISTS match_sides (
    match_id     INTEGER NOT NULL REFERENCES matches(id),
    side         TEXT    NOT NULL CHECK (side IN ('A', 'B')),
    player1_id   INTEGER NOT NULL REFERENCES players(id),
    player2_id   INTEGER REFERENCES players(id),                               -- nullable for singles
    sets_won     INTEGER NOT NULL DEFAULT 0,
    games_won    INTEGER NOT NULL DEFAULT 0,
    won          INTEGER NOT NULL DEFAULT 0,                                   -- bool
    PRIMARY KEY (match_id, side)
);

CREATE INDEX IF NOT EXISTS idx_match_sides_player1 ON match_sides (player1_id);
CREATE INDEX IF NOT EXISTS idx_match_sides_player2 ON match_sides (player2_id);

CREATE TABLE IF NOT EXISTS match_set_scores (
    match_id       INTEGER NOT NULL REFERENCES matches(id),
    set_number     INTEGER NOT NULL,
    side_a_games   INTEGER NOT NULL,
    side_b_games   INTEGER NOT NULL,
    was_tiebreak   INTEGER NOT NULL DEFAULT 0,                                 -- bool: TRUE for 10-pt match tiebreak
    PRIMARY KEY (match_id, set_number)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Ratings (model-agnostic from day one per §5.7)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ratings (
    player_id        INTEGER NOT NULL REFERENCES players(id),
    model_name       TEXT    NOT NULL,                                         -- e.g. 'openskill_pl' (Phase 0 champion)
    mu               REAL    NOT NULL,
    sigma            REAL    NOT NULL,
    last_updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    n_matches        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, model_name)
);

CREATE TABLE IF NOT EXISTS rating_history (
    id           INTEGER PRIMARY KEY,
    player_id    INTEGER NOT NULL REFERENCES players(id),
    model_name   TEXT    NOT NULL,
    match_id     INTEGER NOT NULL REFERENCES matches(id),
    mu_after     REAL    NOT NULL,
    sigma_after  REAL    NOT NULL,
    computed_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rating_history_player_model
    ON rating_history (player_id, model_name, computed_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- Captain-assigned team-tournament classifications (v2)
-- ─────────────────────────────────────────────────────────────────────────────
-- Each row: a captain assigned a player to slot X-N (e.g. 'A1', 'B3', 'C2',
-- 'D1') in tournament T. Multiple players share the same class label per
-- tournament (one per team). A player accumulates one row per team-tournament
-- they participated in; the most-recent assignment is their CURRENT class.
--
-- For tournaments without team assignment (division round-robin), no rows
-- here — current class is derived from primary division as a fallback.

CREATE TABLE IF NOT EXISTS player_team_assignments (
    tournament_id   INTEGER NOT NULL REFERENCES tournaments(id),
    player_id       INTEGER NOT NULL REFERENCES players(id),
    team_letter     TEXT,                       -- 'A' .. 'F' typically
    captain_name    TEXT,                       -- as recorded in source
    class_label     TEXT NOT NULL,              -- 'A1', 'A2', ..., 'D3'
    tier_letter     TEXT NOT NULL,              -- 'A', 'B', 'C', 'D' (extracted from class_label)
    slot_number     INTEGER NOT NULL,           -- 1, 2, 3, ... (extracted)
    gender          TEXT CHECK (gender IN ('M', 'F') OR gender IS NULL),
    PRIMARY KEY (tournament_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_pta_player ON player_team_assignments (player_id);
CREATE INDEX IF NOT EXISTS idx_pta_tier ON player_team_assignments (tier_letter, slot_number);

-- ─────────────────────────────────────────────────────────────────────────────
-- Audit (semantic actions per §5.5)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY,
    ts              TEXT    NOT NULL DEFAULT (datetime('now')),
    actor_user_id   INTEGER,                                                   -- nullable in Phase 0 (CLI)
    action          TEXT    NOT NULL,                                          -- e.g. 'ingestion.completed', 'player.merged'
    entity_type     TEXT    NOT NULL,
    entity_id       INTEGER,
    before_jsonb    TEXT,
    after_jsonb     TEXT,
    ip              TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_ts     ON audit_log (ts);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log (action);

-- ─────────────────────────────────────────────────────────────────────────────
-- Tables intentionally SKIPPED in Phase 0 (added in later phases)
-- ─────────────────────────────────────────────────────────────────────────────
-- Each is documented here so the gap is visible from this file alone.
--
--   model_predictions       — Phase 1+: pre-match P(side A wins) per model;
--                             feeds the model_scoreboard for champion promotion.
--   model_scoreboard        — Phase 1+: rolling Brier / log-loss per model.
--   champion_history        — Phase 1+: which model was champion when, and why.
--   pair_chemistry          — Phase 4: residual (actual − predicted) per pair;
--                             Phase 0 uses pure additive partner-strength.
--   model_feedback          — Phase 4+: pair-rec accept/reject signals etc.
--   player_club_memberships — Phase 5: many-to-many player↔club; Phase 0 has
--                             one club so unnecessary.
--   users / user_club_roles — Phase 2: only needed when web app + auth land.
-- ─────────────────────────────────────────────────────────────────────────────
