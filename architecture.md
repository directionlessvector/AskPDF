# architecture.md — AskPDF AI

**System Architecture Document**
**Version:** 2.0 — Agentic RAG

---

## 1. High-Level Architecture

AskPDF AI is composed of independently deployable services communicating over well-defined APIs and an asynchronous message queue. The system is split into two fully decoupled pipelines — **Ingestion** and **Agentic Query** — that share only the vector store and metadata database.

The key architectural shift from a naive RAG system: the Query Pipeline is not "retrieve once, then generate." It is an **agent loop** running inside the API Service, in which the LLM is given a `search_knowledge_base` tool (and a smaller set of supporting tools) and decides, turn by turn, whether to call it, what to search for, and when it has enough evidence to answer.

```
                                   ┌─────────────────────────┐
                                   │        Frontend         │
                                   │  Next.js / React / TS   │
                                   └────────────┬─────────────┘
                                                │ HTTPS (REST + SSE)
                                                ▼
                                   ┌─────────────────────────┐
                                   │       API Gateway/       │
                                   │     Load Balancer (ALB)  │
                                   └────────────┬─────────────┘
                                                │
                                                ▼
                                   ┌─────────────────────────┐
                                   │      FastAPI Service     │
                                   │ (Auth, KB, Chat, Docs,    │
                                   │  Agent Orchestrator)      │
                                   └───┬───────────┬──────────┘
                                       │           │
                          ┌────────────┘           └─────────────┐
                          ▼                                      ▼
              ┌───────────────────┐                  ┌────────────────────┐
              │   PostgreSQL      │                  │   AWS S3            │
              │ (RDS) - metadata  │                  │ raw document store   │
              │ + agent steps     │                  └────────────────────┘
              └───────────────────┘                             │
                          │                                      ▼
                          │                          ┌────────────────────┐
                          │                          │   Amazon SQS        │
                          │                          │ ingestion-queue     │
                          │                          └─────────┬──────────┘
                          │                                     ▼
                          │                          ┌────────────────────┐
                          │                          │  Worker Service     │
                          │                          │ (extract/chunk/embed)│
                          │                          └─────────┬──────────┘
                          │                                     ▼
                          │                          ┌────────────────────┐
                          └─────────────────────────▶│      Qdrant         │
                                                       │  vector database    │
                                                       └────────────────────┘
                                                                 ▲
                                                                 │ tool-call retrieval
                                                                 │ (0..N calls per turn)
                                                       ┌────────────────────┐
                                                       │   Agent Loop         │
                                                       │  (inside FastAPI,    │
                                                       │   see §5)             │
                                                       └────────────────────┘
```

---

## 2. Microservices

| Service | Responsibility | Technology | Statefulness |
|---|---|---|---|
| **Frontend** | UI rendering, auth flows, chat UX (including agent step visibility), uploads | Next.js/React/TS | Stateless (client) |
| **API Service** | Auth, KB CRUD, document metadata, chat orchestration, **Agent Orchestrator** (query pipeline) | FastAPI/Python | Stateless |
| **Worker Service** | Consumes ingestion queue; extraction, cleaning, chunking, embedding, vector upsert | Python (SQS consumer) | Stateless (scales horizontally) |
| **PostgreSQL (RDS)** | Source of truth for users, KBs, documents, chunks metadata, chats, messages, agent step traces | PostgreSQL | Stateful |
| **Qdrant** | Vector storage + ANN search, invoked exclusively through the agent's search tool | Qdrant | Stateful |
| **S3** | Raw file storage | AWS S3 | Stateful (managed) |
| **SQS** | Decouples upload from processing; ingestion job queue only — **never used for the query/agent path** | Amazon SQS | Stateful (managed) |
| **LLM Provider** | Agent reasoning + tool-call decisions + final answer generation (OpenAI initially) | External API | N/A |

The API Service and Worker Service remain **independently deployable ECS Fargate services**. The Agent Orchestrator lives entirely inside the API Service's request path — it is synchronous-from-the-client's-perspective (streamed via SSE) even though it may perform multiple internal tool calls before completing.

---

## 3. Data Flow Overview

### Ingestion Pipeline (Async, Write Path) — unchanged from non-agentic design
```
Upload → S3 → SQS message → Worker → Extract → Clean → Chunk
   → Embed → Upsert to Qdrant → Update Postgres status → Done
```

### Agentic Query Pipeline (Sync/Streaming, Read Path) — core architectural change
```
User question → API Service → Agent Orchestrator starts loop:
   iteration 1..N (bounded):
      Agent LLM call → decides: call tool(s) OR produce final answer
      if tool call: execute search_knowledge_base (or supporting tool)
                    → results appended to agent's working context
      if final answer: exit loop
   → Stream final answer tokens to client
   → Extract citations from tool-call results actually used
   → Persist message + full agent step trace
```

The agent loop is a **finite state machine with a hard iteration ceiling**, not an open-ended autonomous agent — see §5 for the exact bound and guardrails.

---

## 4. Ingestion Pipeline (Detailed) — Unchanged

```
┌────────┐   1. POST /documents (multipart)   ┌──────────────┐
│ Client │ ─────────────────────────────────▶ │  API Service  │
└────────┘                                     └──────┬────────┘
                                                       │ 2. Store raw file
                                                       ▼
                                              ┌──────────────┐
                                              │   AWS S3      │
                                              │ kb/{kb_id}/   │
                                              │ docs/{doc_id} │
                                              └──────┬────────┘
                                                       │ 3. Insert Document row
                                                       │    status=PENDING
                                                       ▼
                                              ┌──────────────┐
                                              │ PostgreSQL    │
                                              └──────┬────────┘
                                                       │ 4. Publish SQS message
                                                       │   {document_id, kb_id, s3_key}
                                                       ▼
                                              ┌──────────────┐
                                              │ Amazon SQS    │
                                              │ ingestion-q   │
                                              └──────┬────────┘
                                                       │ 5. Poll message
                                                       ▼
                                              ┌──────────────┐
                                              │ Worker Service│
                                              └──────┬────────┘
             6. status=PROCESSING ────────────────────┤
             7. Download from S3 ─────────────────────┤
             8. Extract text (pdf/docx/txt/md) ────────┤
             9. Clean (whitespace, headers/footers) ───┤
            10. Chunk (recursive splitter, overlap) ───┤
            11. Generate embeddings (bge-small-en) ────┤
            12. Upsert vectors + metadata to Qdrant ───┤
            13. Write Chunk rows to PostgreSQL ────────┤
            14. status=INDEXED (or FAILED + reason) ───┘
                                                       │
                                                       ▼
                                              ┌──────────────┐
                                              │ PostgreSQL    │
                                              │ + Qdrant      │
                                              │ (final state) │
                                              └──────────────┘
```

**Failure handling:** If any step (6–13) throws, the worker marks the document `FAILED` with an `error_reason`, and the SQS message is either retried (transient errors, up to N times via visibility timeout + redelivery) or routed to a Dead Letter Queue (DLQ) after max retries for permanent failures (corrupt file, unsupported encoding).

---

## 5. Agent Loop (Detailed) — Core of the Query Pipeline

### 5.1 Design

The Agent Orchestrator implements a **bounded ReAct-style loop** (Reason → Act → Observe, repeated) using the LLM provider's native tool/function-calling capability.

```
┌─────────────────────────────────────────────────────────────┐
│                      AGENT ORCHESTRATOR                       │
│                                                                 │
│  state = {                                                     │
│    messages: [system_prompt, chat_history..., user_question],  │
│    iteration: 0,                                                │
│    max_iterations: 4 (config),                                  │
│    max_wall_clock_ms: 20000 (config),                           │
│    tool_calls_made: [],                                         │
│    tokens_used: 0                                                │
│  }                                                               │
│                                                                 │
│  loop:                                                          │
│    if iteration >= max_iterations OR elapsed >= max_wall_clock:  │
│        → force a final answer using best-available evidence      │
│          gathered so far, explicitly flagged as budget-exhausted  │
│                                                                    │
│    response = LLM.call(state.messages, tools=[search_kb, ...])    │
│                                                                    │
│    if response.tool_calls:                                        │
│        for each tool_call:                                        │
│            validate tool_call args (Pydantic schema)               │
│            deduplicate against tool_calls_made (near-identical      │
│              query text within this turn is rejected/merged)        │
│            result = execute_tool(tool_call)   # see §5.3            │
│            state.messages.append(tool_call, tool_result)            │
│            state.tool_calls_made.append(tool_call)                  │
│        iteration += 1                                                │
│        continue loop                                                 │
│                                                                       │
│    else:  # LLM produced a final answer, no more tool calls          │
│        stream response.content to client                            │
│        extract citations from tool_calls_made results referenced      │
│          in response.content                                          │
│        break loop                                                     │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Guardrails (Non-Negotiable)

| Guardrail | Default | Purpose |
|---|---|---|
| `max_iterations` | 4 tool-calling rounds per user turn | Bounds cost and latency |
| `max_wall_clock_ms` | 20,000ms per turn | Bounds latency even if the LLM provider is slow |
| `max_tokens_per_turn` | Configurable (e.g., 12,000 combined input+output across the whole loop) | Bounds cost |
| Duplicate-query rejection | Cosine similarity of tool-call query text > 0.95 against a prior call in the same turn is short-circuited (cached result reused, not re-searched) | Prevents unproductive loops |
| Forced termination | On hitting any limit above, the orchestrator injects a system message instructing the LLM to answer now with available evidence (or say it doesn't know) — it does not simply cut the connection | Graceful degradation, never a silent failure |
| Tool argument validation | Every tool call's arguments are validated against a strict Pydantic schema before execution; invalid calls return a structured error to the LLM (which may retry, still counted against `max_iterations`) | Prevents malformed/malicious tool invocations |
| Tenant scoping inside the tool | Every tool execution is passed the authenticated `user_id`/`knowledge_base_id` from the orchestrator's request context — **never** parameters the LLM can override | Prevents cross-tenant leakage even under prompt injection |

### 5.3 Agent Tools (MVP Toolset)

| Tool | Description | Arguments (LLM-supplied) | Server-injected (not LLM-controlled) |
|---|---|---|---|
| `search_knowledge_base` | Vector search over the current KB's Qdrant collection | `query: str`, `top_k: int (optional, default 8, max 15)` | `knowledge_base_id`, `user_id` |
| `get_document_context` | Fetch surrounding chunks (before/after) around a specific chunk already returned by a prior search, for extra context on a promising result | `chunk_id: str`, `window: int (optional, default 1)` | `knowledge_base_id`, `user_id` |
| `list_documents` | List document titles/filenames currently indexed in the KB, to help the agent decide if a topic is likely covered at all before searching | *(none)* | `knowledge_base_id`, `user_id` |

`search_knowledge_base` is the workhorse tool and mirrors the retrieval logic from a classic RAG pipeline — the difference is *who decides when to call it and with what query*: the LLM, not a fixed pipeline step.

### 5.4 Tool Execution Detail — `search_knowledge_base`

```
1. Validate args (query non-empty, top_k in [1,15])
2. Embed `query` using the same embedding model/version pinned to this KB
3. ANN search in Qdrant collection `kb_{knowledge_base_id}` — collection
   selection alone enforces tenant isolation (see architecture §11)
4. Return top_k results: [{chunk_id, document_id, filename, page_number,
   content, score}]
5. Record this call (query text, result chunk_ids, iteration number,
   timestamp) into the in-memory agent step trace for this turn
```

Steps 2–3 are functionally identical to the retrieval step of a classic RAG pipeline — the agentic architecture wraps the same retrieval primitive in a tool interface rather than a single hardwired pipeline stage.

### 5.5 Sequence Diagram — Full Agentic Turn

```
Client          API/Agent Orch.      LLM Provider      Qdrant        Postgres
  │  POST /chats/{id}/messages           │                │              │
  │──────────────▶│                      │                │              │
  │                │ persist user msg                     │              │
  │                │───────────────────────────────────────────────────▶│
  │                │ build system prompt + history                       │
  │                │ [iteration 1] call LLM w/ tools       │              │
  │                │───────────────────────▶│              │              │
  │                │◀────────────────────────│ tool_call:   │              │
  │                │  search_knowledge_base("query A")      │              │
  │                │ execute tool (inject kb_id/user_id)     │              │
  │                │────────────────────────────────────────▶│             │
  │                │◀────────────────────────────────────────│ chunks       │
  │                │ [iteration 2] call LLM w/ tool result   │              │
  │                │───────────────────────▶│              │              │
  │                │◀────────────────────────│ tool_call:   │              │
  │                │  search_knowledge_base("query B, refined")            │
  │                │────────────────────────────────────────▶│             │
  │                │◀────────────────────────────────────────│ chunks       │
  │                │ [iteration 3] call LLM w/ both results   │              │
  │                │───────────────────────▶│              │              │
  │                │◀────────────────────────│ final_answer  │              │
  │◀───────────────│  SSE: agent_step events (optional UI)   │              │
  │◀───────────────│  SSE: token, token, ...  │              │              │
  │                │ extract citations from tool_calls_made   │              │
  │                │ persist assistant msg + citations         │              │
  │                │ persist agent_steps (3 rows)                │            │
  │                │─────────────────────────────────────────────────────────▶│
```

---

## 6. Authentication Flow — Unchanged

```
1. POST /auth/register {email, password}
     → hash password (argon2/bcrypt) → create User row

2. POST /auth/login {email, password}
     → verify hash → issue:
         access_token  (JWT, 15 min TTL, HS256/RS256)
         refresh_token (JWT, 7-30 day TTL, stored hashed in DB or as httpOnly cookie)

3. Authenticated request:
     Authorization: Bearer <access_token>
     → API validates signature + expiry → extracts user_id → attaches to request context

4. POST /auth/refresh {refresh_token}
     → validate → rotate refresh token → issue new access_token

5. POST /auth/logout
     → revoke refresh token (DB blacklist or short-TTL rotation record)
```

OAuth-readiness: the `users` table includes `auth_provider` (`local`, `google`, `github`, …) and `provider_user_id` columns from day one so social login can be added without schema migration; only local (`email/password`) is enabled at launch.

---

## 7. Upload Flow (Sequence) — Unchanged

```
Client          API              S3              Postgres          SQS
  │  POST /kb/{id}/documents      │                │                │
  │───────────────▶│              │                │                │
  │                │  PUT object  │                │                │
  │                │─────────────▶│                │                │
  │                │◀─────────────│  200 OK        │                │
  │                │  INSERT document (PENDING)     │                │
  │                │────────────────────────────────▶│                │
  │                │◀────────────────────────────────│  row created   │
  │                │  send_message(document_id)                       │
  │                │──────────────────────────────────────────────────▶│
  │◀───────────────│  202 Accepted {document_id, status: PENDING}      │
```

---

## 8. Chat Flow (High-Level, Agentic)

```
Client            API/Agent           Qdrant            LLM             Postgres
  │  POST /chats/{id}/messages         │                  │                │
  │────────────────▶│                  │                  │                │
  │                  │  persist user message                               │
  │                  │──────────────────────────────────────────────────────▶│
  │                  │  run bounded agent loop (§5) — 1..N tool calls        │
  │                  │◀────────────────▶│                  │                │
  │                  │◀──────────────────────────────────▶│                │
  │◀─────────────────│  SSE: agent_step (optional), token, token, ..., done  │
  │                  │  persist assistant message + citations + step trace   │
  │                  │──────────────────────────────────────────────────────▶│
```

---

## 9. Retrieval Lifecycle (Now: Per-Tool-Call, Not Per-Turn)

Each individual `search_knowledge_base` tool invocation follows this lifecycle (may execute 0–4 times per user turn, per §5.2):

1. **Query normalization** — trim, preserve case, strip control chars. The query text is **written by the LLM**, not the raw user question — the agent may rephrase, narrow, or split the user's question across multiple calls.
2. **Embedding** — encode with the same model version used at ingestion time (model version pinned per KB to avoid drift).
3. **Vector search** — ANN search in Qdrant, scoped to the KB's dedicated collection (tenant isolation by construction, not just payload filtering).
4. **Top-K selection** — LLM-specified `top_k` (default 8, capped at 15).
5. **Result formatting** — chunks returned to the LLM as structured tool-result content (chunk_id, document filename, page number, content, score) so the LLM can reason about relevance and decide whether to search again.

**Turn-level assembly** (across all tool calls in the turn):
6. **Context accumulation** — all chunks retrieved across every tool call in the turn remain in the agent's working context for the remainder of that turn (the LLM can reference earlier search results without re-fetching them).
7. **Final answer generation** — once the LLM stops calling tools, it composes an answer citing specific chunk_ids from *any* tool call made during the turn.
8. **Citation extraction** — inline reference markers in the LLM's final answer are mapped back to the specific chunk_id → document_id → tool-call-iteration that produced them.
9. **Persistence** — the assistant message, its citations, and the full ordered list of tool calls (query text, iteration, result chunk_ids, latency) are stored for traceability and future evaluation.

---

## 10. Database Architecture (PostgreSQL)

### Core Tables

```
users
  id UUID PK
  email TEXT UNIQUE NOT NULL
  hashed_password TEXT NULL          -- null if OAuth-only
  auth_provider TEXT DEFAULT 'local'
  provider_user_id TEXT NULL
  created_at TIMESTAMPTZ
  updated_at TIMESTAMPTZ

knowledge_bases
  id UUID PK
  user_id UUID FK -> users.id
  name TEXT NOT NULL
  description TEXT
  created_at TIMESTAMPTZ
  updated_at TIMESTAMPTZ

documents
  id UUID PK
  knowledge_base_id UUID FK -> knowledge_bases.id
  filename TEXT NOT NULL
  file_type TEXT NOT NULL           -- pdf | docx | txt | md
  s3_key TEXT NOT NULL
  size_bytes BIGINT
  status TEXT NOT NULL DEFAULT 'PENDING'  -- PENDING|PROCESSING|INDEXED|FAILED
  error_reason TEXT NULL
  page_count INT NULL
  created_at TIMESTAMPTZ
  updated_at TIMESTAMPTZ

chunks
  id UUID PK
  document_id UUID FK -> documents.id
  knowledge_base_id UUID FK -> knowledge_bases.id  -- denormalized for fast filtering
  qdrant_point_id UUID NOT NULL
  chunk_index INT NOT NULL
  content TEXT NOT NULL
  token_count INT
  page_number INT NULL
  created_at TIMESTAMPTZ

chats
  id UUID PK
  knowledge_base_id UUID FK -> knowledge_bases.id
  user_id UUID FK -> users.id
  title TEXT
  created_at TIMESTAMPTZ
  updated_at TIMESTAMPTZ

messages
  id UUID PK
  chat_id UUID FK -> chats.id
  role TEXT NOT NULL              -- user | assistant | system
  content TEXT NOT NULL
  citations JSONB NULL            -- [{chunk_id, document_id, excerpt, score, tool_call_id}]
  token_usage JSONB NULL
  agent_iteration_count INT NULL  -- how many tool-calling rounds this answer took
  agent_budget_exhausted BOOLEAN DEFAULT FALSE  -- true if forced termination occurred
  created_at TIMESTAMPTZ

agent_steps
  id UUID PK
  message_id UUID FK -> messages.id      -- the assistant message this step contributed to
  iteration INT NOT NULL                  -- 1-indexed round within the turn
  tool_name TEXT NOT NULL                 -- e.g. 'search_knowledge_base'
  tool_args JSONB NOT NULL                -- {query, top_k} as issued by the LLM
  result_summary JSONB NOT NULL           -- [{chunk_id, document_id, score}] (lightweight)
  latency_ms INT
  created_at TIMESTAMPTZ
```

### Indexing Strategy
- `knowledge_bases(user_id)` — B-tree index for listing.
- `documents(knowledge_base_id, status)` — composite index for status polling.
- `chunks(knowledge_base_id)` and `chunks(document_id)` — composite indexes.
- `chats(knowledge_base_id)`, `messages(chat_id, created_at)` — for chronological pagination.
- `agent_steps(message_id, iteration)` — for reconstructing the ordered trace of a given answer.
- All foreign keys use `ON DELETE CASCADE` to enforce the cascading delete requirements in the PRD.

---

## 11. Vector Database Architecture (Qdrant) — Unchanged Strategy, New Caller

**Collection strategy:** One Qdrant collection per **Knowledge Base** (`kb_{knowledge_base_id}`). This remains the isolation boundary even though Qdrant is now invoked from inside a tool call rather than a fixed pipeline step — the agent's `search_knowledge_base` tool implementation hardcodes the collection name from the server-injected `knowledge_base_id`, never from LLM-supplied input.

**Point payload schema:**
```json
{
  "document_id": "uuid",
  "chunk_id": "uuid",
  "knowledge_base_id": "uuid",
  "chunk_index": 0,
  "page_number": 3,
  "content_preview": "first 200 chars...",
  "embedding_model_version": "bge-small-en-v1.5"
}
```

**Vector config:** 384-dim (bge-small-en-v1.5), cosine distance, HNSW index (`m=16`, `ef_construct=100` default, tunable).

---

## 12. Metadata Strategy — Unchanged, Plus Agent Traceability

- Every chunk stored in Qdrant carries enough payload metadata to reconstruct a citation without a round trip to PostgreSQL, while PostgreSQL remains authoritative for full chunk `content`.
- `embedding_model_version` is stored per point for future re-embedding migrations.
- Tenant isolation is enforced at two layers: (1) collection-per-KB in Qdrant, (2) `knowledge_base_id`/`user_id` scoping on every PostgreSQL query and, critically, (3) **inside the tool execution layer itself** — the LLM never supplies `knowledge_base_id`; it is injected by the orchestrator from the authenticated request.
- `agent_steps` provides a full audit trail of every search the agent performed to answer a given message, enabling future retrieval-quality evaluation and debugging of "why did the agent answer this way."

---

## 13. Folder Structure

```
askpdf-ai/
├── apps/
│   ├── web/                        # Next.js frontend
│   │   ├── app/
│   │   │   ├── (auth)/login/
│   │   │   ├── (auth)/register/
│   │   │   ├── (dashboard)/knowledge-bases/
│   │   │   ├── (dashboard)/kb/[kbId]/
│   │   │   ├── (dashboard)/kb/[kbId]/chat/[chatId]/
│   │   │   └── layout.tsx
│   │   ├── components/
│   │   │   ├── ui/                 # shadcn/ui primitives
│   │   │   ├── chat/
│   │   │   │   ├── agent-step-trace.tsx   # NEW: expandable "what the agent searched" view
│   │   │   │   └── ...
│   │   │   ├── documents/
│   │   │   └── knowledge-base/
│   │   ├── hooks/
│   │   ├── lib/
│   │   │   ├── api-client.ts
│   │   │   └── query-client.ts
│   │   ├── types/
│   │   └── styles/
│   │
│   ├── api/                        # FastAPI service
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── core/                # config, security, logging
│   │   │   ├── api/v1/
│   │   │   │   ├── auth.py
│   │   │   │   ├── knowledge_bases.py
│   │   │   │   ├── documents.py
│   │   │   │   └── chats.py
│   │   │   ├── models/              # SQLAlchemy models (incl. AgentStep)
│   │   │   ├── schemas/             # Pydantic schemas
│   │   │   ├── services/            # business logic
│   │   │   ├── repositories/        # DB access layer
│   │   │   ├── agent/                # NEW: agent orchestrator package
│   │   │   │   ├── orchestrator.py   # the bounded loop from §5.1
│   │   │   │   ├── tools/
│   │   │   │   │   ├── base.py       # Tool interface/Protocol
│   │   │   │   │   ├── search_knowledge_base.py
│   │   │   │   │   ├── get_document_context.py
│   │   │   │   │   └── list_documents.py
│   │   │   │   ├── prompts/
│   │   │   │   │   └── agent_system_prompt.py
│   │   │   │   └── guardrails.py     # iteration/token/time limits, dedup logic
│   │   │   └── providers/           # LLM/embedding provider abstraction (tool-calling aware)
│   │   ├── alembic/                 # migrations
│   │   └── tests/
│   │
│   └── worker/                      # Ingestion worker service (unchanged)
│       ├── app/
│       │   ├── main.py              # SQS polling loop
│       │   ├── pipeline/
│       │   │   ├── extract.py
│       │   │   ├── clean.py
│       │   │   ├── chunk.py
│       │   │   └── embed.py
│       │   ├── providers/           # shared embedding provider abstraction
│       │   └── repositories/
│       └── tests/
│
├── packages/
│   └── shared/                      # shared types/schemas between api & worker (Python package)
│
├── infra/
│   ├── docker/
│   ├── ecs/
│   ├── terraform/                   # later phase
│   └── github-actions/
│
└── docs/
    ├── prd.md
    ├── architecture.md
    ├── phases.md
    ├── design.md
    ├── rules.md
    └── memory.md
```

---

## 14. Deployment Architecture (AWS) — Unchanged Infrastructure Topology

```
                          ┌─────────────────────────┐
                          │      Route 53 / DNS      │
                          └────────────┬─────────────┘
                                       ▼
                          ┌─────────────────────────┐
                          │   CloudFront (frontend)  │
                          └────────────┬─────────────┘
                                       ▼
                          ┌─────────────────────────┐
                          │  Application Load Balancer│
                          └──────┬──────────┬─────────┘
                                 ▼          ▼
                      ┌────────────────┐ ┌────────────────┐
                      │  ECS Fargate    │ │  ECS Fargate    │
                      │  API Service    │ │  (future: agent  │
                      │  (incl. agent   │ │   svc split out)  │
                      │   orchestrator, │ │                    │
                      │   autoscaled)   │ │                    │
                      └───────┬─────────┘ └────────────────┘
                              │
             ┌────────────────┼───────────────────┐
             ▼                ▼                   ▼
    ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
    │ RDS PostgreSQL  │ │  Qdrant (ECS/   │ │  S3 Bucket      │
    │ (Multi-AZ)      │ │  EC2 or managed)│ │  documents       │
    └────────────────┘ └────────────────┘ └────────────────┘
             ▲
             │
    ┌────────────────┐        ┌────────────────┐
    │ Amazon SQS      │◀──────▶│ ECS Fargate     │
    │ ingestion-queue │        │ Worker Service   │
    │ + DLQ           │        │ (autoscaled on    │
    │ (ingestion only,│        │  queue depth)      │
    │  never agent)   │        └────────────────┘
    └────────────────┘

    Cross-cutting: CloudWatch (logs/metrics/alarms, incl. agent iteration/cost
    metrics), IAM (least privilege per task role), ECR (container images),
    GitHub Actions (CI/CD)
```

The Agent Orchestrator adds **no new infrastructure component** — it is code running inside the existing API Service. The only new external dependency is that the chosen LLM provider/model must support function/tool calling with streaming.

### Service-to-service communication
- Frontend → API: HTTPS via ALB; SSE for streaming chat responses, including optional `agent_step` events.
- API (Agent Orchestrator) → LLM Provider: HTTPS, potentially 1–4 round trips per user turn (one per iteration), each with streaming enabled on the final (non-tool-call) response.
- API (Agent Orchestrator) → Qdrant: internal service discovery (ECS Service Connect or internal ALB/NLB) over private VPC networking, invoked from within tool execution, 0–4 times per turn.
- API → PostgreSQL: private subnet, security-group restricted.
- API → S3: presigned URLs for upload/download where possible; otherwise IAM task role with scoped bucket policy.
- API → SQS: `SendMessage` via IAM task role (ingestion only).
- Worker → SQS/S3/PostgreSQL/Qdrant: unchanged from non-agentic design.

---

## 15. Scaling Strategy

| Component | Scaling Trigger | Mechanism |
|---|---|---|
| API Service (ECS Fargate) | CPU > 60% or request count per target — **note:** agentic turns hold a connection open longer (multiple internal round trips), so concurrency planning must account for longer average request duration than a single-pass system | ECS Service Auto Scaling |
| Worker Service (ECS Fargate) | SQS `ApproximateNumberOfMessagesVisible` | Target-tracking scaling policy on queue depth |
| RDS PostgreSQL | Connections/CPU | Vertical scaling (MVP); read replicas (future) |
| Qdrant | Collection count / QPS / memory — **note:** agentic queries can issue up to `max_iterations` searches per turn, so QPS planning should assume 1.5–2x the naive single-search-per-turn estimate | Vertical scaling initially; sharded cluster (future) |
| S3 | N/A | Natively scales |
| SQS | N/A | Natively scales (ingestion only) |

Both API and Worker remain explicitly **stateless**: the agent loop's state lives entirely in-memory for the duration of a single request (not persisted mid-loop), enabling safe horizontal scaling — a retried/failed request simply restarts the loop from scratch rather than resuming partial agent state.

---

## 16. Security Architecture

- **Transport:** TLS everywhere (ALB terminates TLS with ACM-managed certs).
- **AuthN:** JWT (short-lived access + rotating refresh tokens); passwords hashed with argon2.
- **AuthZ:** Every resource access checks `resource.user_id == request.user_id` (or KB ownership chain) at the service layer — never trust client-supplied IDs alone.
- **Tenant isolation:** Enforced at DB query layer, Qdrant collection-per-KB, **and inside every agent tool implementation** — tool functions accept `knowledge_base_id`/`user_id` only as server-injected context, never as LLM-controllable arguments, which closes off a prompt-injection path to cross-tenant data access.
- **Prompt injection hardening:** Document content retrieved via tool calls is treated as untrusted data within the prompt — the system prompt explicitly instructs the model that retrieved content is reference material, not instructions, and the orchestrator strips/ignores any tool-call requests for tools not in the registered allow-list regardless of what the model or document content suggests.
- **Secrets:** AWS Secrets Manager for DB credentials, JWT signing keys, OpenAI API key; injected as ECS task environment via Secrets Manager integration — never hardcoded or committed.
- **IAM:** Least-privilege task roles per service (API role ≠ Worker role); no wildcard `*` resource policies.
- **Input validation:** Pydantic schemas validate all API input and every agent tool-call argument before execution; file type/size validated before S3 upload accepted.
- **Network:** Private subnets for RDS/Qdrant/Worker; only ALB in public subnet.
- **Dependency security:** Automated vulnerability scanning of Docker images in CI (e.g., `trivy`) before push to ECR.

---

## 17. Rate Limiting

- Applied at the API Service layer (Redis-backed token bucket).
- Default limits (MVP): 60 requests/min per user for general API, **10 chat turns/min per user for the agent endpoint** (each turn may itself cost up to `max_iterations` LLM calls, so this limit is calibrated against worst-case agent cost, not per-LLM-call).
- A secondary internal guardrail caps total LLM calls (across all users) per minute per KB to protect against a single hot KB monopolizing agent throughput.
- Upload endpoint additionally limited by concurrent in-flight uploads per user (e.g., 5 concurrent).
- 429 responses include `Retry-After` header.

---

## 18. Caching

- **Tool-call result cache:** short-TTL cache (Redis) keyed by `(knowledge_base_id, normalized_query_text)` for `search_knowledge_base` results — since the agent may issue similar queries across iterations or across chats in the same KB, this both reduces embedding/Qdrant load and reinforces the duplicate-query guardrail in §5.2.
- **KB/document list caching:** TanStack Query on the frontend handles client-side caching/invalidation.
- **Future:** semantic cache for full question→answer pairs with cosine-similarity threshold matching.

---

## 19. Logging

- Structured JSON logs (`timestamp`, `level`, `service`, `request_id`, `user_id`, `message`, `extra`).
- `request_id` generated at ALB/API edge and propagated through every agent iteration and worker job for end-to-end traceability.
- **Agent-specific structured fields:** every agent iteration logs `chat_id`, `message_id`, `iteration`, `tool_name`, `tool_args` (query text truncated/redacted per policy below), `result_count`, `latency_ms`.
- Logs shipped to CloudWatch Logs with service-specific log groups (`/askpdf/api`, `/askpdf/worker`).
- No PII/document content logged at INFO level; DEBUG level may log truncated previews behind a feature flag, never in production. Agent tool-call query text (LLM-generated, not raw user document content) may be logged at INFO for observability since it does not contain document content — only the *questions the agent chose to ask*, which are lower sensitivity than the retrieved content itself.

---

## 20. Monitoring

- **CloudWatch Metrics:** request latency, error rate, SQS queue depth, ECS CPU/memory, RDS connections.
- **Agent-specific metrics:** average/percentile iterations per turn, percentage of turns hitting `max_iterations` (budget-exhausted), average agent-turn LLM token cost, agent-turn wall-clock duration distribution.
- **CloudWatch Alarms:** SQS DLQ depth > 0, API 5xx rate > threshold, ECS service unhealthy task count, RDS storage/CPU thresholds, **budget-exhausted rate > 10% of turns** (signals retrieval quality or prompt tuning issue), **average iterations trending toward `max_iterations`** (signals guardrail may be too tight or retrieval quality is degrading).
- **Health checks:** `/health` (liveness) and `/health/ready` (readiness, checks DB/Qdrant/SQS/LLM-provider connectivity) on API and Worker.
- **Future:** distributed tracing (OpenTelemetry → X-Ray or a third-party APM), with each agent iteration as a child span of the parent chat-turn trace.

---

## 21. Failure Handling

| Failure | Handling |
|---|---|
| Worker crashes mid-processing | SQS visibility timeout expires → message redelivered; processing is idempotent (checked via document status before reprocessing). |
| Text extraction fails (corrupt file) | Document marked `FAILED` with reason; message not retried (permanent failure) — sent to DLQ after 1 attempt classification. |
| Embedding API/model failure (transient) | Retried with exponential backoff (up to N attempts) before DLQ. |
| **Agent LLM call fails mid-loop (provider outage/timeout)** | Orchestrator retries that single LLM call once with backoff; if it still fails, the turn ends gracefully with an error message to the client — no partial/corrupted tool-call state is persisted as a completed answer. |
| **Agent exceeds `max_iterations` or `max_wall_clock_ms`** | Not treated as a failure: orchestrator forces a final-answer generation using accumulated evidence, flags `agent_budget_exhausted=true` on the message, and the answer explicitly notes if the evidence found may be incomplete. |
| **Agent requests a tool not in the registered allow-list (hallucinated tool name)** | Orchestrator returns a structured "unknown tool" error to the LLM as the tool result (counted against `max_iterations`), rather than crashing the request. |
| **Tool execution throws (e.g., Qdrant transiently unavailable mid-loop)** | That specific tool call's result is returned to the LLM as an explicit error observation ("search temporarily unavailable"), allowing the LLM to decide whether to retry, try a different approach, or answer with prior evidence — still bounded by the overall guardrails. |
| LLM provider outage before any tool calls succeed | API returns a graceful error to client; message not persisted as assistant response; user can retry. |
| Qdrant unavailable at query time (all tool calls in the turn fail) | Agent surfaces a clear "I'm unable to search your documents right now" answer rather than fabricating one; API-level circuit breaker also engages to shed load if Qdrant is broadly degraded. |
| Partial ingestion (some chunks embedded, then failure) | Worker performs upsert in a single logical transaction per document: chunks are only marked committed in Postgres after full Qdrant upsert succeeds; otherwise the whole document is reprocessed from scratch. |

---

## 22. Retry Strategy

- **SQS consumption (ingestion only):** visibility timeout tuned to expected max processing time; redelivery acts as retry #1, #2, #3; max receive count 3, then DLQ.
- **Agent LLM calls:** each individual LLM call within the loop gets at most 1 retry with short backoff on transient failure (network/5xx from provider) — this retry does **not** consume an agent iteration (iterations count tool-calling rounds, not raw HTTP retries), but does count against `max_wall_clock_ms`.
- **Agent tool calls:** a failed tool execution is surfaced to the LLM as an error observation (per §21) rather than silently retried by the orchestrator — the *agent itself* decides whether to try again, which is itself bounded by `max_iterations`.
- **Idempotency:** All worker operations are keyed by `document_id`; re-processing a document is safe (upserts, not appends) — Qdrant points use deterministic IDs derived from `chunk_id`. The agent loop has no equivalent idempotency requirement since it is not queued/retried at the message level — a client-side retry of a failed chat turn simply starts a fresh agent loop.