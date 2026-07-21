# PRD.md — AskPDF AI

**Product Requirements Document**
**Version:** 2.0 — Agentic RAG
**Status:** Draft for Implementation
**Owner:** Product/Engineering

---

## 1. Vision

AskPDF AI is a multi-tenant, production-grade **Agentic Retrieval-Augmented Generation (RAG) SaaS** platform that lets any user turn their private documents into a conversational, cited knowledge source. Users create **Knowledge Bases**, upload documents (PDF, DOCX, TXT, Markdown), and chat with an AI **agent** that reasons about what it needs to know, actively searches the knowledge base (potentially multiple times, reformulating its own queries), and answers strictly grounded in retrieved content — always citing its sources.

Unlike a classic single-pass RAG pipeline (embed question → one vector search → generate), AskPDF AI's assistant is an **agent with retrieval as a tool**: it decides *whether* to search, *what* to search for, *whether the results are sufficient*, and *whether to search again* before composing a final answer. This materially improves answer quality on multi-hop questions, ambiguous queries, and questions spanning multiple documents.

AskPDF AI sits at the intersection of NotebookLM (source-grounded notebooks), ChatPDF (single-document chat), and Perplexity Spaces (cited, conversational retrieval) — combined into one coherent, scalable, agentic product.

The long-term vision is a platform that:

- Scales horizontally to thousands of tenants and millions of documents.
- Supports pluggable embedding models and LLM providers.
- Runs a bounded, observable, cost-controlled agent loop for every query.
- Provides enterprise-grade security, observability, and reliability.
- Expands the agent's toolset over time (hybrid search, re-ranking, cross-document synthesis) without breaking the core architecture.

---

## 2. Problem Statement

Knowledge workers, students, researchers, and small teams accumulate large amounts of unstructured document data (PDFs, reports, contracts, papers, notes) that is difficult to search, synthesize, and reason over. Existing tools are either:

- **Too narrow** (ChatPDF-style tools support only one document at a time, no organization, single-shot retrieval that fails on multi-hop questions).
- **Too generic** (general chat assistants lack grounded citations and hallucinate).
- **Too complex/enterprise-locked** (enterprise RAG platforms require IT setup, are expensive, and are not self-serve).
- **Too rigid** (single-pass RAG systems retrieve once and generate — they cannot recover from a bad initial search, cannot decompose a complex question, and cannot verify their own answer against sources before responding).

Users need a self-serve product where they can organize documents into topical collections, ask natural-language questions — including complex, multi-part, or comparative questions — and trust that the assistant will actively work to find the right supporting evidence before answering, with verifiable citations.

---

## 3. Goals

- Enable users to create and manage multiple **Knowledge Bases**, each with its own document set.
- Support ingestion of PDF, DOCX, TXT, and Markdown files with automatic text extraction, chunking, and embedding.
- Provide a chat interface backed by an **agentic retrieval loop**: the assistant can call a search tool one or more times, reformulate queries, and decide when it has enough evidence before answering.
- Give users visibility into the agent's process (what it searched for, how many steps it took) without overwhelming the core chat experience.
- Support multiple independent chat threads per Knowledge Base, all sharing the same underlying vector index and agent toolset.
- Ship a secure, multi-tenant architecture with strict data isolation between users.
- Bound the agent loop with hard iteration, token, and latency limits so cost and response time remain predictable.
- Deploy on AWS using a scalable, production-grade infrastructure (ECS Fargate, S3, RDS, Qdrant, SQS).
- Build the system with clean separation between ingestion and query pipelines so each can scale and evolve independently; the agent loop lives entirely within the query pipeline.

---

## 4. Non-Goals (v1)

- Real-time multi-user collaborative editing of Knowledge Bases (single-owner model in MVP).
- Support for video/audio transcription ingestion (future roadmap).
- Fine-tuning of LLMs on user data.
- On-premise / self-hosted deployment tooling (cloud-only for v1).
- Team/organization workspaces with role-based permissions (v1 is single-user-owned KBs; multi-user orgs are a future phase).
- Native mobile apps (responsive web only in v1).
- Support for LLM providers beyond OpenAI at launch (architecture must allow it, but only OpenAI ships in MVP).
- Agent tools beyond knowledge-base search and document lookup (no web search, no code execution, no cross-KB search in v1).
- Fully autonomous multi-turn planning across chats (the agent loop is scoped to a single user message/turn, not a long-running background agent).

---

## 5. Personas

| Persona | Description | Primary Needs |
|---|---|---|
| **Independent Researcher** | Grad student or analyst working with dozens of papers/reports. | Organize documents by project, ask synthesis/multi-hop questions, trust citations. |
| **Knowledge Worker / Consultant** | Reviews contracts, proposals, and reports. | Fast Q&A over long documents, source traceability, confidence the assistant actually looked before answering. |
| **Small Team Lead** | Wants to build an internal FAQ or onboarding knowledge base from existing docs. | Easy upload, shareable chat access (future), reliable answers even for loosely-phrased questions. |
| **Developer / Power User** | Wants to explore AI-native tools, may probe API limits. | Predictable performance and cost, transparency into agent steps, clear error states. |

---

## 6. User Stories

### Authentication
- As a user, I can sign up with email/password so that I can create an account.
- As a user, I can log in and receive a JWT session so that I can access my data securely.
- As a user, I can log out so that my session is invalidated.
- As a developer, I want the auth system OAuth-ready so social login can be added later without rearchitecting.

### Knowledge Base Management
- As a user, I can create a new Knowledge Base with a name and description.
- As a user, I can view a list of all my Knowledge Bases.
- As a user, I can rename or delete a Knowledge Base.
- As a user, deleting a Knowledge Base removes all associated documents, chunks, embeddings, and chats.

### Document Ingestion
- As a user, I can upload one or more PDF/DOCX/TXT/MD files to a Knowledge Base.
- As a user, I can see the processing status of each uploaded document (Pending, Processing, Indexed, Failed).
- As a user, I can delete a document from a Knowledge Base, which removes its vectors from the index.
- As a user, I receive a clear error message if a file fails to process (corrupt file, unsupported format, size limit exceeded).

### Agentic Chat
- As a user, I can create multiple chats within a single Knowledge Base.
- As a user, I can ask a question — including a vague, broad, or multi-part one — and the assistant will actively search the knowledge base as many times as needed (within bounds) to gather sufficient evidence.
- As a user, I can optionally expand a "steps" view to see what the agent searched for and how many search iterations it performed.
- As a user, I receive a streamed final answer with citations mapped to the specific search results that supported it.
- As a user, if the agent cannot find sufficient evidence after its allowed searches, I'm told clearly that the answer isn't supported by the knowledge base rather than receiving a fabricated answer.
- As a user, I can click a citation to view the relevant source excerpt.
- As a user, I can view my chat history within a session.
- As a user, I can rename or delete a chat.

### Platform
- As a user, I want the app to be responsive on mobile and desktop.
- As a user, I want to see clear loading, empty, and error states throughout the app, including while the agent is actively searching.

---

## 7. Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Users can register and authenticate via email/password with JWT-based sessions. | Must |
| FR-2 | System issues short-lived access tokens and long-lived refresh tokens. | Must |
| FR-3 | Users can create, rename, and delete Knowledge Bases. | Must |
| FR-4 | Users can upload PDF, DOCX, TXT, MD files up to a configurable size limit (default 25MB). | Must |
| FR-5 | Uploaded files are stored in S3 under a tenant-scoped key prefix. | Must |
| FR-6 | Ingestion pipeline extracts text, cleans, chunks, embeds, and stores vectors in Qdrant with metadata. | Must |
| FR-7 | Document processing status is tracked and exposed via API (Pending/Processing/Indexed/Failed). | Must |
| FR-8 | Users can create multiple chats per Knowledge Base. | Must |
| FR-9 | Chat responses are streamed token-by-token to the client. | Must |
| FR-10 | Query answering is driven by an **agent loop** with a `search_knowledge_base` tool the LLM can invoke multiple times per turn, reformulating queries between calls. | Must |
| FR-11 | The agent loop is bounded by a configurable max iteration count (default 4 search calls) and a max wall-clock timeout (default 20s) per turn. | Must |
| FR-12 | Every AI answer includes citations referencing source document(s) and chunk(s) actually returned by tool calls used to produce the answer. | Must |
| FR-13 | Users can view the original excerpt behind a citation. | Must |
| FR-14 | Users can optionally view a step-by-step trace of the agent's tool calls for a given answer (query issued, number of results, iteration number). | Should |
| FR-15 | Deleting a document removes its chunks/vectors from Qdrant and its S3 object. | Must |
| FR-16 | Deleting a Knowledge Base cascades to documents, chunks, vectors, chats, and messages. | Must |
| FR-17 | System enforces per-user data isolation at the database and vector-store level, including inside every agent tool call. | Must |
| FR-18 | If the agent's tool calls yield no relevant evidence after exhausting its iteration budget, the system returns an explicit "not found in knowledge base" response rather than an ungrounded answer. | Must |
| FR-19 | System supports pluggable embedding models (config-driven). | Should |
| FR-20 | System supports pluggable LLM providers via an abstraction layer, including tool-calling support. | Should |
| FR-21 | Users can search/filter their Knowledge Bases and chats. | Could |
| FR-22 | Users can export a chat transcript, optionally including the agent's step trace. | Could |
| FR-23 | System supports hybrid search and re-ranking as additional agent tool capabilities. | Won't (v1) — Future |
| FR-24 | System supports organization/team workspaces. | Won't (v1) — Future |
| FR-25 | Agent has additional tools beyond knowledge-base search (e.g., cross-KB search, web search). | Won't (v1) — Future |

---

## 8. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Performance** | p95 time-to-first-token < 3.5s under nominal load, accounting for at least one agent search iteration (higher than a single-pass system's budget, reflecting the agent's extra reasoning/search round-trips). |
| **Scalability** | API service and workers must be stateless and horizontally scalable. |
| **Availability** | Target 99.5% uptime for MVP; 99.9% post-GA. |
| **Cost Predictability** | Agent loop must be hard-bounded (iterations, tokens, wall-clock) so a single query cannot run away in cost or latency. |
| **Security** | All traffic over TLS; secrets in AWS Secrets Manager; passwords hashed with bcrypt/argon2. |
| **Multi-tenancy** | Strict row-level and vector-namespace isolation per user/KB, enforced inside every agent tool invocation, not just at the API boundary. |
| **Observability** | Structured JSON logging, request tracing, CloudWatch metrics/alarms on all services, including per-iteration agent step logging. |
| **Data Durability** | S3 versioning enabled; RDS automated backups with PITR. |
| **Compliance readiness** | Architecture must support future SOC 2 readiness (audit logs, encryption at rest). |
| **Maintainability** | Clear service boundaries; ingestion and query pipelines independently deployable; agent tools independently addable/removable. |
| **Cost Efficiency** | Workers scale to zero/minimum when idle; use spot-friendly Fargate where viable; agent iteration budget defaults tuned to balance quality vs. LLM API cost. |

---

## 9. Success Metrics

| Metric | Target (MVP) |
|---|---|
| Time to first indexed document | < 60s for a 10-page PDF |
| Answer grounded-citation rate | > 95% of answers include at least one valid citation |
| Query p95 latency (time to first token) | < 3.5s |
| Average agent iterations per query | Tracked; target median 1–2 search calls, informing future tuning |
| Queries hitting max-iteration limit without resolution | < 5% of queries |
| Ingestion success rate | > 98% of supported file types process without failure |
| Weekly active Knowledge Bases per user | Tracked, target growth over time |
| System uptime | ≥ 99.5% monthly |
| Error rate on core APIs | < 1% of requests |

---

## 10. Technical Constraints

- Frontend must be built with Next.js + React + TypeScript + TailwindCSS + shadcn/ui + TanStack Query.
- Backend must be FastAPI (Python) with a strict service-layer separation.
- Vector storage must be Qdrant (self-hosted or managed).
- Primary relational data must be PostgreSQL (AWS RDS in production).
- Object storage must be AWS S3.
- Asynchronous *ingestion* processing must go through Amazon SQS and a dedicated Worker Service — no synchronous heavy processing in the API request path.
- The **query pipeline is agentic**: the LLM provider must support function/tool calling; the agent loop executes synchronously within the API request (streamed to the client), bounded by hard iteration/time limits — it does not go through SQS.
- Initial embedding model: `BAAI/bge-small-en-v1.5` via `sentence-transformers`.
- Initial LLM provider: OpenAI (a tool-calling-capable model), behind a provider-abstraction interface that models tool-calling generically.
- All infrastructure must be containerized (Docker) and deployable to ECS Fargate.

---

## 11. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Agent loop runs away in cost/latency (excessive tool calls) | High | Hard iteration cap, wall-clock timeout, per-user/per-KB query rate limits, circuit breaker. |
| LLM hallucination despite grounding and agentic verification | High | Strict prompt grounding rules, citation validation against actual tool-call results, "I don't know" fallback when evidence is insufficient. |
| Agent gets stuck in an unproductive search loop (repeating similar queries) | Medium | Deduplicate near-identical tool calls within a turn; instruct the agent to vary queries; cap iterations. |
| Embedding model quality insufficient for domain documents | Medium | Provider-abstracted embeddings; allow model upgrade path. |
| Cost overrun from LLM/embedding API usage (compounded by multi-call agent loop) | Medium-High | Token budgeting per turn, iteration caps, rate limits, usage quotas per plan tier, cost monitoring per query. |
| Large file processing timeouts | Medium | Async worker processing with retries and dead-letter queue. |
| Vector DB scaling bottlenecks at high tenant count | Medium | Per-KB collection/namespace strategy, sharding roadmap. |
| Security breach / cross-tenant data leakage, including via a maliciously-crafted agent tool call | Critical | Strict tenant-scoped queries enforced inside the tool implementation itself (not just the calling endpoint), automated tests for isolation, least-privilege IAM. |
| Vendor lock-in to OpenAI's tool-calling format | Low-Medium | Provider abstraction layer normalizes tool-calling from day one. |

---

## 12. Future Roadmap

**Phase 2+ (Post-MVP):**
- Additional agent tools: hybrid search (BM25 + vector), cross-encoder re-ranking as a callable tool, cross-Knowledge-Base search, document metadata/filter search.
- HyDE and query-decomposition as internal agent strategies/prompted behaviors rather than separate pipelines.
- Parent Document Retrieval and Contextual Compression as retrieval-tool enhancements.
- Agent self-critique step (verify draft answer against retrieved evidence before finalizing).
- Organization/team workspaces with RBAC.
- Shareable public/read-only Knowledge Bases.
- Additional LLM providers (Claude, Gemini) with per-KB model selection.
- Audio/video ingestion with transcription.
- Usage-based billing and subscription tiers, informed by per-query agent cost tracking.
- SOC 2 Type II compliance program.
- Terraform-managed infrastructure and multi-region deployment.

---

## 13. Product Scope

### In Scope (MVP)
- Auth (email/password, JWT).
- Knowledge Base CRUD.
- Document upload/delete for PDF, DOCX, TXT, MD.
- Async ingestion pipeline with status tracking.
- Chat CRUD within a Knowledge Base.
- **Agentic query pipeline**: LLM-driven agent loop with a bounded, tool-calling `search_knowledge_base` tool.
- Streamed, cited chat responses grounded in actual tool-call results.
- Optional agent step-trace visibility in the UI.
- Source excerpt viewer.
- Responsive web UI with dark mode.
- AWS deployment (ECS Fargate, S3, RDS, Qdrant, SQS, CloudWatch).

### Out of Scope (MVP)
- Team/org accounts.
- Billing/subscriptions.
- Non-English optimized retrieval.
- Mobile native apps.
- Public sharing of Knowledge Bases.
- Agent tools beyond knowledge-base search and chunk/document lookup.

---

## 14. Feature Prioritization (MoSCoW)

| Feature | Priority |
|---|---|
| Email/password auth with JWT | Must |
| Knowledge Base CRUD | Must |
| Document upload (PDF/DOCX/TXT/MD) | Must |
| Async ingestion (extraction, chunking, embedding) | Must |
| Document status tracking | Must |
| Chat creation and messaging | Must |
| **Agentic retrieval loop with bounded tool-calling** | Must |
| Streaming answers | Must |
| Citations with source excerpts, traceable to actual tool calls | Must |
| Agent step-trace UI | Should |
| Dark mode UI | Should |
| Multiple chats per KB | Must |
| Provider abstraction for LLM/embeddings with tool-calling support | Should |
| Hybrid search / re-ranking as agent tools | Could (Future) |
| Cross-KB search tool | Could (Future) |
| Agent self-critique/verification step | Could (Future) |
| Org/team workspaces | Won't (v1) |
| Billing | Won't (v1) |
| Public KB sharing | Won't (v1) |

---

## 15. Acceptance Criteria (MVP Definition of Done)

The MVP is considered complete when:

1. A new user can register, log in, and receive a valid JWT session.
2. A logged-in user can create a Knowledge Base and see it listed.
3. A user can upload a PDF/DOCX/TXT/MD file and see its status progress from Pending → Processing → Indexed.
4. A failed ingestion (e.g., corrupt file) surfaces a clear Failed status with an error reason.
5. A user can create a chat within a Knowledge Base and ask a question.
6. The system runs an agent loop that calls the `search_knowledge_base` tool at least once, and up to the configured max, deciding autonomously whether additional searches are needed before answering.
7. The system returns a streamed answer grounded in the uploaded documents, including at least one citation traceable to an actual tool-call result, when relevant content exists.
8. A question requiring two distinct pieces of information from different parts of a document (or different documents) triggers multiple, differently-worded tool calls, verified in a test scenario.
9. A question with no supporting content in the Knowledge Base results in an explicit "I couldn't find this in your documents" response after the agent exhausts its search budget — not a fabricated answer.
10. Clicking a citation shows the exact source excerpt and originating document.
11. A user can optionally expand a trace view showing the queries the agent issued and how many iterations it took.
12. A user can create multiple chats in the same Knowledge Base, each with independent history, sharing the same vector index and agent toolset.
13. Deleting a document removes it from S3, PostgreSQL, and Qdrant.
14. Deleting a Knowledge Base cascades correctly across all owned resources.
15. The agent loop never exceeds its configured max iterations or wall-clock timeout in testing, even when deliberately prompted toward an unproductive search pattern.
16. All services are deployed on AWS via Docker/ECS Fargate with CloudWatch logging and basic alarms configured, including agent iteration/cost metrics.
17. Cross-tenant data isolation is verified via automated tests (User A cannot query User B's Knowledge Base), including via directly-invoked agent tool calls in tests.