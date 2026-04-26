# Architecture

Status: **proposed** — supersedes the diagram in PLAN.md §4 once ADR-007
is accepted.

This document is the visual + textual reference for how RallyRank's
components fit together. It is updated when an accepted ADR changes a
component, boundary, or data flow. Keep it terse — detail belongs in the
ADR that introduced it.

## C4 — Context (what's at the boundary)

```mermaid
flowchart LR
    subgraph users[Users]
        U1[Anonymous visitor]
        U2[Club member]
        U3[Captain]
        U4[Admin]
    end

    subgraph external[External services]
        CF[Cloudflare<br/>DNS + Tunnel + CDN]
        ANTHROPIC[Anthropic API<br/>Claude — chat + ingestion]
        BACKUP[Off-site backup<br/>Hetzner Storage Box / B2]
    end

    SYSTEM[RallyRank<br/>self-hosted]

    U1 -->|HTTPS| CF
    U2 -->|HTTPS| CF
    U3 -->|HTTPS + auth| CF
    U4 -->|HTTPS + auth + 2FA| CF
    CF <-->|tunnel| SYSTEM
    SYSTEM -->|HTTPS| ANTHROPIC
    SYSTEM -->|encrypted upload| BACKUP

    style SYSTEM fill:#f5f5f5,stroke:#333,stroke-width:2px
```

**Trust boundary:** the only ingress to the system is via Cloudflare
Tunnel. The home/Hetzner host has no inbound ports open to the public
internet. See ADR-014.

## C4 — Containers (what runs where)

```mermaid
flowchart TB
    subgraph edge[Cloudflare edge]
        CF[Cloudflare Tunnel<br/>+ WAF + cache]
    end

    subgraph host[Host: Proxmox LXC now → Hetzner later]
        subgraph net[Docker network: rallyrank]
            CFD[cloudflared<br/>tunnel client]

            subgraph webtier[Web tier]
                WEB[webapp<br/>Next.js<br/>UI only — no API]
            end

            subgraph apptier[Application tier]
                API[api<br/>FastAPI<br/>HTTP + SSE + WS]
                WORKER[worker<br/>Python<br/>rating engine + jobs]
                INGEST[ingestion<br/>Python<br/>agentic Excel parser]
            end

            subgraph datatier[Data tier]
                PG[(Postgres)]
                REDIS[(Redis<br/>job queue + cache)]
                MINIO[(MinIO<br/>S3-compatible<br/>source files + backups staging)]
            end
        end
    end

    EXT_CLAUDE[Anthropic API]
    BACKUP[Off-site backup]

    CF --> CFD
    CFD --> WEB
    CFD --> API

    WEB -->|HTTPS internal| API

    API --> PG
    API --> REDIS
    API -->|enqueue jobs| REDIS
    API -->|stream chat tokens| EXT_CLAUDE

    WORKER --> PG
    WORKER -->|consume jobs| REDIS

    INGEST --> PG
    INGEST -->|consume jobs| REDIS
    INGEST --> MINIO
    INGEST -->|tool-using LLM| EXT_CLAUDE

    PG -.->|nightly pg_dump<br/>encrypted| BACKUP
    MINIO -.->|periodic mc mirror| BACKUP

    style WEB fill:#e3f2fd
    style API fill:#fff3e0
    style WORKER fill:#fff3e0
    style INGEST fill:#fff3e0
    style PG fill:#e8f5e9
    style REDIS fill:#e8f5e9
    style MINIO fill:#e8f5e9
```

**Why this shape (versus PLAN.md §4):**

- API is now a separate service, not Next.js routes. See ADR-007.
- Webapp's only outbound dependency is the API — no direct DB/Redis access.
  This is what makes a future native client a config-only addition.
- Worker and ingestion are separate processes (not threads in the API)
  so a long-running rating recompute or a slow Excel parse never blocks
  HTTP responses.

## Data flow — the four canonical paths

### Path 1: Anonymous user views a leaderboard

```mermaid
sequenceDiagram
    autonumber
    participant U as User browser
    participant CF as Cloudflare
    participant W as webapp (Next.js)
    participant A as api (FastAPI)
    participant PG as Postgres

    U->>CF: GET /leaderboard
    CF->>W: (cache miss) request
    W->>A: GET /api/v1/leaderboard?gender=men&tier=A
    A->>PG: SELECT FROM v_player_summary ...
    PG-->>A: rows
    A-->>W: JSON
    W-->>CF: rendered HTML (ISR)
    CF-->>U: HTML + cache headers
    Note over CF: subsequent requests within<br/>revalidate window served from edge
```

### Path 2: Member chats with the bot

```mermaid
sequenceDiagram
    autonumber
    participant U as Member browser
    participant CF as Cloudflare
    participant A as api (FastAPI)
    participant CL as Anthropic API
    participant PG as Postgres

    U->>CF: POST /api/v1/chat (SSE upgrade)
    CF->>A: stream
    A->>A: rate-limit + per-user cost budget check
    A->>CL: messages.stream() with tools
    CL-->>A: tool_use: search_players(q="kurt")
    A->>PG: SELECT FROM players ...
    PG-->>A: results
    A->>CL: tool_result
    CL-->>A: token stream (final answer in markdown + mermaid)
    A-->>CF: SSE events
    CF-->>U: streamed response
```

### Path 3: Admin uploads a tournament file

```mermaid
sequenceDiagram
    autonumber
    participant Adm as Admin browser
    participant A as api (FastAPI)
    participant M as MinIO
    participant R as Redis
    participant I as ingestion
    participant CL as Anthropic API
    participant PG as Postgres
    participant W as worker

    Adm->>A: POST /api/v1/admin/upload (xlsx)
    A->>M: store file
    A->>PG: INSERT source_files, ingestion_runs (status=running)
    A->>R: enqueue ingestion job
    A-->>Adm: 202 Accepted + run_id
    R-->>I: dequeue
    I->>M: fetch file
    I->>CL: structured extraction (tool calls)
    I->>PG: INSERT matches (active), aliases, quality_report
    I->>R: enqueue rating-recompute
    R-->>W: dequeue
    W->>PG: rebuild ratings
    W->>R: publish "ratings_updated" → cache invalidate
    Note over Adm: dashboard widget shows<br/>"new report unreviewed"
```

### Path 4: Re-process a previous ingestion (idempotent supersede)

```mermaid
sequenceDiagram
    autonumber
    participant Adm as Admin
    participant A as api
    participant R as Redis
    participant I as ingestion
    participant PG as Postgres
    participant W as worker

    Adm->>A: POST /api/v1/admin/runs/:id/reprocess
    A->>PG: INSERT new ingestion_runs row<br/>(supersedes_run_id = :id)
    A->>R: enqueue
    R-->>I: dequeue
    I->>PG: insert new matches with new run_id<br/>UPDATE old matches SET superseded_by_run_id = new
    I->>R: enqueue full rating recompute
    R-->>W: dequeue
    W->>PG: TRUNCATE rating_history; recompute from active matches
    W->>R: publish invalidate
```

Per PLAN.md §5.3.1 — re-processing is idempotent because all reads filter
`WHERE superseded_by_run_id IS NULL`.

## Deployment topology

### Today (Proxmox at home)

```mermaid
flowchart LR
    subgraph cf[Cloudflare]
        CFTunnel[Tunnel endpoint]
    end

    subgraph home[Home network]
        ROUTER[Home router<br/>NO inbound ports open]
        subgraph proxmox[Proxmox host]
            subgraph lxc[LXC: rallyrank]
                COMPOSE[docker-compose<br/>all containers]
            end
        end
    end

    INTERNET((Internet))
    INTERNET --> CFTunnel
    CFTunnel <-->|outbound TCP from home| ROUTER
    ROUTER --> COMPOSE
```

### Future (Hetzner CX series)

```mermaid
flowchart LR
    subgraph cf[Cloudflare]
        CFTunnel[Tunnel endpoint<br/>same hostname]
    end

    subgraph hetzner[Hetzner Helsinki / Falkenstein]
        subgraph vm[CX VPS]
            COMPOSE[docker-compose<br/>same compose files]
        end
    end

    INTERNET((Internet))
    INTERNET --> CFTunnel
    CFTunnel <-->|outbound TCP from VPS| COMPOSE
```

**Migration is config-only:** stop the Proxmox tunnel client, start a new
one on Hetzner with the same tunnel ID. DNS does not change. Public
hostname does not change. See ADR-014.

## Component responsibilities

| Component | Owns | Talks to | Doesn't talk to |
|---|---|---|---|
| `cloudflared` | tunnel ingress, edge cache compatibility | Cloudflare edge, webapp:3000, api:8000 | Postgres, Redis, MinIO |
| `webapp` (Next.js) | rendering, page routing, ISR cache | api (HTTPS) | Postgres, Redis, MinIO directly |
| `api` (FastAPI) | HTTP/SSE/WS surface, auth, request validation, chat orchestration | Postgres (read mostly), Redis (enqueue + cache), Anthropic API | MinIO directly (delegates to ingestion), spreadsheets |
| `worker` (Python) | rating engine, scheduled recompute, cache invalidation | Postgres (read+write rating tables), Redis (consume) | HTTP clients, MinIO |
| `ingestion` (Python) | spreadsheet parsing, agentic extraction, quality reports | Postgres (write matches), MinIO (read/write files), Redis (consume), Anthropic API | rating math (enqueues a job for worker) |
| `Postgres` | source of truth for all relational data | nothing — clients connect to it | nothing outbound |
| `Redis` | job queue, ephemeral cache, pub/sub for invalidation | nothing — clients connect to it | nothing outbound |
| `MinIO` | source spreadsheet storage, backup staging | nothing — clients connect to it | nothing outbound |

## Open architecture questions (tracked as ADRs)

| Question | ADR | Status |
|---|---|---|
| API as service (not Next.js routes) | ADR-007 | proposed |
| API language | ADR-008 | proposed (FastAPI) |
| Auth strategy (JWT vs session) | ADR-009 | not yet drafted |
| Realtime (SSE vs WS per use case) | ADR-010 | not yet drafted |
| GraphQL deferred | ADR-011 | not yet drafted |
| Contract source-of-truth | ADR-012 | not yet drafted |
| Monorepo tooling | ADR-013 | not yet drafted |
| Hosting + ingress | ADR-014 | proposed (CF Tunnel) |
| Backup + DR | ADR-015 | not yet drafted |
| Quality bar definition | ADR-016 | not yet drafted |

See `adr/INDEX.md` for the full roster.
