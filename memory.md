# memory.md — AskPDF AI

**Long-Term Project Memory**
**Version:** 2.0 — Agentic RAG
**Purpose:** This file is the persistent memory for future AI-assisted coding sessions. Read this file in full before generating any code. Update it at the end of every phase per the protocol in §14.

---

## 1. Project Summary

AskPDF AI is a multi-tenant **Agentic RAG** SaaS application. Users create Knowledge Bases, upload documents (PDF/DOCX/TXT/MD), and chat with an AI **agent** that autonomously decides whether and how to search the knowledge base — potentially issuing multiple, differently-worded searches within a single turn — before composing an answer grounded strictly in retrieved content, with citations back to source excerpts. This is a deliberate architectural upgrade from a classic single-pass "embed → search once → generate" RAG design. It is being built via iterative, phase-by-phase AI-assisted development ("vibe coding") on a production-grade AWS-deployed architecture.

Full detail lives in the companion documents:
- `prd.md` — product requirements, personas, acceptance criteria (agentic requirements are Must-have for MVP, not future roadmap).
- `architecture.md` — system design, agent loop design (§5), data flow, deployment.
- `phases.md` — the 20-phase (0–19) implementation roadmap; Phases 11–13 specifically build the agent tools, orchestrator, and agentic chat endpoint.
- `design.md` — UI/UX specification, including live agent-activity and step-trace UI.
- `rules.md` — binding engineering rules, including agent-specific architecture, security, and prompt-engineering rules.

This file summarizes the decisions from those documents and tracks live implementation status — it does not replace them; consult the source document for full detail.

---

## 2. Vision (Condensed)

A self-serve, NotebookLM/ChatPDF/Perplexity-Spaces-like product, differentiated by **agentic retrieval**: organize documents into Knowledge Bases, ask questions (including complex/multi-hop ones), and get grounded, cited answers produced by an LLM agent that actively searches — deciding what to search for and whether to search again — rather than a fixed single-pass pipeline. Multiple independent chats per Knowledge Base share one vector index and the same agent toolset. Deployed on AWS with production-grade scalability, security, and observability.

---

## 3. Architecture Decisions (Locked)

- **Two fully independent pipelines:** Ingestion (async, via Worker + SQS) and Agentic Query (synchronous-but-multi-step, via API + Agent Orchestrator, streamed via SSE). They never share request-time code paths. **SQS is ingestion-only — the agent loop is never queued.**
- **Service split:** `apps/web` (Next.js), `apps/api` (FastAPI, including the Agent Orchestrator), `apps/worker` (Python SQS consumer) — three independently deployable ECS Fargate services. The agent adds no new infrastructure component; it is code inside the existing API service.
- **The query pipeline is agentic, not single-pass, by default in MVP** — this was a deliberate mid-project architectural upgrade (v1.0 → v2.0 of the docs) from an original classic-RAG design. The core change: retrieval (`search_knowledge_base`) is exposed to the LLM as a **tool** it decides whether/how/how-many-times to call, rather than a fixed pipeline step that always runs exactly once.
- **Bounded agent loop (`architecture.md` §5):** ReAct-style loop with hard guardrails — `max_iterations` (default 4), `max_wall_clock_ms` (default 20000), `max_tokens_per_turn`, duplicate-query short-circuiting via cosine similarity, and forced graceful termination (never a silent failure or infinite loop) when any bound is hit.
- **Agent tools (MVP toolset):** `search_knowledge_base` (the workhorse — vector search over the current KB), `get_document_context` (fetch surrounding chunks for more context), `list_documents` (see what's indexed before deciding to search). All three are tenant-scoped via **server-injected** `knowledge_base_id`/`user_id` in a `ToolContext` — never LLM-supplied arguments. This is a hard security boundary, not a convention.
- **Vector storage strategy:** One Qdrant **collection per Knowledge Base** (`kb_{knowledge_base_id}`), unchanged from the original design — this remains the isolation boundary even though Qdrant is now called from inside a tool rather than a fixed step.
- **Async-only ingestion:** No heavy processing (extraction, chunking, embedding) ever runs inside an API request. Upload triggers an SQS message; the Worker does all processing. Unchanged.
- **Provider abstraction, now tool-calling-aware:** `LLMProvider` and `EmbeddingProvider` interfaces exist from day one; `LLMProvider` specifically models function/tool-calling generically so a future provider swap (Claude, Gemini) doesn't require rewriting the orchestrator, only the provider implementation.
- **Statelessness:** Both API and Worker are stateless and horizontally scalable. The agent loop's state is held **only in-memory for the duration of a single request** — it is never partially persisted or resumed; a retried/failed turn always starts a fresh loop.
- **Tenant isolation is now three-layered:** (1) Qdrant collection-per-KB, (2) mandatory `user_id`/`knowledge_base_id` filters on every PostgreSQL query, enforced through the full ownership chain, **(3) tool-execution-layer enforcement** — every agent tool receives tenant context only from the orchestrator, never from the LLM, closing a prompt-injection-based cross-tenant leakage path.
- **Agent traceability:** every tool call the agent makes within a turn is persisted to a new `agent_steps` table (iteration, tool name, args, result summary, latency), linked to the resulting `messages` row, enabling both UI transparency (step-trace view) and future retrieval-quality evaluation.
- **Retrieved content is untrusted data in the prompt**, not instructions — an explicit, load-bearing security rule to defend against prompt injection embedded in uploaded documents attempting to make the agent call unregistered tools or leak data.

---

## 4. Technology Decisions (Locked)

| Layer | Choice |
|---|---|
| Frontend | Next.js, React, TypeScript, TailwindCSS, shadcn/ui, TanStack Query |
| Backend | FastAPI, Python, async-first, hosts the Agent Orchestrator |
| Auth | JWT (access + refresh), OAuth-ready schema, argon2 password hashing |
| Relational DB | PostgreSQL (AWS RDS in production), now including `agent_steps` |
| Vector DB | Qdrant, collection-per-KB, cosine distance, HNSW, invoked only via agent tools |
| Object storage | AWS S3 |
| Queue | Amazon SQS + DLQ — **ingestion only, never the agent path** |
| Embeddings | `sentence-transformers`, `BAAI/bge-small-en-v1.5` (384-dim) initially |
| LLM | OpenAI initially (must support tool/function calling + streaming), behind a tool-calling-aware provider abstraction (Claude/Gemini planned later) |
| Agent Orchestrator | Custom bounded ReAct-style loop inside the API service (`agent/orchestrator.py`) — not a third-party agent framework in MVP, to keep guardrail behavior fully understood and testable |
| Deployment | Docker, ECS Fargate, CloudWatch, GitHub Actions CI/CD; Terraform is a later phase |
| Rate limiting/caching | Redis — token-bucket rate limiting, query/tool-result embedding cache, doubles as the duplicate-query guardrail's lookup mechanism |

---

## 5. Folder Structure (Reference)

See `architecture.md` §13 for the full tree. Key top-level layout, with agent-specific additions:

```
askpdf-ai/
├── apps/web/       (Next.js frontend; components/chat/agent-step-trace.tsx is new)
├── apps/api/        (FastAPI service: core/, api/v1/, models/, schemas/,
│                      services/, repositories/, providers/, alembic/,
│                      agent/  <-- NEW: orchestrator.py, tools/, prompts/, guardrails.py)
├── apps/worker/     (SQS consumer: pipeline/{extract,clean,chunk,embed}.py,
│                      providers/, repositories/ — unchanged, no agent code here)
├── packages/shared/ (shared Python types between api & worker)
├── infra/           (docker/, ecs/, terraform/, github-actions/)
└── docs/            (this file and its companions)
```

`apps/api/app/agent/` is the single new top-level package versus the original non-agentic design; nothing else moved.

---

## 6. Coding Conventions (Reference)

Full rules in `rules.md`. Key points an AI session must never violate:

- Route handlers are thin; business logic lives in `services/` or the agent orchestrator; DB access lives in `repositories/`.
- All LLM/embedding calls go through `providers/` — never call SDKs directly elsewhere. **Qdrant is called only from inside a registered agent tool's `execute()` method** — nowhere else in the query path.
- Every tenant-scoped query, **including every agent tool call**, has an explicit ownership filter, verified through the full parent chain and injected via `ToolContext` — never accepted as an LLM-supplied argument.
- Every agent loop iteration re-checks guardrail state (`max_iterations`, `max_wall_clock_ms`, `max_tokens_per_turn`) before proceeding — no code path skips this check.
- Python: `black`/`ruff`/`mypy` (strict on `agent/` too), async-first, Pydantic schemas for all API I/O and all tool args/results, DI via FastAPI `Depends()`.
- TypeScript: strict mode, no unjustified `any`, server state only via TanStack Query (with in-flight streaming state as the one deliberate local-state exception).
- Conventional Commits; branch naming `feat/`, `fix/`, `chore/`, `infra/`, `release/` matching `phases.md`.

---

## 7. Naming Conventions (Reference)

- Python: `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE_CASE` constants.
- TypeScript: `camelCase` vars/functions, `PascalCase` components/types.
- DB: plural snake_case tables (`agent_steps`), `{table_singular}_id` foreign keys.
- API routes: plural, kebab-case (`/knowledge-bases`).
- Agent tool names: `snake_case`, verb-first, LLM-facing name = module name = function name (`search_knowledge_base`).
- SSE event names on the agent endpoint: fixed set — `agent_step`, `token`, `done`, `error`.
- SQS payloads: snake_case with a required `type` field; SQS message types are ingestion-only.

---

## 8. Database Schema Overview

Core tables (full DDL-level detail in `architecture.md` §10):

```
users            -> id, email, hashed_password, auth_provider, provider_user_id
knowledge_bases  -> id, user_id (FK), name, description
documents        -> id, knowledge_base_id (FK), filename, file_type, s3_key,
                     size_bytes, status (PENDING|PROCESSING|INDEXED|FAILED),
                     error_reason, page_count
chunks           -> id, document_id (FK), knowledge_base_id (FK, denormalized),
                     qdrant_point_id, chunk_index, content, token_count, page_number
chats            -> id, knowledge_base_id (FK), user_id (FK), title
messages         -> id, chat_id (FK), role, content, citations (JSONB),
                     token_usage (JSONB), agent_iteration_count (INT),
                     agent_budget_exhausted (BOOLEAN)
agent_steps      -> id, message_id (FK), iteration, tool_name, tool_args (JSONB),
                     result_summary (JSONB), latency_ms      -- NEW TABLE
```

All FKs `ON DELETE CASCADE`, including `agent_steps.message_id → messages.id`. Qdrant point payloads carry `document_id`, `chunk_id`, `knowledge_base_id`, `chunk_index`, `page_number`, `content_preview`, `embedding_model_version`.

---

## 9. Major APIs (Reference)

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/register` | Create user account |
| `POST /api/v1/auth/login` | Issue access + refresh tokens |
| `POST /api/v1/auth/refresh` | Rotate/refresh access token |
| `POST /api/v1/auth/logout` | Revoke refresh token |
| `GET/POST /api/v1/knowledge-bases` | List/create KBs |
| `PATCH/DELETE /api/v1/knowledge-bases/{id}` | Rename/delete a KB |
| `POST /api/v1/knowledge-bases/{id}/documents` | Upload a document |
| `GET/DELETE /api/v1/knowledge-bases/{id}/documents/{doc_id}` | Get status / delete a document |
| `GET/POST /api/v1/knowledge-bases/{id}/chats` | List/create chats |
| `PATCH/DELETE /api/v1/chats/{id}` | Rename/delete a chat |
| `POST /api/v1/chats/{id}/messages` | Send a message; runs the **bounded agent loop**; SSE-streamed `agent_step`/`token`/`done`/`error` events; persists message + citations + `agent_steps` trace |
| `GET /health`, `GET /health/ready` | Liveness/readiness (API and Worker), API readiness includes LLM-provider connectivity |

---

## 10. Knowledge Base Model (Reference)

```
User → Knowledge Base → Documents → Chunks → Embeddings (Qdrant)
                       ↳ Chats → Messages → Agent Steps (per-message trace)
```

A Knowledge Base owns one Qdrant collection and one registered agent toolset (currently fixed/global, not per-KB configurable in MVP beyond `top_k`/guardrail defaults). Multiple Chats within a KB share that same collection and toolset for retrieval but maintain fully independent message histories; each turn's agent loop is independent — prior turns' agent step traces are not replayed into a new turn's context.

---

## 11. Current Implementation Status

**As of this document's creation: no code has been written yet.** This is the planning/documentation baseline, now updated to reflect the agentic architecture decision, produced before Phase 0 begins.

### Completed Phases
- None yet.

### Pending Phases (see `phases.md` for full detail — now 20 phases, 0–19)
- Phase 0 — Project Setup & Foundations
- Phase 1 — Database Schema & Migrations (now includes `agent_steps`)
- Phase 2 — Authentication
- Phase 3 — Knowledge Base CRUD
- Phase 4 — S3 Integration & Document Upload
- Phase 5 — SQS Integration & Worker Skeleton
- Phase 6 — Text Extraction & Cleaning
- Phase 7 — Chunking Strategy
- Phase 8 — Embeddings & Qdrant Upsert
- Phase 9 — Document Management UI
- Phase 10 — Chat CRUD
- **Phase 11 — Agent Tools & Tool-Calling Provider Abstraction** (NEW, replaces old "Retrieval Pipeline" phase)
- **Phase 12 — Agent Orchestrator (Bounded Loop)** (NEW, the most critical correctness milestone)
- **Phase 13 — Chat Endpoint, Streaming & Frontend Chat UI (Agentic)** (replaces old "LLM Integration" phase)
- Phase 14 — Source Citation Viewer & Polish (now includes agent step-trace UI)
- Phase 15 — Rate Limiting, Security Hardening & Multi-Tenancy + Agent Test Suite (now includes prompt-injection/guardrail adversarial tests)
- Phase 16 — Dockerization & AWS Infrastructure Provisioning
- Phase 17 — CI/CD Pipeline & ECS Deployment
- Phase 18 — Observability (now includes agent iteration/cost/budget-exhausted metrics)
- Phase 19 — Production Readiness Review & MVP Launch

> **Update instruction for future sessions:** When a phase is completed, move it from "Pending" to "Completed" below with the completion date and a one-line note on any deviation from the original plan, then update §13 (Technical Debt) and §12 (Assumptions) if anything changed. For Phases 11–13 specifically, also log the observed average iteration count and budget-exhausted rate from initial testing — this directly informs whether the default guardrail values need tuning.

### Completed Phases (populate as work progresses)
- _None yet._

---

## 12. Important Assumptions

- Single-owner Knowledge Bases in v1 — no shared/team access, so authorization checks (including tool-context construction) only ever need to verify a single `user_id` chain, not a membership table.
- English-language documents are the primary target for MVP; `bge-small-en-v1.5` is an English-optimized model and retrieval quality on other languages is not guaranteed — this affects both direct retrieval and the agent's own query-reformulation quality.
- File size limit defaults to 25MB per document unless changed in configuration; this assumption drives SQS visibility timeout and worker memory sizing (ingestion side, unaffected by the agentic change).
- OpenAI is assumed reachable with standard API latency and to reliably support tool/function calling with streaming; no fallback provider is wired up for MVP even though the abstraction supports one.
- Qdrant is assumed self-hosted on ECS/EC2 for MVP cost reasons, not a managed Qdrant Cloud offering.
- **Agent guardrail defaults** (`max_iterations=4`, `max_wall_clock_ms=20000`) are initial estimates, not empirically tuned — expect these to be revisited after Phase 12/13 real-provider testing and again after Phase 19 load testing, based on observed median iteration count and budget-exhausted rate.
- The agent's toolset is assumed sufficient with just `search_knowledge_base`, `get_document_context`, and `list_documents` for MVP — hybrid search, re-ranking, and cross-KB search are explicitly deferred, not because they're low-value but to keep the orchestrator's correctness surface area manageable for a first agentic release.

---

## 13. Technical Debt

_Populate this section as implementation proceeds. Nothing logged yet since no code exists. Expected likely sources of early technical debt to watch for, specific to the agentic architecture:_

- Collection-per-KB in Qdrant will need a consolidation/sharding strategy once tenant count grows significantly — now additionally relevant because agentic turns can issue up to `max_iterations` searches each, multiplying expected QPS versus a single-pass system (flagged in `architecture.md` §15).
- The custom in-house agent orchestrator (vs. adopting a third-party agent framework) was a deliberate MVP choice for guardrail transparency/testability — revisit if orchestrator maintenance burden grows significantly as more tools/providers are added.
- MVP ships without organization/team workspaces — the `users`/`knowledge_bases` relationship is a hard 1:1 owner model that will require a migration (not just an additive schema change) when team workspaces are introduced; this also affects future per-team agent guardrail/cost-tracking design.
- Redis is introduced early for rate limiting/caching **and** now doubles as the duplicate-query guardrail's lookup store — confirm this dual responsibility doesn't become an operational tangle; consider splitting if it does.
- Agent guardrail defaults are unvalidated assumptions (see §12) — expect at least one tuning pass early in Phase 13/19.

---

## 14. Update Protocol for This File

At the end of every completed phase, an AI session must:

1. Move the phase from "Pending" to "Completed" in §11, with date and any deviation noted.
2. Add any new assumptions surfaced during implementation to §12.
3. Add any shortcuts, known gaps, or deferred cleanup to §13 (Technical Debt).
4. Update §8/§9/§10 if the schema or API surface changed from what's documented in `architecture.md` (and update `architecture.md` itself if the change is significant/permanent).
5. Note any newly introduced dependency or infrastructure component not already listed in §4.
6. **For any phase touching the agent loop or tools:** log observed average/percentile iteration counts, budget-exhausted rate, and any prompt/guardrail tuning changes made, so future sessions understand *why* current defaults are what they are, not just what they are.

This file should always be readable as a stand-alone "catch-up" briefing for a new AI session that has no other context.

---

## 15. Future Improvements (Backlog Pointer)

Full detail in `prd.md` §12 and `phases.md` "Future Phases." Condensed pointer list:

- Additional agent tools: hybrid search (BM25 + vector), cross-encoder re-ranking, cross-Knowledge-Base search, document metadata/filter search.
- Agent self-critique/verification step (draft answer checked against retrieved evidence before finalizing).
- HyDE and query-decomposition as internal agent prompting strategies rather than separate pipeline stages.
- Organization/team workspaces with RBAC.
- Additional LLM providers (Claude, Gemini) with per-KB selection and normalized tool-calling.
- Terraform migration for infrastructure-as-code.
- Billing/subscription tiers, informed by per-query agent cost tracking.
- Audio/video ingestion with transcription.
- User-facing "research depth" preference mapping to different guardrail presets.

---

## 16. Known Constraints

- No synchronous heavy *ingestion* processing is permitted inside the API request path — hard architectural constraint (`rules.md` §17, §21). The agent loop is the one deliberate exception to "no long-running work in the request path," and it is only permitted because it is tightly bounded by guardrails.
- Every LLM/embedding call must go through the provider abstraction — no direct SDK calls anywhere else in the codebase.
- **Qdrant may only be called from inside a registered agent tool's `execute()` method** — this is new and specific to the agentic architecture; no other module in the query path may call Qdrant directly.
- **`knowledge_base_id`/`user_id` are never LLM-controllable tool arguments** — always server-injected via `ToolContext`. This is the single most important security invariant introduced by the agentic redesign.
- The agent loop must always be bounded — every iteration re-checks guardrail state; there is no unbounded code path.
- Cross-tenant data leakage is treated as a Critical-severity risk (`prd.md` §11) — any change touching resource access, **including any new or modified agent tool**, must be accompanied by an authorization test that calls the tool directly, not just through the orchestrator/API.

---

## 17. Things AI Should Always Remember Before Generating Code

1. Read this file and the referenced companion docs before generating code for any new phase.
2. Ingestion and agentic-query pipelines are architecturally separate — SQS is ingestion-only; the agent loop runs synchronously within a single API request, streamed via SSE, and is never queued or resumed.
3. Every new tenant-scoped resource, **and every new or modified agent tool**, needs an authorization test verifying a second user/tenant cannot access it — test tools directly, not only through the orchestrator.
4. Route handlers are thin; logic goes in `services/` or the agent orchestrator; DB access goes in `repositories/`; LLM/embedding calls go through `providers/`; Qdrant is called only from inside a tool.
5. `knowledge_base_id`/`user_id` are always server-injected into `ToolContext` — never accept them as LLM-supplied tool arguments, and never let retrieved document content be treated as instructions rather than untrusted reference data.
6. Every agent loop iteration must re-check `max_iterations`/`max_wall_clock_ms`/`max_tokens_per_turn` before proceeding — no exceptions, no unbounded paths.
7. Use the typed settings object for configuration, including all agent guardrail values — never scatter `os.environ.get()` calls or hardcode guardrail numbers.
8. Follow the exact schema in `architecture.md` §10 (including `agent_steps`) — do not invent new tables/columns without updating that document first.
9. Follow Conventional Commits and the branch naming convention tied to the current phase in `phases.md`.
10. Update this file (`memory.md`) at the end of the phase you just completed, per §14 above — and for agent-related phases, log observed iteration/budget-exhausted metrics.