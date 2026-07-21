# phases.md — AskPDF AI

**Implementation Phases**
**Version:** 2.0 — Agentic RAG

This document breaks the build into sequential, independently completable phases for iterative AI-assisted development ("vibe coding"). Each phase is scoped so it can be implemented, tested, and committed as a coherent unit before moving to the next. Phases 0–10 are unchanged from a classic-RAG build; **Phases 11–13 are restructured around the agent loop**.

---

## Phase 0 — Project Setup & Foundations

- **Goal:** Establish the monorepo, tooling, and baseline CI so every subsequent phase has a working skeleton to build on.
- **Deliverables:** Monorepo structure (`apps/web`, `apps/api`, `apps/worker`), Docker Compose for local dev (Postgres, Qdrant, LocalStack for S3/SQS), base FastAPI app with `/health`, base Next.js app with Tailwind/shadcn installed, linting/formatting configs (ESLint, Prettier, Ruff, Black, mypy).
- **Features:** None user-facing yet.
- **Learning Objectives:** Establish conventions before any business logic exists.
- **Milestone:** `docker compose up` boots all services locally; `/health` returns 200; frontend renders a placeholder page.
- **Completion Criteria:** CI pipeline runs lint + type-check on push; all services build successfully in Docker.
- **Dependencies:** None.
- **Estimated Complexity:** Low.
- **Recommended Git Branch:** `chore/project-setup`
- **Recommended Commit Strategy:** Small commits per tool (`chore: add fastapi skeleton`, `chore: add nextjs skeleton`, `chore: docker compose local env`).
- **Testing Strategy:** Smoke test only (`/health` returns 200); CI runs lint/type-check.
- **Deployment Milestone:** None (local only).

---

## Phase 1 — Database Schema & Migrations

- **Goal:** Define the full PostgreSQL schema described in `architecture.md` §10 — including the `agent_steps` table — and wire up ORM + migrations.
- **Deliverables:** SQLAlchemy models for `users`, `knowledge_bases`, `documents`, `chunks`, `chats`, `messages`, `agent_steps`; Alembic migration setup and initial migration.
- **Features:** None user-facing yet.
- **Learning Objectives:** Get the data model right before building endpoints against it, including the agent-traceability schema up front so later phases don't require a retrofit migration.
- **Milestone:** `alembic upgrade head` creates all tables correctly against local Postgres.
- **Completion Criteria:** Schema matches `architecture.md` §10 exactly, including `messages.agent_iteration_count`, `messages.agent_budget_exhausted`, and the full `agent_steps` table; foreign keys and cascade rules verified with a manual test insert/delete.
- **Dependencies:** Phase 0.
- **Estimated Complexity:** Low-Medium.
- **Recommended Git Branch:** `feat/db-schema`
- **Recommended Commit Strategy:** One commit per model, one commit for the migration.
- **Testing Strategy:** Unit tests for model constraints; integration test verifying cascade deletes (including `agent_steps` cascading from `messages`).
- **Deployment Milestone:** None (local only).

---

## Phase 2 — Authentication (Register/Login/JWT)

- **Goal:** Implement email/password auth with JWT access + refresh tokens, OAuth-ready schema.
- **Deliverables:** `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout` endpoints; password hashing (argon2); JWT issuing/validation middleware; frontend login/register pages.
- **Features:** Users can sign up and log in from the UI.
- **Learning Objectives:** Establish the security foundation all other resources depend on.
- **Milestone:** A user can register via the UI, log in, and reach a protected dashboard route.
- **Completion Criteria:** Invalid credentials rejected; expired/invalid JWTs rejected with 401; refresh flow rotates tokens correctly.
- **Dependencies:** Phase 1.
- **Estimated Complexity:** Medium.
- **Recommended Git Branch:** `feat/authentication`
- **Recommended Commit Strategy:** Backend auth endpoints → JWT middleware → frontend auth pages → protected route guard, as separate commits.
- **Testing Strategy:** Unit tests for password hashing and token generation/validation; integration tests for full register→login→access-protected-route flow.
- **Deployment Milestone:** None (local only).

---

## Phase 3 — Knowledge Base CRUD

- **Goal:** Allow authenticated users to create, list, rename, and delete Knowledge Bases.
- **Deliverables:** `/kb` CRUD endpoints; ownership authorization checks; frontend KB list/dashboard page; create/rename/delete UI with confirmation dialogs.
- **Features:** Users can manage Knowledge Bases end-to-end.
- **Learning Objectives:** Establish the tenant-scoping pattern (`WHERE user_id = current_user`) reused everywhere else, including later inside agent tool implementations.
- **Milestone:** A logged-in user can create a KB, see it in a list, rename it, and delete it.
- **Completion Criteria:** User A cannot read/modify/delete User B's KB (verified by test); cascade delete stub in place (full cascade completed once documents/chats exist).
- **Dependencies:** Phase 2.
- **Estimated Complexity:** Low-Medium.
- **Recommended Git Branch:** `feat/knowledge-base-crud`
- **Recommended Commit Strategy:** API endpoints, then repository/service layer, then frontend pages as separate commits.
- **Testing Strategy:** Unit tests for service layer; integration tests for authorization boundaries; frontend component tests for CRUD UI.
- **Deployment Milestone:** None (local only).

---

## Phase 4 — S3 Integration & Document Upload (Metadata Only)

- **Goal:** Enable file upload to S3 and creation of `documents` rows with `PENDING` status, without processing yet.
- **Deliverables:** S3 client wrapper (or LocalStack locally); `/kb/{id}/documents` upload endpoint (multipart or presigned URL flow); file type/size validation; frontend upload UI with drag-and-drop and progress bar.
- **Features:** Users can upload PDF/DOCX/TXT/MD files to a KB and see them listed with `PENDING` status.
- **Learning Objectives:** Establish the upload contract before building the async pipeline that consumes it.
- **Milestone:** Uploading a file results in an S3 object and a `documents` row with correct metadata.
- **Completion Criteria:** Unsupported file types rejected client- and server-side; oversized files rejected with a clear error.
- **Dependencies:** Phase 3.
- **Estimated Complexity:** Medium.
- **Recommended Git Branch:** `feat/document-upload`
- **Recommended Commit Strategy:** S3 client → upload endpoint → validation → frontend upload UI.
- **Testing Strategy:** Integration tests against LocalStack S3; frontend tests for validation and progress states.
- **Deployment Milestone:** None (local only).

---

## Phase 5 — SQS Integration & Worker Service Skeleton

- **Goal:** Publish an ingestion job to SQS on upload and stand up a Worker Service that consumes it (no processing logic yet, just status transition to `PROCESSING`).
- **Deliverables:** SQS client wrapper; message publishing on upload; Worker Service polling loop (long polling); status update to `PROCESSING` on message receipt; DLQ configuration.
- **Features:** None new user-facing beyond status transitioning.
- **Learning Objectives:** Establish the fully async, decoupled ingestion contract before adding real processing logic — and reinforce that this queue is ingestion-only, never touched by the agent loop built later.
- **Milestone:** Uploading a file causes its status to flip from `PENDING` to `PROCESSING` via the worker, purely through the queue.
- **Completion Criteria:** Worker correctly deletes message from queue on success; a forced worker failure results in redelivery (verified locally).
- **Dependencies:** Phase 4.
- **Estimated Complexity:** Medium.
- **Recommended Git Branch:** `feat/sqs-worker-skeleton`
- **Recommended Commit Strategy:** SQS publisher → worker polling loop → status update logic.
- **Testing Strategy:** Integration tests using LocalStack SQS; test message redelivery behavior on simulated crash.
- **Deployment Milestone:** None (local only).

---

## Phase 6 — Text Extraction & Cleaning

- **Goal:** Implement extraction for PDF, DOCX, TXT, MD and basic text cleaning.
- **Deliverables:** `extract.py` module with per-file-type extractors (e.g., `pypdf`/`pdfplumber` for PDF, `python-docx` for DOCX, native read for TXT/MD); `clean.py` for whitespace normalization, header/footer stripping heuristics, encoding fixes.
- **Features:** None new user-facing yet (internal pipeline stage).
- **Learning Objectives:** Isolate and unit test the trickiest, most failure-prone part of ingestion in isolation.
- **Milestone:** Given a sample file of each supported type, the pipeline produces clean plain text.
- **Completion Criteria:** Corrupt/malformed files raise a typed exception caught by the worker and mapped to `FAILED` with a specific reason; extraction covered by unit tests with sample fixtures for each file type.
- **Dependencies:** Phase 5.
- **Estimated Complexity:** Medium-High.
- **Recommended Git Branch:** `feat/text-extraction`
- **Recommended Commit Strategy:** One commit per file-type extractor, one commit for cleaning logic.
- **Testing Strategy:** Unit tests with real sample fixtures (good and corrupt files) per format.
- **Deployment Milestone:** None (local only).

---

## Phase 7 — Chunking Strategy

- **Goal:** Implement recursive/semantic-aware chunking with configurable size and overlap.
- **Deliverables:** `chunk.py` module (recursive character/token splitter with overlap); page-number/position metadata attached per chunk; configurable chunk size (default ~500 tokens, 50-token overlap).
- **Features:** None new user-facing yet.
- **Learning Objectives:** Understand chunk-size trade-offs — later relevant to how the agent evaluates whether a given search result is "enough" evidence.
- **Milestone:** Extracted text from Phase 6 is split into well-formed chunks with correct metadata (`chunk_index`, `page_number`).
- **Completion Criteria:** No chunk exceeds the configured token budget; overlap correctly applied; unit tests verify boundaries on edge cases (very short docs, single-page docs).
- **Dependencies:** Phase 6.
- **Estimated Complexity:** Medium.
- **Recommended Git Branch:** `feat/chunking`
- **Recommended Commit Strategy:** Single feature commit plus a follow-up commit for edge-case fixes found via tests.
- **Testing Strategy:** Unit tests covering short docs, long docs, and boundary conditions.
- **Deployment Milestone:** None (local only).

---

## Phase 8 — Embeddings & Qdrant Upsert

- **Goal:** Generate embeddings for chunks using `sentence-transformers` (`bge-small-en-v1.5`) and upsert them into a per-KB Qdrant collection with full payload metadata.
- **Deliverables:** `embed.py` module (batched embedding generation); Qdrant client wrapper; collection provisioning logic (`kb_{id}` created on first document if not exists); upsert logic with deterministic point IDs; `chunks` rows written to PostgreSQL; final status transition to `INDEXED`.
- **Features:** End-to-end ingestion pipeline is now functionally complete — uploaded documents become searchable vectors, ready to be searched by the agent's tool once built.
- **Learning Objectives:** Complete the full ingestion pipeline; understand idempotent upserts.
- **Milestone:** Uploading a real PDF results in a fully populated Qdrant collection and `INDEXED` status within the target latency (<60s for a 10-page PDF).
- **Completion Criteria:** Re-processing the same document (simulated retry) does not create duplicate vectors; deleting a document removes its vectors.
- **Dependencies:** Phase 7.
- **Estimated Complexity:** High.
- **Recommended Git Branch:** `feat/embeddings-qdrant`
- **Recommended Commit Strategy:** Embedding module → Qdrant client/collection management → full pipeline wiring → status transition logic.
- **Testing Strategy:** Integration test against local Qdrant: upload → assert vector count matches chunk count; idempotency test (reprocess = same vector count).
- **Deployment Milestone:** First internal deployable milestone — ingestion pipeline is feature-complete.

---

## Phase 9 — Document Management UI (Status, Delete)

- **Goal:** Complete the document management experience on the frontend.
- **Deliverables:** Document list UI with live/polling status badges (Pending/Processing/Indexed/Failed); delete document action (cascades S3 + Postgres + Qdrant); error detail display for failed documents.
- **Features:** Users have full visibility and control over documents in a KB.
- **Learning Objectives:** Build responsive UI around asynchronous backend state (polling via TanStack Query).
- **Milestone:** A user can watch a document progress from Pending to Indexed in real time and delete it cleanly.
- **Completion Criteria:** Deleting a document while it is `PROCESSING` is handled gracefully (blocked or safely cancelled); Failed documents show a human-readable reason.
- **Dependencies:** Phase 8.
- **Estimated Complexity:** Medium.
- **Recommended Git Branch:** `feat/document-management-ui`
- **Recommended Commit Strategy:** Status polling hook → document list component → delete flow.
- **Testing Strategy:** Frontend component tests for each status state; integration test for delete cascade.
- **Deployment Milestone:** None (local only).

---

## Phase 10 — Chat CRUD

- **Goal:** Allow users to create, list, rename, and delete chats within a Knowledge Base.
- **Deliverables:** `/kb/{id}/chats` CRUD endpoints; `chats`/`messages` repository layer; frontend chat list/sidebar UI within a KB.
- **Features:** Users can manage multiple independent chats per KB.
- **Learning Objectives:** Extend the tenant-scoped CRUD pattern to a nested resource (chat belongs to KB belongs to user) — the same pattern the agent tools will rely on for tenant scoping.
- **Milestone:** A user can create multiple chats in one KB, each appearing independently in the sidebar.
- **Completion Criteria:** Authorization verified through the full chain (chat → KB → user); deleting a KB cascades to its chats.
- **Dependencies:** Phase 3 (KB CRUD), Phase 2 (Auth).
- **Estimated Complexity:** Low-Medium.
- **Recommended Git Branch:** `feat/chat-crud`
- **Recommended Commit Strategy:** Backend endpoints → frontend sidebar/list UI.
- **Testing Strategy:** Integration tests for nested-resource authorization; frontend tests for chat list UI.
- **Deployment Milestone:** None (local only).

---

## Phase 11 — Agent Tools & Tool-Calling Provider Abstraction

- **Goal:** Build the individual, independently-testable **agent tools** and the tool-calling-aware LLM provider interface — before wiring up the orchestration loop that uses them.
- **Deliverables:**
  - `providers/base.py`: `LLMProvider` interface extended to support tool/function-calling (declare tools, receive tool-call requests, receive final text) and streaming.
  - `providers/openai_provider.py`: OpenAI implementation of the tool-calling interface.
  - `agent/tools/base.py`: `Tool` Protocol (`name`, `description`, `args_schema: BaseModel`, `async def execute(args, context) -> ToolResult`).
  - `agent/tools/search_knowledge_base.py`: implements the retrieval logic from `architecture.md` §5.4 — query embedding, Qdrant ANN search scoped to `context.knowledge_base_id`, top-K formatting.
  - `agent/tools/get_document_context.py` and `agent/tools/list_documents.py`.
  - `agent/guardrails.py`: duplicate-query detection (cosine similarity against prior calls in the same list), tool-arg validation wrapper.
- **Features:** None user-visible yet — this phase produces the building blocks, not the assembled loop.
- **Learning Objectives:** Get retrieval-as-a-tool right and independently testable before adding the complexity of a multi-turn orchestration loop on top of it.
- **Milestone:** Given a `ToolContext(knowledge_base_id, user_id)` and a query string, `search_knowledge_base.execute(...)` returns correctly-scoped, correctly-ranked results directly (without any LLM involved yet).
- **Completion Criteria:** Tool execution is provably tenant-scoped in isolation (a test calling the tool with KB A's context can never return KB B's chunks, regardless of query content); tool-call argument validation rejects malformed input with a structured error, not an exception leak.
- **Dependencies:** Phase 8 (vectors must exist), Phase 10 (chats exist to eventually attach answers to).
- **Estimated Complexity:** High.
- **Recommended Git Branch:** `feat/agent-tools`
- **Recommended Commit Strategy:** Provider interface extension → OpenAI tool-calling implementation → `search_knowledge_base` tool → `get_document_context`/`list_documents` tools → guardrails module, as separate commits.
- **Testing Strategy:** Unit tests per tool with a seeded Qdrant collection; tenant-isolation tests calling tools directly (bypassing the orchestrator) to prove isolation is enforced at the tool layer itself, not just the API layer.
- **Deployment Milestone:** None (local only).

---

## Phase 12 — Agent Orchestrator (Bounded Loop)

- **Goal:** Implement the ReAct-style bounded agent loop from `architecture.md` §5.1 that wires the tools from Phase 11 into an autonomous, guardrailed reasoning process.
- **Deliverables:**
  - `agent/prompts/agent_system_prompt.py`: the system prompt instructing the model on tool usage, grounding rules, citation format, and untrusted-content handling for retrieved text (per `architecture.md` §16).
  - `agent/orchestrator.py`: the main loop — calls the LLM with the tool registry, executes any requested tool calls, appends results to the working context, tracks iteration count/elapsed time/token usage, forces a final answer on guardrail breach, and yields streamable events (`tool_call_started`, `tool_call_completed`, `token`, `done`).
  - Citation extraction: a pure function mapping the LLM's final answer text + the turn's accumulated tool-call results → structured citations.
  - `agent_steps` persistence wired to the orchestrator's event stream.
- **Features:** None user-visible via UI yet (no HTTP endpoint wired up) — testable directly against the orchestrator function.
- **Learning Objectives:** Isolate and validate the hardest part of the system — a correctly-bounded, non-runaway agent loop — before exposing it over HTTP/SSE.
- **Milestone:** Given a multi-hop test question requiring two distinct searches, the orchestrator autonomously issues two differently-worded `search_knowledge_base` calls and produces a final cited answer, all within 3 iterations.
- **Completion Criteria:** A test scenario using a mock LLM that always requests a new (non-duplicate) search never exceeds `max_iterations`; a test scenario simulating LLM tool-call timeout correctly triggers forced termination with `agent_budget_exhausted=true`; duplicate near-identical queries are correctly short-circuited per the guardrail.
- **Dependencies:** Phase 11.
- **Estimated Complexity:** Very High.
- **Recommended Git Branch:** `feat/agent-orchestrator`
- **Recommended Commit Strategy:** System prompt → core loop (happy path, single iteration) → multi-iteration support → guardrail enforcement (max iterations/timeout/token budget) → citation extraction → `agent_steps` persistence, as separate incremental commits.
- **Testing Strategy:** Extensive unit/integration tests using a **mock LLM provider** with scripted tool-call sequences (deterministic, no real API cost) covering: single-search happy path, multi-search happy path, no-results-found path, duplicate-query dedup, forced termination on max iterations, forced termination on timeout, malformed tool-call arguments, hallucinated/unknown tool name. A smaller set of manual QA tests against the real OpenAI provider validates realistic tool-calling behavior.
- **Deployment Milestone:** None (local only) — but this is the most critical correctness milestone in the whole project.

---

## Phase 13 — Chat Endpoint, Streaming & Frontend Chat UI (Agentic)

- **Goal:** Expose the orchestrator over an SSE HTTP endpoint and build the full chat UI, including optional agent step-trace visibility.
- **Deliverables:**
  - `POST /chats/{id}/messages` SSE endpoint: persists user message, runs the orchestrator, streams `agent_step` and `token` events, persists the assistant message + citations + `agent_steps` rows on completion.
  - Frontend: streaming token rendering, citation chips (per `design.md`), and a collapsible **agent step trace** component showing each search query issued and iteration number.
  - Rate limiting on the endpoint per `architecture.md` §17.
- **Features:** Full end-to-end agentic chat experience — the core product value proposition is now live.
- **Learning Objectives:** Handle a variable-length, multi-round streaming response correctly across FastAPI SSE and React (tool-call events interleaved with token events), and communicate agent activity to the user without disrupting the chat flow.
- **Milestone:** A user asks a multi-part question in the UI, sees (optionally) the agent's search steps as they happen, and receives a streamed, cited final answer referencing real uploaded content across multiple searches.
- **Completion Criteria:** Citations resolve to correct source excerpts >95% of the time on a test document set; a deliberately-vague or multi-hop test question measurably triggers more than one tool call in a majority of runs; the UI clearly communicates when `agent_budget_exhausted=true` rather than presenting a partial answer as complete and authoritative.
- **Dependencies:** Phase 12.
- **Estimated Complexity:** High.
- **Recommended Git Branch:** `feat/agentic-chat-endpoint`
- **Recommended Commit Strategy:** SSE endpoint wiring → frontend streaming token renderer → citation chip UI → agent step-trace component → rate limiting, as separate commits.
- **Testing Strategy:** Integration tests using the mock LLM provider from Phase 12 to verify the full endpoint→persistence round trip deterministically; manual QA against real OpenAI calls in a staging environment for realistic latency/behavior; frontend tests for streaming render correctness and step-trace display.
- **Deployment Milestone:** Second major internal milestone — core agentic product loop complete end-to-end locally.

---

## Phase 14 — Source Citation Viewer & Polish

- **Goal:** Build the UI for viewing the exact source excerpt behind a citation, plus general UX polish (loading/empty/error states across the app, including agent-specific states).
- **Deliverables:** Citation click → modal/side-panel showing document name, page number, and highlighted excerpt, plus which agent iteration/tool call produced it; consistent loading skeletons, empty states, and error boundaries across KB list, document list, and chat views (including a distinct "agent is searching…" state, per iteration, during streaming); dark mode implementation per `design.md`.
- **Features:** Full MVP UX per `design.md` is realized.
- **Learning Objectives:** Close the loop on trust/transparency — now extended to *agentic* transparency (not just "here's a citation" but "here's what the agent did to find it").
- **Milestone:** Every citation in a chat response is clickable, shows accurate source context, and links back to the specific search step that retrieved it.
- **Completion Criteria:** All screens defined in `design.md` have loading, empty, and error states implemented, including the agent step-trace states; dark mode toggle works and persists user preference.
- **Dependencies:** Phase 13.
- **Estimated Complexity:** Medium.
- **Recommended Git Branch:** `feat/citation-viewer-polish`
- **Recommended Commit Strategy:** Citation viewer component → state polish pass per screen → dark mode.
- **Testing Strategy:** Frontend component/visual tests; manual accessibility pass (keyboard nav, contrast).
- **Deployment Milestone:** None (local only) — UI feature-complete.

---

## Phase 15 — Rate Limiting, Security Hardening & Multi-Tenancy + Agent Test Suite

- **Goal:** Harden the system for production: rate limiting, input validation review, a cross-tenant isolation test suite, and a dedicated **agent guardrail regression suite**.
- **Deliverables:** Redis-backed rate limiter on API endpoints, including the agent-specific per-KB throughput guardrail (`architecture.md` §17); comprehensive authorization test suite (User A cannot access User B's KB/documents/chats/messages under any endpoint, **including via directly-invoked agent tool calls**); prompt-injection test scenarios (malicious content embedded in a document attempting to make the agent call unregistered tools or leak cross-tenant data); secrets audit; dependency vulnerability scan integrated into CI.
- **Features:** No new user-facing features; production-readiness gate.
- **Learning Objectives:** Treat security — and agent-loop safety specifically — as first-class deliverables, not afterthoughts.
- **Milestone:** Full cross-tenant isolation test suite passes, including agent-tool-level tests; a documented prompt-injection scenario (crafted document content instructing the model to ignore grounding rules) is verified to fail to alter agent behavior in a harmful way.
- **Completion Criteria:** Zero cross-tenant leakage findings; agent loop never exceeds guardrails under adversarial test prompting designed to induce runaway iteration; CI blocks on high/critical vulnerability findings.
- **Dependencies:** Phases 2–14 (covers the full surface area).
- **Estimated Complexity:** Medium-High.
- **Recommended Git Branch:** `chore/security-hardening`
- **Recommended Commit Strategy:** Rate limiter → isolation test suite → prompt-injection test suite → CI vulnerability scan integration, as separate commits.
- **Testing Strategy:** Dedicated `tests/security/` suite; dedicated `tests/agent_guardrails/` suite with adversarial mock-LLM scripts (always requests new tool calls, requests unregistered tools, requests near-duplicate queries); CI-gated vulnerability scanning.
- **Deployment Milestone:** None (local/CI only).

---

## Phase 16 — Dockerization & AWS Infrastructure Provisioning

- **Goal:** Containerize all services and provision baseline AWS infrastructure (manually or via console/CLI scripts; Terraform is a later phase).
- **Deliverables:** Production Dockerfiles for `web`, `api`, `worker` (multi-stage builds); VPC with public/private subnets; RDS PostgreSQL instance; S3 bucket with versioning; SQS queue + DLQ; ECR repositories; Qdrant deployment (ECS service or EC2); Redis (ElastiCache) for rate limiting and tool-result caching; IAM roles per service.
- **Features:** None new user-facing; infrastructure milestone.
- **Learning Objectives:** Translate the architecture document — including the agent's infrastructure footprint (no new services, but higher expected LLM/Qdrant call volume per user turn) — into real AWS resources and right-sized capacity.
- **Milestone:** All infrastructure exists and services can theoretically connect to it (verified via manual connectivity tests from a bastion/ECS exec session).
- **Completion Criteria:** Each Docker image builds and runs correctly locally against production-like env vars; infra resources tagged and documented; API service task sizing (CPU/memory) accounts for longer-held connections during multi-iteration agent turns.
- **Dependencies:** Phase 15.
- **Estimated Complexity:** High.
- **Recommended Git Branch:** `infra/aws-provisioning`
- **Recommended Commit Strategy:** One commit per Dockerfile; infra changes documented in `infra/` with setup scripts/README.
- **Testing Strategy:** Manual connectivity verification; Docker image smoke tests in CI.
- **Deployment Milestone:** Infrastructure exists but is not yet serving traffic.

---

## Phase 17 — CI/CD Pipeline (GitHub Actions) & ECS Deployment

- **Goal:** Automate build, test, and deployment of all three services to ECS Fargate.
- **Deliverables:** GitHub Actions workflows: lint/test on PR (including the mock-LLM agent test suite, which runs without real API cost/keys), build+push to ECR on merge to `main`, deploy to ECS (update task definition + service) with health-check gating; environment-specific config (staging/production) via GitHub Environments and Secrets, including per-environment `max_iterations`/`max_wall_clock_ms` tuning if needed.
- **Features:** None new user-facing; deployment automation milestone.
- **Learning Objectives:** Establish a repeatable, safe deployment process.
- **Milestone:** A merge to `main` automatically results in a healthy, updated deployment on ECS with zero manual steps.
- **Completion Criteria:** Failed health checks automatically roll back the deployment; pipeline completes in a reasonable time window (<15 min target).
- **Dependencies:** Phase 16.
- **Estimated Complexity:** High.
- **Recommended Git Branch:** `infra/ci-cd-pipeline`
- **Recommended Commit Strategy:** One workflow file per concern (lint/test, build/push, deploy), iterated via small commits.
- **Testing Strategy:** Pipeline dry-runs on a feature branch; staged rollout to a `staging` ECS environment before `production`, including a manual smoke test of a real multi-hop agentic query against staging.
- **Deployment Milestone:** **First live production deployment.**

---

## Phase 18 — Observability: Logging, Monitoring, Alarms

- **Goal:** Implement full observability per `architecture.md` §19–20, with particular emphasis on agent-loop-specific signals.
- **Deliverables:** Structured JSON logging across all services with `request_id`/`chat_id`/`message_id`/`iteration` propagation; CloudWatch log groups and metric filters; CloudWatch alarms (5xx rate, DLQ depth, ECS unhealthy tasks, RDS thresholds, **agent budget-exhausted rate**, **average iterations per turn trending toward the max**); `/health` and `/health/ready` endpoints (including LLM-provider connectivity check) wired into ECS health checks; a lightweight internal dashboard view (or CloudWatch dashboard) surfacing agent iteration/cost metrics.
- **Features:** None new user-facing; operational readiness milestone.
- **Learning Objectives:** Ensure production issues — including subtle agent-quality regressions, not just hard failures — are diagnosable without SSH/ad-hoc debugging.
- **Milestone:** A simulated failure (e.g., kill a worker task, or force the mock LLM to always request tools until budget exhaustion) surfaces correctly in CloudWatch logs and triggers the relevant alarm.
- **Completion Criteria:** All critical failure modes from `architecture.md` §21 have a corresponding alarm or log signal, including agent-specific ones.
- **Dependencies:** Phase 17.
- **Estimated Complexity:** Medium.
- **Recommended Git Branch:** `feat/observability`
- **Recommended Commit Strategy:** Logging middleware → CloudWatch alarm definitions → health check endpoints → agent metrics dashboard, as separate commits.
- **Testing Strategy:** Chaos-style manual failure injection in staging; alarm-firing verification.
- **Deployment Milestone:** Production deployment now fully observable, including agent-loop health.

---

## Phase 19 — Production Readiness Review & MVP Launch

- **Goal:** Final end-to-end verification against the PRD acceptance criteria and go-live.
- **Deliverables:** Full manual QA pass against every acceptance criterion in `prd.md` §15, with specific attention to the agentic acceptance criteria (multi-hop question triggers multiple searches, no-evidence question triggers an honest "not found" response, guardrails never breached under adversarial testing); load test of ingestion and agentic query pipelines at expected launch scale (accounting for the higher per-turn LLM/Qdrant call volume); backup/restore drill for RDS; documented runbook for common incidents, including "agent stuck near max iterations across many users" as a scenario.
- **Features:** MVP is complete and launched.
- **Learning Objectives:** Validate the system holistically, not just feature-by-feature — and specifically validate that the agentic behavior is a net quality improvement over a single-pass baseline on a hand-curated multi-hop test set.
- **Milestone:** All PRD acceptance criteria pass in the production environment.
- **Completion Criteria:** Sign-off checklist complete; production monitoring dashboard reviewed (including agent metrics); rollback plan documented and tested.
- **Dependencies:** Phase 18.
- **Estimated Complexity:** Medium.
- **Recommended Git Branch:** `release/v1.0`
- **Recommended Commit Strategy:** Tag `v1.0.0` after final verification commit.
- **Testing Strategy:** Full regression pass (manual + automated suite, including the agent guardrail suite from Phase 15); load testing (e.g., `locust`/`k6`) against staging, sized for agentic call volume.
- **Deployment Milestone:** **MVP Production Launch.**

---

## Future Phases (Post-MVP, not detailed here)

- Phase 20+: Additional agent tools — hybrid search (BM25 + vector) and cross-encoder re-ranking exposed as callable tools.
- Phase 21+: Cross-Knowledge-Base search tool and document metadata/filter search tool.
- Phase 22+: Agent self-critique/verification step (draft answer checked against retrieved evidence before finalizing, as an additional bounded loop stage).
- Phase 23+: Organization/team workspaces with RBAC.
- Phase 24+: Terraform migration for infrastructure-as-code.
- Phase 25+: Multi-provider LLM support (Claude, Gemini) with per-KB selection, including normalizing tool-calling formats across providers.
- Phase 26+: Billing and subscription tiers, informed by per-query agent cost tracking built in Phase 18.