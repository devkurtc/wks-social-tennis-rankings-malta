# Repo layout

Status: **proposed** — formalized by ADR-007 (API as service) and the
2026-04-26 conversation locking `/src/services` + `/src/webapp`.

This is the target structure for Phase 1 onward. Phase 0 code in
`scripts/phase0/` migrates into `src/services/worker/` at the start of
Phase 1 (decided 2026-04-26: Phase 0 keeps working as-is during the
design phase).

## Tree

```
/                                       ← repo root
├── PLAN.md                             canonical project plan
├── TASKS.md                            operational task tracker
├── CLAUDE.md                           agent orientation
├── README.md                           project README (TBD)
│
├── DESIGN/                             this dossier — ADRs, contracts, specs
│   ├── README.md
│   ├── repo-layout.md  (this file)
│   ├── architecture.md
│   ├── adr/
│   ├── contracts/                      OpenAPI, event schemas
│   ├── pages/                          page specs / wireframes
│   ├── runbooks/                       incident playbooks
│   ├── quality-bar.md
│   ├── perf-budget.md
│   ├── privacy.md
│   ├── threat-model.md
│   └── chat-eval.yaml
│
├── _DATA_/                             source spreadsheets — read-only
│   ├── VLTC/                           bootstrap club
│   ├── TCK/                            future club
│   └── ...                             year-bucketed mirror folders
│
├── _RESEARCH_/                         exploratory notes (not authoritative)
│
├── src/
│   ├── contracts/                      single source of truth for cross-service types
│   │   ├── openapi.yaml                public API contract — webapp + native + chat all consume
│   │   ├── events.yaml                 Redis job/message schemas
│   │   └── generated/                  TS + Python clients (gitignored, built in CI)
│   │       ├── ts/
│   │       └── py/
│   │
│   ├── services/
│   │   ├── api/                        FastAPI HTTP+SSE+WS server
│   │   │   ├── pyproject.toml
│   │   │   ├── app/
│   │   │   │   ├── main.py
│   │   │   │   ├── routes/             one module per resource (/leaderboard, /players, ...)
│   │   │   │   ├── auth/               JWT issuer + middleware
│   │   │   │   ├── realtime/           SSE + WS handlers
│   │   │   │   ├── chat/               Claude tool-calling orchestrator
│   │   │   │   └── deps/               DB, Redis, settings — DI factories
│   │   │   ├── tests/
│   │   │   └── Dockerfile
│   │   │
│   │   ├── worker/                     Python: rating engine, recompute jobs
│   │   │   ├── pyproject.toml
│   │   │   ├── rallyrank_worker/
│   │   │   │   ├── rating/             OpenSkill engine (Phase 0 code lands here)
│   │   │   │   ├── jobs/               Redis-consumer job handlers
│   │   │   │   └── schedules/          cron-like recompute / refresh tasks
│   │   │   ├── tests/
│   │   │   └── Dockerfile
│   │   │
│   │   ├── ingestion/                  Python: agentic Excel → matches (Phase 3)
│   │   │   ├── pyproject.toml
│   │   │   ├── rallyrank_ingest/
│   │   │   │   ├── agent/              Claude API tool-using extractor
│   │   │   │   ├── parsers/            template parsers (Phase 0 parsers move here)
│   │   │   │   └── quality/            quality-report generator
│   │   │   ├── tests/
│   │   │   └── Dockerfile
│   │   │
│   │   └── shared/                     code shared across Python services
│   │       ├── pyproject.toml
│   │       ├── rallyrank_shared/
│   │       │   ├── db/                 SQLAlchemy models or psycopg helpers
│   │       │   ├── migrations/         versioned SQL migrations (alembic or plain)
│   │       │   ├── audit/              audit_log helper (PLAN.md §5.5)
│   │       │   ├── identity/           player normalization, alias resolution
│   │       │   └── settings/           Pydantic Settings — env loading
│   │       └── tests/
│   │
│   ├── webapp/                         Next.js — UI only, no API routes
│   │   ├── package.json
│   │   ├── app/                        App Router pages
│   │   ├── components/
│   │   ├── lib/
│   │   │   └── api-client/             generated TS client from contracts/openapi.yaml
│   │   ├── tests/
│   │   └── Dockerfile
│   │
│   └── native/                         (future) React Native / Expo
│       └── README.md                   placeholder — populated when Phase ≥5
│
├── infra/
│   ├── docker-compose.yml              local dev composition
│   ├── docker-compose.prod.yml         production overlay (CF Tunnel container, prod env)
│   ├── caddy/                          (legacy — may be replaced by Cloudflare Tunnel; see ADR-014)
│   ├── cloudflared/                    tunnel config
│   ├── secrets/                        SOPS-encrypted secrets (.enc.yaml only)
│   └── deploy/                         deploy scripts, GH Actions workflows referenced from .github/
│
├── scripts/                            one-off ops scripts (backfill, migrate, restore)
│   └── phase0/                         RETIRES at start of Phase 1; code migrates to src/services/worker
│
└── .github/
    └── workflows/                      lint, typecheck, test, build, deploy
```

## Folder responsibilities — quick reference

| Folder | Owns | Doesn't own |
|---|---|---|
| `src/contracts/` | API contract, event schemas, generated clients | Implementation logic |
| `src/services/api/` | HTTP/SSE/WS surface, auth, request validation, response shaping | Rating math, ingestion, DB schema |
| `src/services/worker/` | Rating engine, recompute jobs, scheduled refreshes | HTTP, user-facing concerns |
| `src/services/ingestion/` | Spreadsheet → matches, quality reports | Rating math (delegates to worker), serving |
| `src/services/shared/` | DB schema, migrations, audit, identity, settings | Service-specific HTTP/job handlers |
| `src/webapp/` | UI pages, components, client-side state, calling API | API endpoints (none in Next.js per ADR-007) |
| `infra/` | Compose files, ingress config, secrets, deploy scripts | Application code |
| `scripts/` | One-off operational tools (e.g., one-time backfill) | Long-lived service code |

## Phase 0 → Phase 1 migration path

When Phase 1 begins (post-design-phase):

1. `scripts/phase0/db.py`, `players.py`, `rating.py`, `team_selection.py` →
   `src/services/worker/rallyrank_worker/` (refactored to import from
   `src/services/shared`).
2. `scripts/phase0/parsers/*.py` → `src/services/ingestion/rallyrank_ingest/parsers/`.
3. `scripts/phase0/schema.sql` → `src/services/shared/rallyrank_shared/migrations/0001_initial.sql`
   (with port to Postgres dialect).
4. `scripts/phase0/cli.py` retired; replaced by:
   - HTTP endpoints in `src/services/api/`
   - Operational CLI in `src/services/worker/` (separate entrypoint)
5. `scripts/phase0/test_*.py` → moved alongside their new homes; coverage
   gate enabled in CI per ADR-016.

The migration is a single PR with explicit before/after — not incremental
drift. Phase 0 keeps working until the moment of cutover.

## Why no `apps/` or `packages/`

Many monorepos split `apps/` (deployable units) and `packages/` (shared
libs). RallyRank's structure puts both under `src/` because:

- Only `src/services/shared/` is library-shaped; everything else is a
  deployable. One library doesn't justify a `packages/` tier.
- `src/contracts/` *looks* package-like but is a build artifact + a YAML
  source — not a long-lived imported library.
- Future native app slots cleanly into `src/native/` without restructuring.

## Related

- ADR-007 — API as standalone service (amends PLAN.md §4)
- ADR-008 — API language is FastAPI/Python
- ADR-013 — Monorepo tooling (TBD)
- ADR-014 — Hosting + ingress
- `PLAN.md` §4, §5.6
