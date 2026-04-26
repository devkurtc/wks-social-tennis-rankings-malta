# ADR-008: API language — FastAPI in Python

- **Status:** proposed
- **Date:** 2026-04-26
- **Deciders:** Kurt
- **Related:** ADR-007 (API as service), ADR-010 (realtime), ADR-011
  (GraphQL deferred), ADR-012 (contract codegen), `../../PLAN.md` §5.1, §5.2

## Context

ADR-007 established that the public API lives in `src/services/api/` as
a standalone service. The remaining question is what language and
framework that service uses.

PLAN.md §5.1 originally picked Next.js + TypeScript with the assumption
that API and UI shared a runtime. ADR-007 broke that assumption: the API
is no longer in Next.js. So the language choice for the API is now open.

The 2026-04-26 conversation also added two requirements that bear on
this decision:

1. **WebSockets at some point** — for live tournament updates, captain
   collaboration features.
2. **GraphQL deferred** (per ADR-011, when drafted) — REST + OpenAPI is
   the contract. So we don't need a framework with a strong GraphQL story.

Two existing locked decisions further constrain this:

- The rating engine (OpenSkill) is Python (PLAN.md §5.2)
- The ingestion agent will be Python (PLAN.md §5.3)

## Decision drivers

- **Service-boundary cost for rating-aware reads** — every API endpoint
  that needs to compute "what would this player's rating be if they won
  this match" or "what's the predicted outcome of this hypothetical pair"
  has to either call into the Python rating engine, or duplicate the
  rating math in another language. Same-language API removes this hop.
- **Realtime (SSE + WS)** — the API must support both, well, with first-class
  framework support — not via contortions or third-party adapters
- **Contract codegen** — the API must produce or consume an OpenAPI
  spec cleanly so the TS and (future) Swift/Kotlin clients can be generated
- **Operational simplicity** — one runtime per backend service tier is
  easier to operate than two (Python worker + TS API + Python ingestion =
  two languages on the backend; all-Python = one)
- **Maintainer fluency** — Kurt is the primary author. Stack choice
  shouldn't introduce a language he's less comfortable maintaining at
  the API layer specifically

## Options considered

### Option 1: TypeScript — Hono on Bun (or Fastify on Node)

**Pros**
- Same language as webapp; if codegen ever breaks, types can be
  hand-shared
- Hono is small, fast, has first-class SSE/WS support
- Bun's startup time and bundler are excellent for rapid dev iteration
- Strong TypeScript inference for request/response validation (Zod)

**Cons**
- **Service-boundary cost is real**: every rating-aware endpoint must
  cross into the Python worker. This is at minimum a Redis enqueue +
  result-poll cycle, or an internal HTTP call to a Python sidecar.
  Compare to Python API where it's a function call.
- Two backend languages to maintain (TS for API, Python for worker +
  ingestion)
- "Shared types with webapp" benefit is illusory once we commit to
  OpenAPI codegen for the native client — webapp will go through the
  same generator
- Bun is still a younger production runtime than Node; Node + Fastify
  is mature but adds a build step we'd skip with Bun
- No native interop with OpenSkill — we'd be calling out to Python for
  *every* prediction the chatbot wants to make ("what if X+Y played W+Z")

### Option 2: Python — FastAPI

**Pros**
- **Same language as worker and ingestion** — one backend language; one
  CI image base; one set of linting/test conventions
- **Direct calls into rating engine** — no service hop for reads,
  predictions, or chatbot tool calls that need rating math. The
  `predict_match(side_a, side_b)` chat tool becomes a function call,
  not an inter-service HTTP request
- FastAPI has first-class WebSocket and SSE-style streaming via Starlette
- Pydantic v2 is excellent for request/response validation and produces
  OpenAPI 3.1 automatically (code-first OpenAPI, no hand-authoring)
- Mature ecosystem: SQLAlchemy or psycopg, Alembic for migrations,
  authlib for OAuth, Anthropic Python SDK for the chatbot
- TypeScript client for the webapp is generated from FastAPI's OpenAPI
  output — same pipeline the native client will use

**Cons**
- Webapp gets API types via codegen, not native imports (need a
  generator step in CI)
- Python is slower than Bun/Node on raw HTTP throughput — irrelevant
  at our scale (low hundreds of RPS at peak), but worth naming
- Python WebSocket scaling beyond a few thousand concurrent connections
  per process needs worker tuning — also irrelevant at our scale
- The maintainer (Kurt) needs comfortable Python depth — already have it
  per Phase 0 work

### Option 3: Python — Litestar or Sanic instead of FastAPI

**Pros**
- Litestar has cleaner DI and built-in plugin system; arguably better for
  a long-lived production API
- Sanic is very fast and async-first

**Cons**
- Smaller community than FastAPI; smaller pool of help, fewer integrations
- FastAPI's Pydantic-based OpenAPI generation is the most mature
- No clear advantage for this app's needs that justifies the unfamiliarity tax

### Option 4: Mixed — TS for "thin" public endpoints, Python for chat + admin

**Pros**
- "Use the right tool for each job"

**Cons**
- Two API surfaces, two auth implementations, two deployment pipelines,
  two on-call playbooks — for one product
- Decisively rejected; listed only to record we considered it

## Decision

> The public API service is implemented in **Python with FastAPI**,
> living in `src/services/api/`. OpenAPI 3.1 is generated from FastAPI's
> route definitions and committed to `src/contracts/openapi.yaml` for
> client codegen.

Option 2. The same-language win across api + worker + ingestion is the
single biggest operational simplification available, and it directly
benefits the chatbot's `predict_match` tool by making it a function call
instead of a service hop. The "shared types with webapp" argument that
historically favored TypeScript collapsed once ADR-007 separated the
webapp from the API and once we committed to a native client (which
requires codegen anyway). FastAPI's WebSocket and streaming support
covers the realtime requirements without contortion.

## Consequences

### Enables

- Chatbot tools call `predict_match(...)`, `compute_partner_strength(...)`,
  etc. as Python functions — zero service-hop overhead, zero serialization
  cost, deterministic latency
- One Python toolchain for backend services: same `pyproject.toml`
  conventions, same pytest setup, same Ruff/Black config, same Docker
  base image
- OpenAPI is automatically up-to-date with the code (Pydantic models =
  schema definitions); generator step in CI emits the TS + Swift + Kotlin
  clients consistently
- Python ecosystem for OAuth (Authlib), Postgres (psycopg / SQLAlchemy),
  Redis (redis-py), Anthropic SDK (anthropic) is well-trodden
- Realtime (SSE + WS) handled by Starlette, which FastAPI builds on —
  same lifecycle, same auth dependency injection

### Constrains / costs

- Webapp's type-safety contract depends on the codegen pipeline working
  reliably (tracked under ADR-012)
- Python API is slower per-request than a Bun/Node API — a real cost
  only if we ever exceed ~500 RPS sustained, which is years away at
  realistic VLTC + few-clubs scale
- WebSocket fan-out to many clients requires worker tuning if we ever
  exceed a few thousand concurrent connections — far beyond projected scale
- The maintainer must stay current in async Python (Starlette/anyio,
  asyncio patterns) — not a new burden given the rating engine is also Python

### Revisit triggers

- **Codegen pipeline cost exceeds value** — if `contracts/generated/`
  becomes a source of frustration, we revisit (likely toward
  hand-authored OpenAPI in `contracts/openapi.yaml` rather than toward
  changing language)
- **Sustained API load exceeds 500 RPS** with response-time degradation
  attributable to Python — revisit whether to extract a hot subset to a
  faster runtime; do not preemptively optimize
- **A future contributor brings strong TS expertise and weak Python
  expertise** and joins maintainership — revisit; the decision serves
  the team, not the other way round

## Validation

This decision is working if:

- Webapp and (future) native client both consume the same generated
  client without complaint
- Chatbot tool implementations are short, function-call shaped Python
  rather than HTTP-orchestration code
- API p99 latency stays under SLOs defined in ADR-018
- Adding a new endpoint takes < 1 hour from "I have an idea" to "it's
  in OpenAPI and tested"

## Related work

- ADR-007 — API as standalone service
- ADR-010 — Realtime: FastAPI's SSE + WS used here
- ADR-012 — Contract codegen pipeline
- TASKS.md (TBD): "T-P1-002 — Scaffold FastAPI app with health endpoint,
  Pydantic settings, and OpenAPI dump-on-build"
