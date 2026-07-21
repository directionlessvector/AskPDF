# rules.md — AskPDF AI

**Engineering Rules for AI-Assisted Development**
**Version:** 2.0 — Agentic RAG

These rules are binding for all code generated in this project, whether written by a human or an AI coding assistant. When in doubt, prefer the stricter interpretation. This document is the contract that keeps iterative "vibe coding" sessions consistent with each other.

---

## 1. Architecture Rules

- The system is composed of three deployable units: `apps/web` (frontend), `apps/api` (FastAPI, including the Agent Orchestrator), `apps/worker` (ingestion worker). Do not merge their responsibilities.
- The **ingestion pipeline** (worker) and **agentic query pipeline** (API/agent) must never share a request-time code path. The worker never serves HTTP; the API never performs SQS polling; SQS is used exclusively for ingestion, never for agent turns.
- The agent loop is **synchronous within a single API request**, streamed to the client via SSE. It must never be queued, deferred, or split across multiple HTTP requests — a single user turn is one bounded loop, start to finish, within one request lifecycle.
- All cross-service communication between API and Worker happens via: (1) SQS messages, (2) shared PostgreSQL state, (3) shared Qdrant state. No direct HTTP calls between API and Worker.
- Business logic lives in a `services/` layer. API route handlers (`api/v1/*.py`) must be thin: parse request → call service (or the agent orchestrator) → return/stream response. No SQL or business rules inside route handlers.
- Data access lives in a `repositories/` layer. Services never construct raw SQL/ORM queries inline — they call repository methods.
- LLM and embedding calls must always go through the `providers/` abstraction (`LLMProvider`, `EmbeddingProvider` interfaces), including tool/function-calling. No direct `openai.*` or `sentence_transformers.*` calls outside a provider implementation.
- **Agent tools are the only code path allowed to call Qdrant during a query.** No other module (route handler, service) invokes Qdrant directly for a chat/query — retrieval is exclusively a tool the orchestrator calls, never an inline pipeline step.
- The agent orchestrator (`agent/orchestrator.py`) is the **only** place the bounded loop logic lives. Do not duplicate iteration/guardrail logic elsewhere (e.g., inside a route handler or a tool itself).

---

## 2. Folder Structure Rules

- Follow the structure defined in `architecture.md` §13 exactly. Do not introduce ad-hoc top-level folders without updating that document.
- Every new API resource gets: a model (`models/`), a schema (`schemas/`), a repository (`repositories/`), a service (`services/`), and a route module (`api/v1/`). No skipping layers "for speed."
- Every new agent tool gets: a Pydantic args schema, an implementation in `agent/tools/`, and a registration entry in the orchestrator's tool registry. A tool is never wired directly into a route handler or service — only the orchestrator invokes tools.
- Frontend components are organized by domain (`components/chat/`, `components/documents/`, `components/knowledge-base/`), not by component type. Only generic, reusable primitives live in `components/ui/`. Agent-specific chat UI (step trace, live activity row) lives under `components/chat/`, not a separate top-level folder.
- Tests mirror source structure: `tests/services/test_document_service.py` tests `services/document_service.py`; `tests/agent/tools/test_search_knowledge_base.py` tests the corresponding tool; `tests/agent/test_orchestrator.py` tests the loop itself.

---

## 3. Naming Conventions

- **Python:** `snake_case` for functions/variables/modules, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- **TypeScript/React:** `camelCase` for functions/variables, `PascalCase` for components and types/interfaces, `kebab-case` for file names of non-component modules, `PascalCase.tsx` for component files.
- **Database:** table names plural snake_case (`knowledge_bases`, `agent_steps`), column names snake_case, foreign keys named `{referenced_table_singular}_id` (e.g., `knowledge_base_id`, `message_id`).
- **API routes:** plural nouns, kebab-case where multi-word (`/knowledge-bases`, `/documents`, `/chats/{chat_id}/messages`).
- **Agent tool names:** `snake_case`, verb-first, matching the LLM-facing function name exactly (e.g., `search_knowledge_base`, `get_document_context`, `list_documents`) — the tool's registered name, its Python module name, and its class/function name should all be trivially derivable from each other.
- **SQS messages:** payload keys snake_case, message type identified by a required `type` field (e.g., `"type": "document.ingest"`). SQS is never used for agent-related message types.
- **SSE event names (agent endpoint):** `agent_step`, `token`, `done`, `error` — fixed, documented set; do not introduce ad-hoc event names without updating `architecture.md` §5 and the frontend consumer together.
- **Environment variables:** `UPPER_SNAKE_CASE`, prefixed by service where ambiguous (`API_JWT_SECRET`, `WORKER_SQS_QUEUE_URL`, `AGENT_MAX_ITERATIONS`).

---

## 4. Code Style

### 4.1 Python Conventions
- Formatter: `black`. Linter: `ruff`. Type checker: `mypy` (strict mode for `services/`, `repositories/`, and `agent/`; relaxed for `tests/`).
- All function signatures must have type hints, including return types.
- Use Pydantic models for all API request/response schemas, all agent tool argument schemas, and all tool result schemas — never return raw dicts or ORM objects directly from route handlers or tools.
- Prefer `async def` for all I/O-bound code (DB, S3, SQS, HTTP calls to LLM providers, Qdrant calls inside tools). Use `asyncpg`/async SQLAlchemy session, async boto3 (`aioboto3`) or thread-pooled sync boto3 wrapped explicitly — never block the event loop with a sync call, and especially never block it during an agent loop, since a blocked loop directly inflates `max_wall_clock_ms` consumption for the user.
- Use dependency injection via FastAPI's `Depends()` for DB sessions, current user, and provider instances — never instantiate a DB session or provider directly inside a route handler.
- Custom exceptions live in `core/exceptions.py` and map to HTTP status codes via a centralized exception handler — no ad-hoc `HTTPException` construction scattered through services. Agent-specific exceptions (`ToolExecutionError`, `AgentBudgetExhaustedError`, `UnknownToolError`) live in `agent/exceptions.py` and are handled *within the orchestrator loop*, never allowed to propagate as an unhandled 500 to the client.

### 4.2 TypeScript Conventions
- Strict mode enabled in `tsconfig.json` (`strict: true`). No `any` without an explicit `// eslint-disable-next-line` justification comment.
- All API responses are typed via shared types generated or hand-maintained in `types/` — no untyped `fetch`/SSE responses consumed directly in components. This includes typed discriminated unions for the three SSE event types (`agent_step`, `token`, `done`/`error`).
- Server state (KBs, documents, chats, messages) is managed exclusively via TanStack Query. Do not duplicate server state into local `useState`. In-flight streaming state (the currently-arriving tokens and live agent-step text of an active turn) is the one deliberate exception — it is transient UI state, not cached server state, and lives in local component state until the turn completes and is persisted/refetched.
- Client-only UI state (form inputs, modal open/close, drag state, step-trace expand/collapse) uses local `useState`/`useReducer`. No global client-state library (Redux/Zustand) unless a documented need arises.
- Components are function components with explicit prop interfaces (`interface ChatMessageProps { ... }`), never inline anonymous prop types for anything reused more than once.

---

## 5. API Conventions

- All routes versioned under `/api/v1/`.
- Every authenticated route depends on a `get_current_user` dependency; no manual token parsing inside individual handlers.
- Every resource-scoped route (KB, document, chat, message) verifies ownership through the full chain before returning data (e.g., a chat lookup verifies `chat.knowledge_base.user_id == current_user.id`, not just `chat.user_id`). The agent endpoint performs this same ownership check **before** starting the orchestrator loop — the orchestrator itself receives an already-authorized `ToolContext`, never a raw chat/KB ID it must re-verify.
- Pagination: list endpoints accept `limit`/`offset` (or cursor-based for `messages`), default `limit=20`, max `limit=100`.
- Errors return a consistent JSON shape: `{"error": {"code": "string", "message": "human-readable", "details": {...}}}`.
- The agentic chat endpoint (`POST /chats/{id}/messages`) uses `text/event-stream` with the fixed named SSE events defined in §3 (`agent_step`, `token`, `done`, `error`). `agent_step` events carry `{iteration, tool_name, status: "started"|"completed", query_summary}` — never raw tool result content (that stays server-side until the final answer/citations are persisted and fetched normally).
- All mutating endpoints (`POST`/`PATCH`/`DELETE`) are idempotent where feasible (e.g., delete on an already-deleted resource returns 404, not 500). A retried chat turn (e.g., after a dropped connection) always starts a **fresh** agent loop rather than attempting to resume a partial one — the agent loop has no resumable state by design (see `architecture.md` §22).

---

## 6. Database Conventions

- All tables have `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `created_at TIMESTAMPTZ DEFAULT now()`, and `updated_at TIMESTAMPTZ` (auto-updated via trigger or ORM `onupdate`) where applicable (`agent_steps` is append-only and does not need `updated_at`).
- All foreign keys declared with `ON DELETE CASCADE` where the child record has no meaning without the parent (per `architecture.md` §10) — this includes `agent_steps.message_id → messages.id`.
- No business logic in database triggers/functions beyond `updated_at` maintenance — logic belongs in the service/agent layer for testability.
- Every migration is generated via Alembic (`alembic revision --autogenerate`) and manually reviewed before commit — never hand-edit the database schema outside a migration.
- Migrations must be reversible (`downgrade()` implemented, not `pass`), except where explicitly justified in a comment.
- No `SELECT *` in application code — always specify columns or use the ORM model explicitly.
- `agent_steps.tool_args` and `agent_steps.result_summary` are `JSONB`, not free text — always written as structured, schema-validated data (the same Pydantic models used for the tool call itself), never string-formatted debug output.

---

## 7. Git Conventions

- **Branch strategy:** `main` is always deployable. Feature branches named `feat/<short-description>`, fixes `fix/<short-description>`, chores `chore/<short-description>`, infra `infra/<short-description>`, releases `release/vX.Y.Z` — matching the branch names specified per phase in `phases.md`.
- Direct commits to `main` are not allowed; all changes land via pull request.
- Each PR should correspond to one phase (or a clearly scoped sub-slice of a phase) from `phases.md` — avoid PRs that span unrelated concerns. The agent orchestrator (Phase 12) is large enough that it should be built via multiple small, reviewable PRs against a shared `feat/agent-orchestrator` branch rather than a single giant PR.
- Rebase (not merge commits) to keep feature branches up to date with `main` where practical; squash-merge into `main` to keep history linear.

## 8. Commit Conventions

- Follow **Conventional Commits**: `type(scope): description`.
  - Types: `feat`, `fix`, `chore`, `refactor`, `test`, `docs`, `infra`, `perf`.
  - Example: `feat(agent): add duplicate-query guardrail to orchestrator loop`.
- Commits should be small and logically atomic (per the "Recommended Commit Strategy" in each `phases.md` entry) — not one giant commit per phase.
- Never commit secrets, `.env` files, or credentials, including LLM provider API keys used for manual agent testing. `.env.example` files only, with placeholder values.

---

## 9. Testing Requirements

- Every service-layer function has at least one unit test covering the happy path and at least one covering a failure/edge case.
- Every authenticated/tenant-scoped endpoint has an authorization test verifying a second user cannot access it, **including agent tool calls tested in isolation** (calling a tool function directly with another tenant's KB context must be provably impossible/rejected).
- Every agent tool has unit tests independent of the orchestrator (seeded Qdrant collection, direct function call, assert correct scoping/results).
- The agent orchestrator has a dedicated test suite using a **mock/scripted LLM provider** (deterministic, no real API cost) covering: single-iteration happy path, multi-iteration happy path, no-results-found path, duplicate-query short-circuiting, forced termination on `max_iterations`, forced termination on `max_wall_clock_ms`, malformed tool-call arguments, and a hallucinated/unregistered tool name. These tests must run in CI without any real LLM API key.
- A smaller, separately-tagged suite of tests against the **real** LLM provider (requires an API key, run manually or on a schedule, not on every PR) validates realistic tool-calling behavior and prompt effectiveness — these are not required to pass for merge but should be run before major prompt/orchestrator changes ship.
- Ingestion pipeline stages (extract/clean/chunk/embed) are tested independently with fixture files, in addition to an end-to-end integration test.
- Frontend: components with conditional rendering (loading/empty/error states, including agent live-activity and budget-exhausted states) have tests covering each state.
- Minimum coverage target: 80% for `services/`, `repositories/`, and `agent/` layers in the API and Worker; UI coverage is judged by critical-path coverage (auth, upload, chat, agent step-trace) rather than a blanket percentage.
- No PR merges with failing tests or reduced coverage on touched files without explicit justification in the PR description.

---

## 10. Logging Requirements

- Use structured logging (`structlog` or equivalent JSON logger) — never bare `print()` statements in `apps/api` or `apps/worker`.
- Every log entry includes `request_id` (API) or `message_id`/`document_id` (worker) for correlation, per `architecture.md` §19. Agent-loop log entries additionally include `chat_id`, `message_id`, and `iteration`.
- Log levels used deliberately: `DEBUG` for verbose diagnostic detail (never enabled in production by default), `INFO` for normal lifecycle events (including each agent tool call's query text and result count), `WARNING` for recoverable issues (e.g., a tool call failed but the agent continued), `ERROR` for failures requiring attention (e.g., the agent loop terminated abnormally).
- Never log raw document content, full prompts, or user passwords/tokens at any level in production. Agent tool-call **query text** (LLM-generated) may be logged at INFO since it does not itself contain document content, but the **retrieved chunk content** returned by a tool call must not be logged at INFO — only a redacted summary (chunk_id, score, character count) is appropriate at INFO; full content is DEBUG-only and gated behind a feature flag.

---

## 11. Error Handling

- All external calls (S3, SQS, Qdrant, LLM provider, embedding provider) are wrapped in explicit try/except with typed exceptions — no bare `except Exception: pass`.
- User-facing errors are always human-readable and never leak internal stack traces, SQL, or provider-specific error payloads.
- Worker pipeline stage failures set a specific `error_reason` on the `documents` row (e.g., `"unsupported_encoding"`, `"corrupt_pdf"`, `"embedding_provider_timeout"`) rather than a generic "processing failed."
- **Agent tool execution failures never crash the request.** A failing tool call is caught inside the orchestrator and converted into a structured error observation returned to the LLM as that tool call's result (per `architecture.md` §21) — the LLM, not the orchestrator, decides how to proceed, still bounded by the overall guardrails.
- **Agent guardrail breaches (`max_iterations`, `max_wall_clock_ms`, `max_tokens_per_turn`) are not exceptions to catch-and-500 — they are an expected, handled control-flow path** that produces a valid (if flagged) final answer. `AgentBudgetExhaustedError` (if used internally) must always be caught within the orchestrator and never surface as an unhandled 500.
- Retries follow `architecture.md` §22 exactly: exponential backoff with jitter for transient external-API failures, no retry for permanent/validation failures. A single LLM-call-level retry inside the agent loop does not consume an iteration (see `architecture.md` §22), and this distinction must be reflected precisely in the orchestrator's iteration-counting code — do not conflate "HTTP retry of one LLM call" with "one more round of the agent loop."

---

## 12. Dependency Injection

- FastAPI `Depends()` is the sole DI mechanism for the API service: DB sessions, current user, provider instances (`LLMProvider`, `EmbeddingProvider`), and configuration are all injected, never imported as global singletons directly into route handlers.
- The agent orchestrator receives its dependencies (LLM provider, tool registry, guardrail config, repository instances for persistence) via constructor/function injection from the route handler — it never reaches into a global registry or re-instantiates providers itself.
- Agent tools receive a `ToolContext` (containing `knowledge_base_id`, `user_id`, and injected repository/Qdrant client instances) at execution time — a tool never constructs its own DB session, Qdrant client, or embedding provider; all are passed in.
- The Worker Service uses a lightweight composition-root pattern: a single `main.py` wires up concrete provider/repository instances and passes them into pipeline functions — pipeline functions accept interfaces, not concrete classes, so they remain independently testable with mocks.
- Provider interfaces (`LLMProvider`, `EmbeddingProvider`) are defined as abstract base classes / `Protocol`s in `providers/base.py`, including the tool-calling contract; concrete implementations (`OpenAIProvider`, `BGEEmbeddingProvider`) live alongside and are swapped via configuration, never via code branching (`if provider == "openai"` scattered through business logic).
- Agent tools implement a shared `Tool` `Protocol` (`name`, `description`, `args_schema`, `async def execute(args, context) -> ToolResult`) so the orchestrator's tool registry can treat every tool identically — adding a new tool must never require orchestrator code changes beyond a registry entry.

---

## 13. Configuration Management

- All configuration loaded via a single typed settings object per service (`core/config.py` using `pydantic-settings`), sourced from environment variables — no scattered `os.environ.get()` calls throughout the codebase.
- Agent guardrail values (`max_iterations`, `max_wall_clock_ms`, `max_tokens_per_turn`, `top_k` default/max, duplicate-query similarity threshold) are all part of this typed settings object — never magic numbers inline in `agent/orchestrator.py` or `agent/guardrails.py`.
- Configuration is validated at service startup; the service fails fast with a clear error if required config is missing, rather than failing later mid-request (this includes validating that `AGENT_MAX_ITERATIONS` is a sane positive integer, etc.).
- Frontend configuration (API base URL, feature flags) uses Next.js public env vars (`NEXT_PUBLIC_*`) explicitly and only for genuinely public values — never expose secrets via `NEXT_PUBLIC_*`.

---

## 14. Environment Variables

- Every service ships a `.env.example` listing all required variables with placeholder/dummy values and a one-line comment explaining each.
- Required variables (non-exhaustive, expand as needed):
  - API: `DATABASE_URL`, `JWT_SECRET`, `JWT_ALGORITHM`, `ACCESS_TOKEN_TTL_MINUTES`, `REFRESH_TOKEN_TTL_DAYS`, `QDRANT_URL`, `S3_BUCKET_NAME`, `SQS_INGESTION_QUEUE_URL`, `OPENAI_API_KEY`, `EMBEDDING_MODEL_NAME`, `REDIS_URL`, `AGENT_MAX_ITERATIONS`, `AGENT_MAX_WALL_CLOCK_MS`, `AGENT_MAX_TOKENS_PER_TURN`, `AGENT_SEARCH_TOP_K_DEFAULT`, `AGENT_SEARCH_TOP_K_MAX`, `AGENT_DUPLICATE_QUERY_SIMILARITY_THRESHOLD`.
  - Worker: `DATABASE_URL`, `QDRANT_URL`, `S3_BUCKET_NAME`, `SQS_INGESTION_QUEUE_URL`, `EMBEDDING_MODEL_NAME`.
  - Web: `NEXT_PUBLIC_API_BASE_URL`.
- In production, all secret-valued variables are sourced from AWS Secrets Manager via ECS task definition secret injection — never baked into Docker images or committed to the repo. Guardrail *tuning* values (non-secret) may be plain ECS task-definition environment variables.

---

## 15. Docker Rules

- Every service (`web`, `api`, `worker`) has its own multi-stage `Dockerfile`: a build stage (installs dependencies, compiles/builds) and a slim runtime stage (copies only build artifacts + runtime dependencies).
- Base images pinned to specific versions (e.g., `python:3.12-slim`, `node:20-alpine`) — never `latest`.
- Containers run as a non-root user in the runtime stage.
- `.dockerignore` excludes `node_modules`, `__pycache__`, `.git`, `.env`, test fixtures, and local dev artifacts.
- Local development uses `docker-compose.yml` with hot-reload volumes; production images are immutable builds with no bind mounts.
- The API service's ECS task definition must size CPU/memory and connection/timeout limits accounting for agent turns holding a request open longer than a single-pass system (multiple internal LLM/Qdrant round trips) — this must be documented explicitly in `infra/ecs/README.md`, not left implicit.

---

## 16. Security Rules

- Passwords hashed with `argon2` (preferred) or `bcrypt` — never stored in plaintext or reversible encryption.
- JWTs signed with a secret/key of sufficient length (256-bit minimum for HS256); signing key never logged or exposed via any API response.
- Every DB query touching tenant-owned data includes an explicit ownership filter — enforced via code review checklist (§21) and the automated isolation test suite (per `phases.md` Phase 15).
- **`knowledge_base_id` and `user_id` are never accepted as LLM-supplied tool-call arguments.** They are injected into `ToolContext` by the orchestrator from the already-authenticated, already-authorized request — this is a hard architectural rule (`architecture.md` §16), not a convention, and must be enforced by the `Tool` Protocol's signature itself (tool `execute()` methods take `args` from the LLM and `context` from the orchestrator as clearly separate parameters, never merged into one dict the LLM could pollute).
- Retrieved document content injected into the agent's prompt context is treated as **untrusted data**, not instructions — the system prompt must explicitly state this, and the orchestrator must never execute a tool call, follow an instruction, or alter its guardrail behavior based on content found inside retrieved chunks (defense against prompt injection embedded in uploaded documents).
- The orchestrator's tool registry is a fixed allow-list constructed at startup — it never dynamically registers a tool based on runtime/LLM input.
- File uploads validated by both extension and content-type/magic-byte sniffing (not filename alone) before being accepted.
- All outbound requests to LLM/embedding providers use HTTPS with certificate validation enabled (never disable TLS verification, including in tests against real providers).
- Dependency vulnerabilities are scanned in CI (`pip-audit`, `npm audit`, `trivy` for images) and block merge on high/critical findings without an explicit documented exception.

---

## 17. Performance Rules

- No synchronous, long-running work (file parsing, embedding generation) inside an API request handler outside the bounded agent loop itself — heavy ingestion work belongs in the Worker Service, triggered via SQS.
- The agent loop's guardrails (§13 config) exist specifically to bound performance/cost — any change to `max_iterations` or `max_wall_clock_ms` defaults must be accompanied by a note on the expected p95 latency/cost impact.
- Batch embedding calls where possible (embed a document's chunks in batches at ingestion time, not one HTTP/model call per chunk). A single `search_knowledge_base` tool call embeds only the one query string it was given — no batching needed there, but the orchestrator should reuse a warm embedding-model instance across iterations within a turn rather than reloading it per call.
- Qdrant queries (inside tools) always specify a `limit` and appropriate payload filters — never an unbounded scan.
- The tool-result cache (`architecture.md` §18) should be checked before executing a `search_knowledge_base` call whose query text is near-identical to a prior call in the same turn — this is both a performance optimization and the mechanism behind the duplicate-query guardrail; do not implement these as two separate, potentially inconsistent code paths.
- Frontend: paginate/virtualize long lists (chat history, document lists) rather than rendering unbounded DOM nodes.
- Streaming responses must begin flushing `agent_step` events to the client as soon as the first tool call starts, and `token` events as soon as the LLM begins producing final text — no server-side buffering of the full response before sending.

---

## 18. Documentation Rules

- Every service has a `README.md` covering: purpose, local setup, environment variables, how to run tests.
- Every non-trivial service/repository/agent function has a docstring (Python) or JSDoc comment (TypeScript) explaining purpose, parameters, and return value — not restating the obvious, but clarifying intent and edge cases. Every agent tool's docstring must also document its `args_schema` fields in the exact language that will be shown to the LLM as the tool description, since this text directly shapes model behavior.
- API endpoints are documented via FastAPI's automatic OpenAPI generation — route handlers must have clear `summary`/`description` and response models so `/docs` stays useful without extra effort. The SSE event contract for the agentic chat endpoint is documented explicitly in prose (OpenAPI doesn't natively describe SSE event streams well) in that endpoint's docstring and in `architecture.md` §5.
- `memory.md` must be updated at the end of every phase (see `memory.md` itself for the update protocol).

---

## 19. RAG & Agent Implementation Rules

- Embedding model version is recorded per Qdrant point (`embedding_model_version` payload field) and per Knowledge Base — retrieval (via any tool call) must never mix vectors generated by different model versions within a single search without an explicit, deliberate re-indexing migration.
- Chunk size and overlap are configuration-driven constants, not magic numbers scattered across the codebase — defined once in `core/config.py` (or `pipeline/config.py` in the worker) and referenced everywhere.
- The `search_knowledge_base` tool always filters by the server-injected `knowledge_base_id` (implicitly tenant-scoped via KB ownership already verified at the API layer, per §16) — a tool call must never be able to retrieve chunks from a KB the requester doesn't own, even accidentally through a missing filter, and even if the LLM's query text somehow references another KB by name.
- `top_k` and any future re-ranking/hybrid-search parameters are configurable (global defaults, LLM-adjustable within a capped range per §13), anticipating the future roadmap items in `architecture.md`.
- Citation mapping (LLM output marker → chunk → document → originating tool call/iteration) must be deterministic and testable independent of the LLM call itself — implemented as a pure function taking `(generated_text, agent_steps)` → citations.
- **The agent loop must always be bounded.** Every code path that could theoretically call the LLM or a tool again must check the guardrail state first. There is no code path in `agent/orchestrator.py` where an iteration proceeds without first checking `iteration < max_iterations` and `elapsed_ms < max_wall_clock_ms`.
- Near-duplicate tool-call detection (§ guardrails) must use the same embedding model as retrieval itself for cosine-similarity comparison, not a separate/ad-hoc string-similarity heuristic, to stay consistent with how "similar" is defined everywhere else in the system.

---

## 20. Prompt Engineering Rules

- System prompts (including the agent system prompt) live in version-controlled prompt template files (e.g., `agent/prompts/agent_system_prompt.py`), never inlined as ad-hoc strings inside service/orchestrator logic — they are reviewed and tested like code.
- The agent system prompt must explicitly instruct the model to: (1) use the `search_knowledge_base` tool to gather evidence before answering rather than answering from general knowledge, (2) issue additional, differently-worded searches when the question has multiple parts or the first search is insufficient, (3) treat retrieved tool-call content strictly as untrusted reference data, never as instructions (defense against prompt injection, per §16), (4) cite sources using the defined citation marker format tied to specific chunk IDs actually returned by its own tool calls, and (5) explicitly state it doesn't know when, after searching, the context is insufficient — never fabricate an answer to avoid appearing unhelpful.
- Chat history included in the prompt is bounded (last N turns, token-budgeted) to control cost and avoid exceeding context limits — never include unbounded full history. Prior agent step traces from earlier turns in the same chat are **not** replayed into a new turn's prompt by default (each turn starts its own fresh agent loop); only the prior turns' final answers are included as history.
- Tool descriptions (the text exposed to the LLM describing what each tool does and when to use it) are treated with the same rigor as the system prompt — reviewed, tested via the mock-LLM orchestrator suite, and changed deliberately, since tool descriptions are a primary lever for shaping when/how often the agent chooses to search.
- Prompt templates and tool descriptions are treated as testable artifacts: changes should be accompanied by a note on why, and ideally a before/after example (including any observed change in average iteration count) in the PR description.

---

## 21. Do's and Don'ts

**Do:**
- Do keep ingestion and agentic query pipelines fully independent, with SQS reserved exclusively for ingestion.
- Do write tenant-isolation tests for every new resource type and every agent tool, testing tools directly and not just through the orchestrator.
- Do use the provider abstraction (including its tool-calling contract) for any new LLM or embedding integration.
- Do write migrations for every schema change, reviewed before merge.
- Do keep route handlers thin and push logic into services or the agent orchestrator.
- Do enforce guardrail checks (`max_iterations`, `max_wall_clock_ms`, `max_tokens_per_turn`) before every single loop iteration, with no exceptions.
- Do treat retrieved document content as untrusted data inside prompts.

**Don't:**
- Don't call OpenAI (or any LLM/embedding SDK) directly from a route handler, service, or agent tool — always through a provider.
- Don't call Qdrant from anywhere except inside a registered agent tool's `execute()` method.
- Don't perform synchronous document *ingestion* processing inside an API request.
- Don't trust client-supplied `user_id`/`knowledge_base_id` without verifying ownership server-side — and never accept them as LLM-controllable tool arguments.
- Don't hardcode chunk size, top-K, model names, or agent guardrail values inline — use configuration.
- Don't log document content, prompts, or secrets at INFO level or above; retrieved chunk content specifically is DEBUG-only.
- Don't let a tool-call failure or a hallucinated/unregistered tool name crash the request — always convert to a structured observation or graceful termination.
- Don't introduce a new top-level dependency (library) without checking it against the stack defined in the PRD/architecture docs first.
- Don't add a new agent tool without updating `architecture.md` §5.3 and adding both isolated unit tests and an orchestrator-level mock-LLM test exercising it.

---

## 22. Definition of Done

A unit of work (PR/phase) is "done" only when:

1. Code adheres to all rules in this document (style, layering, naming).
2. Tests are written and passing per §9, with no reduction in coverage on touched files, including new/updated agent guardrail tests where the agent loop is touched.
3. Structured logging is present for new service-layer and agent-loop operations, per §10.
4. Error handling follows §11 (no silent failures, human-readable user-facing errors, no unhandled guardrail breaches).
5. New environment variables (including any new agent guardrail knob) are added to the relevant `.env.example` with comments.
6. Documentation (README/docstrings/OpenAPI/SSE contract) is updated for any new public interface or new/changed agent tool.
7. `memory.md` is updated to reflect the new implementation status.
8. The relevant phase's "Completion Criteria" in `phases.md` is satisfied.
9. No secrets, debug prints, or commented-out dead code remain in the diff.

---

## 23. Code Review Checklist

- [ ] Does this change respect the ingestion/agentic-query pipeline separation (SQS never touched by the agent path)?
- [ ] Are all new tenant-scoped queries, including any agent tool call, filtered by ownership (not just presence of an ID)?
- [ ] Are route handlers thin, with logic in `services/` or the agent orchestrator?
- [ ] Are DB queries going through `repositories/`, not inlined in services or tools?
- [ ] Are LLM/embedding calls going through the `providers/` abstraction, including tool-calling?
- [ ] Is Qdrant only ever called from inside a registered agent tool's `execute()`?
- [ ] Does every new/changed agent loop code path re-check the guardrail state (`max_iterations`, `max_wall_clock_ms`, `max_tokens_per_turn`) before proceeding?
- [ ] Are `knowledge_base_id`/`user_id` strictly server-injected into `ToolContext`, never accepted as LLM-supplied tool arguments?
- [ ] Is retrieved document content treated as untrusted data in any prompt construction touched by this change?
- [ ] Are new config values (including agent guardrails) added via the typed settings object, not `os.environ` directly?
- [ ] Are secrets absent from the diff (`.env`, hardcoded keys, tokens)?
- [ ] Do new endpoints have request/response Pydantic schemas and OpenAPI docs (and, for the agent endpoint, an updated SSE event contract if changed)?
- [ ] Are error responses consistent with the shape defined in §5, and are tool/guardrail failures handled gracefully rather than surfaced as 500s?
- [ ] Are new frontend components typed, with loading/empty/error states (including agent live-activity, step-trace, and budget-exhausted states) handled per `design.md`?
- [ ] Are tests included and passing, covering both happy path and at least one failure case, including mock-LLM orchestrator tests for any orchestrator/tool change?
- [ ] Is structured logging present with correct correlation IDs, including `chat_id`/`message_id`/`iteration` for agent-loop changes?
- [ ] Does the commit history follow Conventional Commits and match the phase's recommended strategy?
- [ ] Has `memory.md` been updated if this PR completes or advances a phase?