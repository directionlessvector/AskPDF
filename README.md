# AskPDF AI

An agentic RAG SaaS that lets users upload documents and chat with an LLM agent that autonomously decides what to search and when, rather than a fixed single-pass retrieval pipeline.

## What's Different

Unlike classic RAG (embed query → search once → generate), AskPDF uses a **bounded ReAct-style agent loop**: the LLM itself decides whether/what/how many times to search a Knowledge Base before answering. This handles multi-hop and ambiguous questions better than single-pass retrieval.

## Architecture

**Monorepo** with three services:
- **`apps/web`** — Next.js frontend (KB/document management, chat UI)
- **`apps/api`** — FastAPI service (auth, CRUD, agent orchestrator)
- **`apps/worker`** — Ingestion worker (SQS consumer for document processing)

**Two decoupled pipelines**:
1. **Ingestion** (async): upload → S3 → SQS → extract/chunk/embed → Qdrant + Postgres
2. **Query** (sync/streaming): user question → agent loop (1..N tool calls) → SSE stream → persist message + trace

**Infra**: PostgreSQL, Qdrant (vector DB, one collection per KB), S3 (local: LocalStack), SQS (ingestion queue only).

## Current Status

**Done** (Phase 0/1):
- Monorepo scaffold and `docker-compose.yml` with all services
- FastAPI skeleton with `/health` endpoint
- Next.js 15 frontend with Tailwind + shadcn/ui setup
- SQLAlchemy models for all 7 tables (users, knowledge_bases, documents, chunks, chats, messages, agent_steps)
- Alembic migration (verified against live Postgres)

**Not yet started** (Phase 2+):
- Auth endpoints
- KB/document/chat CRUD endpoints
- Document ingestion pipeline (extract, chunk, embed)
- Agent orchestrator and tools
- Frontend pages (auth, dashboard, chat UI)
- CI/CD pipeline

See [`docs/phases.md`](docs/phases.md) for the full implementation roadmap.

## Local Development

### Prerequisites
- Python 3.12+
- Node.js 18+
- Docker & Docker Compose
- Obsidian (optional, for developer knowledge base)

### Setup

1. **Clone and install**:
   ```bash
   git clone <repo>
   cd askpdf-ai
   pip install -e apps/api[dev]
   cd apps/web && npm install
   ```

2. **Boot local infra** (Postgres, Qdrant, LocalStack):
   ```bash
   docker compose up -d
   ```

3. **Run migrations**:
   ```bash
   cd apps/api && alembic upgrade head
   ```

4. **Start services**:
   ```bash
   # API
   cd apps/api && uvicorn app.main:app --reload
   # Frontend (new terminal)
   cd apps/web && npm run dev
   ```

Visit `http://localhost:3000` (frontend) and `http://localhost:8000/health` (API).

### Developer Knowledge Base

A personal knowledge base for this project (and future projects) lives at:
```
~/Documents/Obsidian/DeveloperBrain/Projects/AskPDF/
```

See `~/.claude/CLAUDE.md` for guidelines on using it alongside Claude Code.

## Docs

- [`architecture.md`](architecture.md) — detailed system design, data flow, decisions
- [`phases.md`](phases.md) — phased implementation plan (19 phases, MVP at Phase 13)
- [`prd.md`](prd.md) — product requirements and acceptance criteria
- [`rules.md`](rules.md) — coding conventions, patterns, testing requirements
- [`design.md`](design.md) — UI/UX design system

## Technology Stack

| Layer | Tech |
|-------|------|
| **Frontend** | Next.js 15, React 19, TypeScript, Tailwind CSS, shadcn/ui, TanStack Query |
| **API** | FastAPI, Pydantic, SQLAlchemy 2.0 (async), asyncpg |
| **Worker** | FastAPI, asyncpg, sentence-transformers, boto3, qdrant-client |
| **Database** | PostgreSQL 16, Qdrant (vector DB) |
| **Storage** | S3 (LocalStack in dev) |
| **Queue** | SQS (LocalStack in dev) |
| **LLM** | OpenAI (abstracted via provider interface) |

## License

MIT
