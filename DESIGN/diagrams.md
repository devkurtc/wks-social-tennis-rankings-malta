# Diagrams — visual atlas

Purpose: a single visual reference for the whole system. Read non-linearly
— jump to whichever diagram you need.

This file complements `architecture.md` (which carries the ADR-scoped
container + deployment diagrams). Anything *system-shaped* lives here:
domain model, user journeys, lifecycles, security zones, failure modes,
chatbot internals, and the future native-app slot.

Each diagram is tagged with one of three confidence levels:

- **locked** — based on accepted ADR or schema already in `scripts/phase0/schema.sql`
- **proposed** — based on proposed (not yet accepted) ADR; will firm up when accepted
- **tentative** — depends on a not-yet-drafted ADR (typically ADR-002 visibility, ADR-009 auth, ADR-021 caching); shown as best-current-thinking, expected to change

## Table of contents

1. [Domain model (ERD)](#1-domain-model-erd) — locked
2. [Ingestion run lifecycle](#2-ingestion-run-lifecycle) — locked
3. [Player lifecycle (with merges)](#3-player-lifecycle-with-merges) — locked
4. [Match → rating flow](#4-match--rating-flow) — locked
5. [User personas + permissions sketch](#5-user-personas--permissions-sketch) — tentative
6. [Webapp route map](#6-webapp-route-map) — tentative
7. [API resource map](#7-api-resource-map) — tentative
8. [Chatbot conversation internals](#8-chatbot-conversation-internals) — proposed
9. [Ingestion pipeline (Phase 3)](#9-ingestion-pipeline-phase-3) — proposed
10. [Auth + token flow](#10-auth--token-flow) — tentative
11. [Trust zones + security boundaries](#11-trust-zones--security-boundaries) — locked
12. [Cache + invalidation flow](#12-cache--invalidation-flow) — tentative
13. [Failure-mode handling](#13-failure-mode-handling) — proposed
14. [Native app slot (future)](#14-native-app-slot-future) — proposed

---

## 1. Domain model (ERD)

**Status: locked** — taken from `scripts/phase0/schema.sql`, with the
Phase 1+ tables called out separately.

```mermaid
erDiagram
    CLUBS ||--o{ PLAYERS_M : has
    CLUBS ||--o{ TOURNAMENTS : hosts
    CLUBS ||--o{ SOURCE_FILES : owns

    PLAYERS ||--o{ PLAYER_ALIASES : "known as"
    PLAYERS ||--o{ MATCH_SIDES : "plays in"
    PLAYERS ||--o{ RATINGS : has
    PLAYERS ||--o{ RATING_HISTORY : "history of"
    PLAYERS ||--o{ PLAYER_TEAM_ASSIGNMENTS : "assigned by captain"
    PLAYERS ||--o| PLAYERS : "merged into"

    SOURCE_FILES ||--|{ INGESTION_RUNS : "processed by"
    INGESTION_RUNS ||--o{ MATCHES : produces
    INGESTION_RUNS ||--o| INGESTION_RUNS : supersedes

    TOURNAMENTS ||--|{ MATCHES : contains
    TOURNAMENTS ||--o{ PLAYER_TEAM_ASSIGNMENTS : "team rosters"

    MATCHES ||--|{ MATCH_SIDES : "side A and B"
    MATCHES ||--o{ MATCH_SET_SCORES : "set-by-set"
    MATCHES ||--o{ RATING_HISTORY : "rating Δ from"

    PLAYERS {
        int id PK
        string canonical_name UK
        string gender
        int dob_year
        int merged_into_id FK
    }

    MATCHES {
        int id PK
        int tournament_id FK
        date played_on
        string match_type
        string division
        int ingestion_run_id FK
        int superseded_by_run_id FK
        bool informal
        bool walkover
    }

    MATCH_SIDES {
        int match_id PK,FK
        string side PK
        int player1_id FK
        int player2_id FK
        int sets_won
        int games_won
        bool won
    }

    RATINGS {
        int player_id PK,FK
        string model_name PK
        float mu
        float sigma
        int n_matches
    }

    PLAYERS_M {
        note "(many-to-many in Phase 5: player_club_memberships table)"
    }
```

**Reading the diagram:**

- `PLAYERS ||--o| PLAYERS` (self-reference) is the merge link — when two
  records are deduped, one keeps `merged_into_id = NULL`, the other points
  to it.
- `INGESTION_RUNS ||--o| INGESTION_RUNS` is the supersede link — re-processing
  a file creates a new run that supersedes the previous one (PLAN.md §5.3.1).
- The `RATINGS` PK is `(player_id, model_name)` — the model-agnostic
  design from PLAN.md §5.7. Every rating-aware query *must* specify a model.
- Tables not yet present (Phase 1+): `users`, `user_club_roles`,
  `model_predictions`, `model_scoreboard`, `champion_history`, `pair_chemistry`,
  `model_feedback`, `player_club_memberships`. Documented in `schema.sql`.

---

## 2. Ingestion run lifecycle

**Status: locked** — defined in PLAN.md §5.3.1 and `schema.sql`.

```mermaid
stateDiagram-v2
    [*] --> running : POST /admin/upload<br/>or scheduled retry

    running --> completed : extraction succeeded<br/>matches inserted
    running --> failed : extraction errored<br/>no matches inserted

    completed --> superseded : admin clicks reprocess<br/>or new run for same source_file
    failed --> [*] : no further state

    completed --> [*] : reviewed by admin<br/>(reviewed_at set)

    note right of running
        Matches are NOT inserted until
        extraction completes successfully.
        No "pending" intermediate state in DB.
    end note

    note right of superseded
        Old matches kept; flagged
        superseded_by_run_id = new_run.id.
        Active reads filter IS NULL.
    end note
```

**Why this matters:**

- "Reviewed" is a flag, not a state — admin review is post-hoc per
  PLAN.md §5.3.1.
- Re-processing is *idempotent* by design — every read query filters
  `WHERE superseded_by_run_id IS NULL`, so old runs become invisible
  without being deleted.
- `failed` is terminal — failed runs do not leave partial data behind.

---

## 3. Player lifecycle (with merges)

**Status: locked** — schema-driven. Merge flow specified in PLAN.md §5.4.

```mermaid
stateDiagram-v2
    [*] --> proposed : alias seen in incoming file<br/>NEW name, no fuzzy match

    [*] --> existing : alias seen in incoming file<br/>fuzzy match >= threshold<br/>+ admin confirms

    proposed --> active : admin reviews,<br/>creates new player record

    active --> active : new aliases attached<br/>(common case, no state change)

    active --> merged : admin merges duplicate into another player<br/>merged_into_id set

    merged --> [*] : record retained for audit<br/>but excluded from reads

    note right of proposed
        Phase 3+ behavior. Phase 0 / 1
        creates players directly without
        a review queue.
    end note

    note right of merged
        URL stability concern (ADR-020):
        bookmarked URLs to merged player
        must 301 to canonical record.
    end note
```

---

## 4. Match → rating flow

**Status: locked** — implemented in `scripts/phase0/rating.py`.

How a single match's outcome propagates into rating updates:

```mermaid
flowchart TB
    M[New match inserted<br/>with ingestion_run_id]

    M --> RECOMPUTE{Recompute strategy}

    RECOMPUTE -->|incremental<br/>Phase 0 default| INCR[Apply OpenSkill rate update<br/>to 4 player records<br/>using current μ,σ]

    RECOMPUTE -->|full rebuild<br/>after supersede| FULL[TRUNCATE rating_history<br/>+ ratings<br/>Replay all active matches<br/>chronologically]

    INCR --> COMPUTE[For each player:<br/>μ_new, σ_new = openskill.rate]
    FULL --> COMPUTE

    COMPUTE --> ADJUSTERS[Apply adjusters:<br/>• Division K-multiplier<br/>• Volume K-multiplier<br/>• Upset amplification<br/>• Partner weighting]

    ADJUSTERS --> WRITE[(Write to ratings table<br/>+ append rating_history row<br/>per player per match)]

    WRITE --> CACHE[Publish 'ratings_updated'<br/>on Redis]

    CACHE --> INVAL[Invalidate cached<br/>leaderboard + profile pages]

    style M fill:#e3f2fd
    style WRITE fill:#e8f5e9
    style CACHE fill:#fff3e0
```

**Notes on the math** (full detail in `rating.py`):

- Phase 0 uses incremental updates for new matches; full rebuilds happen
  on supersede or model parameter changes.
- "Adjusters" are post-OpenSkill multipliers that encode domain
  knowledge (a 6-0 win in Div 4 should not move ratings the same as
  a 6-0 win in Div 1).
- The model-agnostic design means `compute()` can dispatch to multiple
  rating models in one pass (PLAN.md §5.7 champion/challenger).

---

## 5. User personas + permissions sketch

**Status: tentative** — depends on ADR-002 (consent) and ADR-003
(visibility matrix). Diagram shows current best-thinking; will be made
authoritative once those ADRs are accepted.

```mermaid
flowchart LR
    subgraph personas[Personas]
        ANON[Anonymous visitor<br/>no account]
        MEM[Club member<br/>verified email]
        CAP[Captain<br/>elected per tournament]
        ADM[Admin<br/>club committee or system owner]
    end

    subgraph capabilities[Capabilities]
        C1[View public leaderboard]
        C2[View public player profile<br/>names + ratings + recent matches]
        C3[Chat with bot<br/>rate-limited]
        C4[View detailed stats<br/>partners, opponents, trajectory]
        C5[Submit informal match<br/>HITL channel]
        C6[Edit team selection<br/>for own captaincy]
        C7[Upload tournament file]
        C8[Review ingestion quality reports]
        C9[Trigger reprocess]
        C10[Merge player records]
        C11[View audit log]
    end

    ANON --> C1
    ANON --> C2

    MEM --> C1
    MEM --> C2
    MEM --> C3
    MEM --> C4
    MEM --> C5

    CAP --> C1
    CAP --> C2
    CAP --> C3
    CAP --> C4
    CAP --> C5
    CAP --> C6

    ADM --> C1
    ADM --> C2
    ADM --> C3
    ADM --> C4
    ADM --> C5
    ADM --> C7
    ADM --> C8
    ADM --> C9
    ADM --> C10
    ADM --> C11
```

**Open questions** (to be resolved in ADR-002 / ADR-003):

- Are `C1` and `C2` *truly* anonymous, or behind a soft-gate (one-time
  email verification)?
- Does `C2` show full names or initials by default? Per-player override
  via ADR-004?
- Is `C3` member-only (recommended for cost control) or anonymous with
  hard rate-limit?

---

## 6. Webapp route map

**Status: tentative** — page list inferred from PLAN.md §1 and
the report types you described in our first conversation. Final shape
depends on ADR-003 (visibility) and ADR-020 (URL strategy).

```mermaid
flowchart TB
    ROOT["/"]
    ROOT --> LB["/leaderboard"]
    ROOT --> PLAYERS["/players"]
    ROOT --> TOURNAMENTS["/tournaments"]
    ROOT --> CHAT["/chat<br/>member-only"]
    ROOT --> ABOUT["/about<br/>how this works"]
    ROOT --> LOGIN["/login"]

    LB --> LB_FILTERED["/leaderboard?gender=&tier="]

    PLAYERS --> PSEARCH["/players?q=kurt"]
    PLAYERS --> PROFILE["/players/:slug"]
    PROFILE --> PMATCHES["/players/:slug/matches"]
    PROFILE --> PPARTNERS["/players/:slug/partners"]
    PROFILE --> POPPS["/players/:slug/opponents"]
    PROFILE --> PTRAJ["/players/:slug/trajectory"]

    PROFILE -.->|compare link| COMPARE["/compare?p1=&p2="]

    TOURNAMENTS --> TLIST["/tournaments?year="]
    TOURNAMENTS --> TDETAIL["/tournaments/:slug"]
    TDETAIL --> TBRACKET["/tournaments/:slug/divisions"]

    subgraph admin[Admin only]
        ADM_HOME["/admin"]
        ADM_HOME --> ADM_UP["/admin/upload"]
        ADM_HOME --> ADM_RUNS["/admin/runs"]
        ADM_RUNS --> ADM_RUN_DETAIL["/admin/runs/:id<br/>quality report"]
        ADM_HOME --> ADM_PLAYERS["/admin/players<br/>merge UI"]
        ADM_HOME --> ADM_AUDIT["/admin/audit"]
    end

    ROOT -.-> ADM_HOME

    style ADM_HOME fill:#ffebee
    style CHAT fill:#fff3e0
```

**Convention:** all `/admin/*` routes require role `admin` and are
behind an additional CF Access gate (per ADR-014's "future hardening").

---

## 7. API resource map

**Status: tentative** — locked by ADR-012 (OpenAPI codegen) once the
spec is drafted. Resource shape derives from the report types we
discussed (lists, profiles, comparison, chat).

```mermaid
flowchart LR
    subgraph public[Public read]
        E1[GET /api/v1/leaderboard]
        E2[GET /api/v1/players]
        E3[GET /api/v1/players/:id]
        E4[GET /api/v1/players/:id/matches]
        E5[GET /api/v1/players/:id/partners]
        E6[GET /api/v1/players/:id/opponents]
        E7[GET /api/v1/players/:id/trajectory]
        E8[GET /api/v1/compare]
        E9[GET /api/v1/tournaments]
        E10[GET /api/v1/tournaments/:id]
        E11[GET /api/v1/insights/upsets]
    end

    subgraph member[Member auth]
        E12[POST /api/v1/chat/messages<br/>SSE stream]
        E13[GET /api/v1/chat/conversations]
        E14[POST /api/v1/players/me/informal-match]
    end

    subgraph captain[Captain auth]
        E15[PUT /api/v1/tournaments/:id/team-assignments]
    end

    subgraph admin[Admin auth]
        E16[POST /api/v1/admin/upload]
        E17[GET /api/v1/admin/runs]
        E18[GET /api/v1/admin/runs/:id]
        E19[POST /api/v1/admin/runs/:id/reprocess]
        E20[POST /api/v1/admin/players/merge]
        E21[GET /api/v1/admin/audit]
    end

    subgraph realtime[Realtime]
        E22[WS /api/v1/ws/leaderboard<br/>live tournament tick]
    end

    style public fill:#e3f2fd
    style member fill:#fff3e0
    style captain fill:#fff8e1
    style admin fill:#ffebee
    style realtime fill:#f3e5f5
```

**Versioning:** `/api/v1/` from day 1 per ADR-017 (when drafted). Breaking
changes ship at `/api/v2/` with documented deprecation window for v1.

---

## 8. Chatbot conversation internals

**Status: proposed** — based on the LLM strategy in `research/2026-04-26-llm-options.md`.

End-to-end flow for a single user query that requires a tool call:

```mermaid
sequenceDiagram
    autonumber
    participant U as Member browser
    participant API as api (FastAPI)
    participant Cost as Cost-cap middleware
    participant LLM as LLMProvider<br/>(wraps Anthropic SDK)
    participant CL as Anthropic Sonnet 4.6
    participant DB as Postgres<br/>(via internal tools)
    participant SSE as SSE response

    U->>API: POST /api/v1/chat/messages<br/>"Who has Kurt played most often?"
    API->>Cost: check user daily budget<br/>+ monthly ceiling
    Cost-->>API: ok (under cap)

    API->>LLM: stream(messages, tools=[search_players,<br/>get_opponents, predict_match, ...])
    LLM->>CL: messages.stream w/ system prompt + tools<br/>(system prompt CACHED)

    CL-->>LLM: tool_use: search_players(q="kurt")
    LLM-->>API: tool_call event
    API->>DB: SELECT FROM players WHERE name LIKE '%kurt%'
    DB-->>API: candidates
    API->>LLM: tool_result
    LLM->>CL: continue with tool result

    CL-->>LLM: tool_use: get_opponents(player_id=42)
    LLM-->>API: tool_call event
    API->>DB: SELECT FROM v_player_opponents WHERE player_id=42
    DB-->>API: opponent stats
    API->>LLM: tool_result
    LLM->>CL: continue

    CL-->>LLM: token stream<br/>"Kurt's most frequent opponent..."<br/>+ markdown table
    LLM-->>API: stream chunks
    API-->>SSE: SSE events (tokens)
    SSE-->>U: streamed answer

    API->>DB: INSERT chat_messages (token usage,<br/>cost, conversation_id)

    note over CL: System prompt + tool defs<br/>are cached → ~$0.30/M not $3/M<br/>after first query in session
```

**Key design points:**

- All tool functions are *internal* — they run inside the API process
  using direct Python calls, no extra HTTP hops (the win for ADR-008
  Python choice).
- Cost-cap check happens *before* the LLM call, not after — prevents
  runaway budget overruns.
- Token usage logged per message for per-user budget tracking and
  monthly cost forecasting.
- System prompt + tool definitions are written *once* and cached for
  the session — see `research/2026-04-26-llm-options.md` for the 4–5×
  cost impact this has.

---

## 9. Ingestion pipeline (Phase 3)

**Status: proposed** — extends the simpler sequence in `architecture.md`.
Locked by PLAN.md §5.3 + §5.3.1; details refined here.

```mermaid
flowchart TB
    UPLOAD[Admin uploads file<br/>POST /admin/upload]

    UPLOAD --> STORE[Store in MinIO<br/>compute SHA-256]
    STORE --> DEDUP{Same SHA seen<br/>before?}

    DEDUP -->|yes| WARN[Warn admin:<br/>'Identical file already processed.<br/>Reprocess explicitly?']
    DEDUP -->|no| INGEST_RUN[INSERT ingestion_runs<br/>status=running]

    INGEST_RUN --> ENQUEUE[Enqueue Redis job]
    ENQUEUE --> WORKER[ingestion worker picks up]

    WORKER --> TEMPLATE{Detect template}

    TEMPLATE -->|known template| PARSER[Use specific parser<br/>e.g. wilson, mixed_doubles]
    TEMPLATE -->|unknown / messy| AGENT[Spawn Claude agent<br/>with tools: read_cells,<br/>propose_match, normalize_player,<br/>flag_anomaly]

    PARSER --> EXTRACT[Extract matches + aliases]
    AGENT --> EXTRACT

    EXTRACT --> NORMALIZE[Normalize player names<br/>NFKC + apostrophes + whitespace<br/>Resolve aliases vs existing players<br/>Fuzzy match >= 0.7 → flag for review]

    NORMALIZE --> INSERT[INSERT matches<br/>match_sides<br/>match_set_scores<br/>tagged with ingestion_run_id]

    INSERT --> QUALITY[Generate quality report:<br/>• Low-confidence rows<br/>• Anomalies<br/>• New aliases<br/>• Match counts vs expected]

    QUALITY --> COMPLETE[UPDATE ingestion_runs<br/>status=completed<br/>quality_report_jsonb=...]

    COMPLETE --> RECOMPUTE[Enqueue rating recompute job]
    COMPLETE --> NOTIFY[Dashboard widget:<br/>'1 new ingestion report unreviewed']

    RECOMPUTE --> WORKER2[worker service picks up]
    WORKER2 --> RATING[Apply rating updates<br/>see diagram 4]
    RATING --> INVAL[Publish 'ratings_updated'<br/>→ cache invalidate]

    WORKER -.->|on error| FAILED[UPDATE ingestion_runs<br/>status=failed<br/>error captured in quality_report_jsonb]

    style AGENT fill:#fff3e0
    style QUALITY fill:#fff8e1
    style FAILED fill:#ffebee
    style NOTIFY fill:#e8f5e9
```

**Notes:**

- Template detection is the optimization that lets cheap parsers handle
  the easy 80% of files; agentic extraction handles the messy 20% (per
  PLAN.md §5.3 hybrid approach).
- The agent has a small, allowlisted toolset — it can *read* cells and
  *propose* matches but cannot directly write to the DB; the orchestrating
  worker validates and writes.
- Quality report is *always* generated, even on success — not just on
  error. This is the surface the admin reviews.

---

## 10. Auth + token flow

**Status: tentative** — depends on ADR-009 (auth strategy). Diagram shows
expected JWT-bearer flow with refresh tokens, web + future native parity.

```mermaid
sequenceDiagram
    autonumber
    participant U as Browser / Native client
    participant API as api (FastAPI)
    participant DB as Postgres
    participant EMAIL as Email provider

    note over U,EMAIL: Magic-link login (passwordless)

    U->>API: POST /api/v1/auth/login<br/>{email}
    API->>DB: lookup or create user
    API->>EMAIL: send magic-link with one-time token
    EMAIL-->>U: email with link

    U->>API: GET /api/v1/auth/verify?token=...
    API->>DB: validate one-time token<br/>(single-use, 15min TTL)
    API-->>U: 200 + access JWT (1h) + refresh JWT (30d)<br/>(web: HttpOnly cookie + JSON; native: JSON only)

    note over U,API: Subsequent authenticated requests

    U->>API: GET /api/v1/players/me/...<br/>Authorization: Bearer <access>
    API->>API: validate JWT signature + expiry + role claims
    API-->>U: 200 + data

    note over U,API: Refresh flow

    U->>API: POST /api/v1/auth/refresh<br/>{refresh_token}
    API->>DB: validate refresh token (rotation check)
    API->>DB: invalidate old refresh, issue new
    API-->>U: 200 + new access JWT + new refresh JWT
```

**Why this shape:**

- **Bearer tokens (not session cookies)** — the only auth model that works
  identically for web and future native clients (ADR-007 + ADR-009).
- **Magic-link login (no password)** — fewer attack surfaces, no password
  reset flow, club members already have verified emails. Tradeoff:
  email deliverability becomes critical infra.
- **Refresh-token rotation** — every refresh issues a new refresh token
  and invalidates the old one. Detects token theft (if both old + new
  are used, that's a breach signal).

---

## 11. Trust zones + security boundaries

**Status: locked** — derived from ADR-014 (Cloudflare Tunnel ingress).

```mermaid
flowchart LR
    subgraph internet[Internet — hostile]
        ATTACKER[Random attacker]
        BOT[Scraper bot]
        USER[Legitimate user]
    end

    subgraph cf[Cloudflare edge — semi-trusted]
        WAF[WAF + rate limit]
        CACHE[Edge cache]
        TUNNEL[Tunnel endpoint]
    end

    subgraph host[Host — trusted]
        subgraph dnet[Docker network — trusted]
            CFD[cloudflared]
            WEB[webapp]
            API[api]
            WORKER[worker]
            INGEST[ingestion]

            subgraph dataz[Data tier — most trusted]
                PG[(Postgres)]
                REDIS[(Redis)]
                MINIO[(MinIO)]
            end
        end
    end

    EXT[Anthropic API — trusted endpoint<br/>data leaves system]

    ATTACKER --> WAF
    BOT --> WAF
    USER --> WAF

    WAF --> CACHE
    CACHE --> TUNNEL
    TUNNEL <-.->|outbound only| CFD

    CFD --> WEB
    CFD --> API

    WEB --> API
    API --> PG
    API --> REDIS
    API --> EXT

    WORKER --> PG
    WORKER --> REDIS

    INGEST --> PG
    INGEST --> REDIS
    INGEST --> MINIO
    INGEST --> EXT

    style ATTACKER fill:#ffcdd2
    style BOT fill:#ffe0b2
    style WAF fill:#fff3e0
    style CACHE fill:#fff3e0
    style TUNNEL fill:#fff3e0
    style PG fill:#c8e6c9
    style REDIS fill:#c8e6c9
    style MINIO fill:#c8e6c9
    style EXT fill:#e1bee7
```

**Trust gradient:**

| Zone | Trust | Notes |
|---|---|---|
| Internet | None — adversarial | Assume every request is hostile |
| Cloudflare edge | Semi — vendor-trusted | WAF + rate-limit applied here |
| Host (LXC / VPS) | High — physically controlled | OS hardened, ssh key only |
| Docker network | High — internal | TLS not required for inter-service |
| Data tier | Highest | Only application services connect; no human shells (audited if needed) |
| Anthropic API | Trusted endpoint | But: data leaves the system; per-message PII review applies |

**Critical property:** the host has **zero inbound public ports**.
All traffic enters via outbound CF Tunnel (cloudflared connects out).

---

## 12. Cache + invalidation flow

**Status: tentative** — locked by ADR-021 (caching strategy) when drafted.
Diagram shows the expected pattern: ISR + edge cache + pub/sub invalidation.

```mermaid
flowchart TB
    subgraph reads[Read path — cache-friendly]
        USER[User]
        USER --> CF[Cloudflare edge cache<br/>TTL 5min]
        CF -->|miss| WEB[webapp Next.js<br/>ISR cache 60s]
        WEB -->|miss| API[api endpoint]
        API --> PG[(Postgres)]
    end

    subgraph mutations[Mutation path — invalidates]
        ADMIN[Admin reprocess<br/>or new ingestion]
        ADMIN --> WORKER[worker recomputes ratings]
        WORKER --> PUBSUB[Redis PUBLISH<br/>'ratings_updated']
        PUBSUB --> INVAL_API[api INVALIDATE<br/>internal cache]
        PUBSUB --> INVAL_WEB[webapp on-demand<br/>revalidate ISR pages]
        PUBSUB --> INVAL_CF[Trigger CF cache purge<br/>via API]
    end

    style PG fill:#e8f5e9
    style PUBSUB fill:#fff3e0
    style INVAL_CF fill:#ffe0b2
    style INVAL_WEB fill:#ffe0b2
    style INVAL_API fill:#ffe0b2
```

**Cache TTL strategy (proposed):**

| Surface | TTL | Invalidated on |
|---|---|---|
| CF edge cache | 5 min | `ratings_updated` event → API purge |
| Webapp ISR (leaderboard) | 60s | `ratings_updated` → on-demand revalidate |
| Webapp ISR (player profile) | 5 min | `ratings_updated` for that player only |
| API in-memory cache | per-request | n/a (request-scoped only in v1) |

---

## 13. Failure-mode handling

**Status: proposed** — derived from "great from day 1" framing. Final
behavior locked in ADR-016 (quality bar) and per-feature ADRs.

```mermaid
flowchart LR
    subgraph normal[Normal operation]
        N1[All services healthy]
    end

    subgraph degraded[Degraded modes]
        D1[Anthropic API down<br/>or rate-limited]
        D2[Postgres down<br/>or read-only]
        D3[Redis down]
        D4[Worker job stuck]
        D5[Bad ingestion data]
        D6[CF Tunnel down]
    end

    subgraph responses[System response]
        R1[Chat returns 'service degraded — try later'<br/>+ Sentry alert]
        R2[Read-only mode: serve stale CF cache<br/>+ admin alert<br/>+ login disabled]
        R3[Job queue paused<br/>requests buffered<br/>+ admin alert]
        R4[Stale-job watchdog<br/>marks failed at 30min<br/>+ admin retry UI]
        R5[Quality report flags issues<br/>+ admin reviews + reprocess option]
        R6[Site offline<br/>healthcheck.io page-out<br/>+ user-visible status page]
    end

    D1 --> R1
    D2 --> R2
    D3 --> R3
    D4 --> R4
    D5 --> R5
    D6 --> R6

    style normal fill:#e8f5e9
    style degraded fill:#fff8e1
    style responses fill:#e3f2fd
```

**Principles:**

- **Never silently fail.** Every failure mode produces an admin-visible
  signal (Sentry alert, dashboard widget, status banner).
- **Read paths degrade gracefully.** A Postgres outage means stale reads,
  not a 500 page.
- **Write paths fail loudly.** A user attempting a write during an outage
  gets a clear error, not silent acceptance.
- **Status page** for users — "we're aware, ETA X" beats opaque
  unavailability.

---

## 14. Native app slot (future)

**Status: proposed** — shows how the future native client integrates
without architectural changes. Per `repo-layout.md` §native and ADR-007.

```mermaid
flowchart TB
    subgraph clients[Clients]
        WEB[webapp<br/>Next.js<br/>existing]
        IOS[iOS app<br/>future]
        AND[Android app<br/>future]
        CHAT_EXT[3rd-party chat extension<br/>theoretical]
    end

    subgraph contract[Single contract]
        OPENAPI[/src/contracts/openapi.yaml/]
    end

    subgraph generated[Generated clients]
        TS[TypeScript client]
        SWIFT[Swift client]
        KOTLIN[Kotlin client]
    end

    subgraph backend[Backend]
        API[api FastAPI<br/>same endpoints for all clients]
    end

    OPENAPI --> TS
    OPENAPI --> SWIFT
    OPENAPI --> KOTLIN

    TS --> WEB
    TS --> CHAT_EXT
    SWIFT --> IOS
    KOTLIN --> AND

    WEB --> API
    IOS --> API
    AND --> API
    CHAT_EXT --> API

    style WEB fill:#e3f2fd
    style IOS fill:#e1bee7
    style AND fill:#e1bee7
    style CHAT_EXT fill:#f5f5f5
    style OPENAPI fill:#fff3e0
    style API fill:#e8f5e9
```

**The integration story:**

- Native app needs **zero new endpoints** — it consumes the same v1
  contract as the webapp.
- Auth works identically because tokens are bearer-style (ADR-009 path).
- Realtime works identically because SSE/WS are HTTP-native (ADR-010).
- The cost of "native-readiness" today is one CI codegen step, paid
  once.

This is the structural payoff of ADR-007's API-as-service decision —
adding a new client is a frontend project, not a backend project.

---

## Maintenance

This file is updated when:

- An ADR is accepted that changes a diagram's confidence level
  (`tentative` → `proposed` → `locked`)
- The schema changes (rare; PLAN.md §6 is the source of truth)
- A new system component is added (worker subtype, new external
  dependency, etc.)

Diagrams should never be more authoritative than the ADR or schema they
derive from. If a diagram and an ADR disagree, the ADR wins and the
diagram is wrong.
