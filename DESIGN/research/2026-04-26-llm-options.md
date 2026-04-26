# LLM options — providers, pricing, projected cost

- **Date:** 2026-04-26
- **Author:** Kurt (with Claude assist)
- **Status:** complete
- **Informs:** ADR-023 (chatbot LLM strategy), ADR-025 (ingestion LLM
  strategy — to be drafted)
- **Question this answers:** Which LLM provider(s) should RallyRank's
  member-facing chatbot and admin-side ingestion agent use, and what
  will it cost at realistic scale?

## Summary

Two-track recommendation:

| Use case | Champion model | Path | Projected cost (steady state) |
|---|---|---|---|
| Chatbot (public, streaming, tool-using) | **Anthropic Sonnet 4.6** | direct SDK | ~$370/month |
| Ingestion agent (admin, batch, structured) | **Anthropic Sonnet 4.6** | direct SDK (Batch API where latency-tolerant) | ~$13/month |

Behind a thin internal `LLMProvider` abstraction so we can A/B-test
challengers (GPT-5, Gemini 2.5 Flash, Haiku 4.5) per the
champion/challenger pattern in PLAN.md §5.7, and so a provider outage
fails over to a different SDK without rewrites.

**Rejected: OpenRouter as the primary chatbot path** — documented
streaming tool-call bugs for Anthropic models (April 2026) make it
unsafe for our flagship feature, which is built on streaming tool-use.

## Provider price sheet

All prices in USD per million tokens. Verified 2026-04-26.

### Frontier models

| Provider / Model | Input | Output | Cache write (5m) | Cache read | Context | Notes |
|---|---:|---:|---:|---:|---:|---|
| Anthropic Opus 4.7 | $5.00 | $25.00 | $6.25 | $0.50 | 1M | Major price drop from 4.1's $15/$75 |
| Anthropic Sonnet 4.6 | $3.00 | $15.00 | $3.75 | $0.30 | 1M | The "default" frontier model |
| OpenAI GPT-5 | $0.625 | $5.00 | n/a | ~$0.063 | 400k | Extremely competitive on input price |
| OpenAI GPT-5 Mini | $0.250 | $2.00 | n/a | ~$0.025 | 400k | Strong cost/quality |
| Google Gemini 2.5 Pro | $1.25 | $10.00 | n/a | $0.125 | 1M | Doubles to $2.50/$15 over 200k tokens |

### Cheap / fast tier

| Provider / Model | Input | Output | Cache | Notes |
|---|---:|---:|---:|---|
| Anthropic Haiku 4.5 | $1.00 | $5.00 | $0.10 read | Same Anthropic SDK — drop-in cheap fallback |
| Google Gemini 2.5 Flash | $0.30 | $2.50 | $0.03 read | Excellent cost; 1M context |
| Google Gemini 2.5 Flash-Lite | $0.10 | $0.40 | $0.01 read | Cheapest Google option; quality much weaker |
| DeepSeek V3 | $0.14 | $0.28 | $0.03 read | Strikingly cheap; weaker tool-use than frontier |
| Groq Llama 3.3 70B | $0.59 | $0.79 | (free hits) | Open model; ~10× faster inference than alternatives |
| DeepInfra Llama 3.3 70B | $0.15 | $0.35 | n/a | Cheapest hosted Llama |

### Gateway

| Service | Markup | Notes |
|---|---|---|
| OpenRouter | 0% on inference; ~5% Stripe fee on credit top-ups | Pass-through pricing; documented streaming tool-call bugs for Anthropic |

## Workload model — what we'll actually consume

These projections are conservative on the chatbot side (more usage than
realistically expected at launch). They're the volume against which the
cost projections are calculated.

### Chatbot — steady state estimate

**Assumption:** Phase 2 launch with VLTC + 1–2 more clubs. ~600 members
total. 50 daily-active chat users. 2 sessions per user per day. 5 queries
per session = **15,000 queries/month**.

| Item | Per query | Per month |
|---|---:|---:|
| System prompt + tool definitions (cacheable) | 8,000 tokens | — |
| Cache writes (start of each session) | — | ~12M tokens |
| Cache reads (queries 2+ in a session) | 8,000 | ~108M tokens |
| Fresh input (user msg + tool results) | ~1,500 | ~22.5M tokens |
| Output (markdown answer + sometimes mermaid chart) | ~1,000 | ~15M tokens |

### Ingestion — Phase 3 steady state

**Assumption:** 5 clubs × ~10 tournament files/month = **50 files/month**
of agentic Excel parsing.

| Item | Per file | Per month |
|---|---:|---:|
| System+tools (cacheable across files) | 3,000 tokens | — |
| Excel content + tool round-trips (uncached) | ~60,000 | ~3M tokens input |
| Output (structured matches) | ~5,000 | ~0.25M tokens output |

## Monthly cost projection

### Chatbot (15,000 queries/month)

| Model | Cache writes | Cache reads | Fresh input | Output | **Total /mo** |
|---|---:|---:|---:|---:|---:|
| Opus 4.7 | $75 | $54 | $113 | $375 | **$617** |
| Sonnet 4.6 | $45 | $32 | $68 | $225 | **$370** |
| Haiku 4.5 | $15 | $11 | $23 | $75 | **$123** |
| GPT-5 | n/a | $7 | $22 | $75 | **$104** |
| Gemini 2.5 Pro | n/a | $14 | $43 | $150 | **$207** |
| Gemini 2.5 Flash | n/a | $3 | $10 | $38 | **$51** |
| GPT-5 Mini | n/a | $3 | $9 | $30 | **$42** |
| DeepSeek V3 | n/a | $3 | $5 | $4 | **$12** |
| Groq Llama 3.3 70B (no cache) | n/a | n/a | $84 | $12 | **$96** |

### Ingestion (50 files/month, Phase 3)

| Model | Input | Output | **Total /mo** |
|---|---:|---:|---:|
| Opus 4.7 | $16 | $6 | **$22** |
| Sonnet 4.6 | $9 | $4 | **$13** |
| Haiku 4.5 | $3 | $1 | **$4** |
| GPT-5 | $2 | $1 | **$3** |
| Gemini 2.5 Pro | $4 | $3 | **$7** |

### Total LLM cost across phases

| Phase | Chat | Ingestion | **Monthly total** |
|---|---:|---:|---:|
| Phase 2 launch (VLTC only, ~10 daily users) | ~$75 | $0 (Phase 3 not live) | **~$75/mo** |
| Phase 3 steady state (3 clubs, 50 daily users) | $370 | $13 | **~$385/mo** |
| Mature (5 clubs, 100+ daily users) | ~$750 | $25 | **~$775/mo** |

## Quality vs cost — where each model genuinely fits

| Model | Tool-use reliability | Hallucination resistance | Streaming | Best for |
|---|---|---|---|---|
| Sonnet 4.6 | Excellent — Anthropic's strength | High | Mature | **Default chatbot champion** |
| Opus 4.7 | Excellent | Highest | Mature | Overkill for tennis Q&A; reserve for ingestion edge cases |
| GPT-5 | Excellent | High | Mature | **Strong challenger to Sonnet — same league** |
| Haiku 4.5 | Good | Medium | Mature | Cheap fallback / high-volume routine queries |
| Gemini 2.5 Pro | Very good | Medium-High | Mature | Long-context (1M) — useful for ingestion of large Excels |
| Gemini 2.5 Flash | Good | Medium | Mature | High-volume cheap tier |
| GPT-5 Mini | Good | Medium | Mature | Direct GPT-5 alternative; strong cost |
| Llama 3.3 70B (Groq) | Adequate — degrades on multi-step | Lower | Yes (very fast) | Speed demos; not for production tool-use |
| DeepSeek V3 | Adequate — known weaker on agentic tool-use | Medium | Yes | Cost benchmarks; not yet production-grade for agentic chat |

## Key insights

### Prompt caching is a 4–5× cost lever for chat

Without caching, every query re-pays for the 8k-token system+tools
prompt. Sonnet 4.6 with caching = $370/mo; without caching it would be
~$1,700/mo. Any provider that doesn't pass caching savings through
cleanly is materially more expensive than its sticker price suggests.

### Output tokens dominate output cost

15M output × $15 = $225 of Sonnet's $370 bill — over 60% of total cost.
The single biggest optimization for chat cost is *response brevity* in
the system prompt: "answer in ≤200 words unless asked for detail." That
alone cuts the bill ~40%.

### Ingestion model choice barely moves the needle

50× lower volume than chat means ingestion costs $3–$22/mo regardless
of provider. **Always pick the highest-quality model that supports proper
tool-use** for ingestion — it's where parsing errors cascade into bad
ratings, and the cost difference is negligible.

### OpenRouter — the deal-breaker

OpenRouter is appealing on paper (one SDK, automatic fallback,
multi-model A/B testing) but has two specific issues for our architecture:

1. **Documented streaming tool-call bugs for Anthropic models** (multiple
   production reports as of April 2026): empty `arguments` fields when
   streaming tool calls through OpenRouter to Claude. This breaks the
   *core mechanism* of our chatbot, which is built on streaming tool-use
   (`search_players`, `get_player_profile`, `predict_match`, etc.).
2. **Pass-through pricing** with no markup is genuinely good — only ~5%
   Stripe fee on credit top-ups. Privacy is reasonable: doesn't log
   prompts by default. So the *commercial* downside is small.

**Net assessment:** OpenRouter is a fine fit for non-streaming batch use
cases, but the tool-call streaming bug pattern means we'd be building
our flagship feature on a known-flaky path. We can replicate the
multi-provider story for champion/challenger evaluation with a thin
internal `LLMProvider` abstraction that maps to Anthropic SDK + OpenAI
SDK + Google SDK directly — ~50 lines of code.

## Recommendation

### Chatbot (member-facing, public)

- **Champion: Anthropic Sonnet 4.6 via direct SDK** — $370/mo at projected
  volume; best-in-class tool-use; prompt caching pays off; mature streaming
- **Challenger candidates** to shadow-run quarterly:
  - GPT-5 ($104/mo) — same quality tier, much cheaper input
  - Gemini 2.5 Flash ($51/mo) — if quality holds for tennis-domain
    queries, large savings
  - Haiku 4.5 ($123/mo) — same Anthropic SDK; drop-in cheap fallback
- **Outage fallback:** Haiku 4.5 (zero integration cost, same SDK) or
  GPT-5 (one extra SDK)
- **Hard cost cap per user/day** + **monthly ceiling kill-switch**
  designed in (per ADR-024 chat safety)

### Ingestion (admin-side, Phase 3)

- **Sonnet 4.6 via direct SDK** — $13/mo at projected volume; top-tier
  tool-use; **Batch API discount available (50% off)** for non-time-
  sensitive runs → could halve to ~$7/mo
- **Reach for Opus 4.7 ($22/mo) on retry** when Sonnet fails on a
  complex spreadsheet — fallback escalation pattern

### Internal abstraction

A `LLMProvider` interface in `src/services/api/app/llm/` and
`src/services/ingestion/llm/` that wraps the direct SDK calls. ~100
lines. Lets us:

- Swap models per environment (dev = Haiku for cost; prod = Sonnet)
- Run shadow A/B tests against challengers
- Centralize cost-cap, rate-limit, and observability concerns
- Add OpenRouter or another provider later if the streaming bug gets fixed

### What we explicitly are not doing

- **OpenRouter as primary path** — streaming tool-call bug is
  disqualifying for the chatbot architecture
- **Self-hosted open models** (Ollama on the Proxmox box) — Llama 3.3
  70B needs ~140GB VRAM to run well; doesn't fit a home box; even if it
  did, quality on multi-step tool-use is below the production bar
- **DeepSeek as champion** — too cheap to ignore but agentic tool-use
  quality not yet at frontier-model level; recheck quarterly
- **Single-provider lock-in at the code level** — internal abstraction
  means we can pivot without rewriting; we don't *gain* anything by
  hard-coding Anthropic SDK calls everywhere

## Open follow-ups

These should be addressed in the ADRs that consume this research:

- **Per-user daily token cap** — what's the ceiling? Default suggestion:
  100k tokens/user/day (≈ $0.30 worst-case at Sonnet rates) → ADR-024
- **Monthly ceiling kill-switch** — at what total $/month do we
  automatically degrade chat to "service paused, contact admin"?
  Default suggestion: $1,500/mo → ADR-024
- **Anonymous chat allowed?** — if yes, abuse risk dominates cost
  modeling; if no (member-only), the projections above hold → ADR-023
- **Conversation retention policy** — affects GDPR + storage cost (small
  but non-zero) → ADR-006 + ADR-023
- **Quarterly re-research cadence** — set a calendar reminder to redo
  this analysis. Pricing and model availability shift fast; default
  cadence: every 90 days, or whenever a major model release happens

## Sources

All accessed 2026-04-26.

- [Anthropic Claude API pricing — official docs](https://platform.claude.com/docs/en/about-claude/pricing)
- [Google Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [OpenRouter FAQ](https://openrouter.ai/docs/faq)
- [OpenRouter prompt caching documentation](https://openrouter.ai/docs/guides/best-practices/prompt-caching)
- [OpenAI GPT-5 pricing breakdown (apidog)](https://apidog.com/blog/gpt-5-5-pricing/)
- [GPT-5 pricing per token (pricepertoken)](https://pricepertoken.com/pricing-page/model/openai-gpt-5)
- [OpenAI 2026 pricing breakdown (Lazzari)](https://nicolalazzari.ai/articles/openai-api-pricing-explained-2026)
- [Groq pricing](https://groq.com/pricing)
- [Llama 3.3 70B provider comparison (Artificial Analysis)](https://artificialanalysis.ai/models/llama-3-3-instruct-70b/providers)
- [DeepSeek API pricing](https://api-docs.deepseek.com/quick_start/pricing)
- [DeepInfra pricing](https://deepinfra.com/pricing)
- [OpenRouter Anthropic streaming tool-call issue (Bifrost write-up)](https://www.getmaxim.ai/articles/how-to-use-claude-code-with-any-model-or-provider-using-bifrost/)
- [Claude Code via OpenRouter — provider reliability notes](https://lgallardo.com/2025/08/20/claude-code-router-openrouter-beyond-anthropic/)
