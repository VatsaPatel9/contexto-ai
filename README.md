# Contexto - AI Tutor Chatbot

A learning-first AI tutor chatbot for gateway STEM courses (Biology, Calculus, Differential Equations) deployed as part of PA-STEM-PA. Created by Dr. Vatsa Patel.

Contexto helps students learn through guided questions, hints, and Socratic dialogue rather than giving direct answers. It uses RAG (Retrieval-Augmented Generation) over instructor-uploaded course materials to provide accurate, citation-backed tutoring.

## Architecture

```
Students (Browser)
       |
   [Nginx :80]  ── reverse proxy
       |
  ┌────┴────────────────────────────────┐
  │         frontend (SvelteKit)         │
  │  Port 5173 (dev) / static build     │
  │  - Chat interface                   │
  │  - Admin panel                      │
  │  - User profile                     │
  │  - Document upload                  │
  │  - Dark/light/OLED themes           │
  └────┬────────────────────────────────┘
       │ fetch() with SuperTokens cookies
  ┌────┴────────────────────────────────┐
  │      backend (FastAPI + Python)     │
  │  Port 8000                          │
  │  - Chat pipeline (SSE streaming)    │
  │  - RAG retrieval (pgvector)         │
  │  - PII scrubbing                    │
  │  - Prompt injection detection       │
  │  - Output validation                │
  │  - Risk escalation                  │
  │  - Document upload + embedding      │
  │  - Admin & profile APIs             │
  └────┬────────────────────────────────┘
       │
  ┌────┴────────────────────────────────┐
  │          Infrastructure             │
  │  PostgreSQL 16 + pgvector           │
  │  Redis 7                            │
  │  SuperTokens (auth, RBAC)           │
  │  OpenAI API (GPT-4o-mini + embeds)  │
  └─────────────────────────────────────┘
```

## Project Structure

```
.
├── backend/                  # FastAPI backend (Python)
│   ├── main.py               # App entry point
│   ├── config.py             # Settings (loads .env)
│   ├── database.py           # SQLAlchemy + pgvector setup
│   ├── auth/                 # SuperTokens config, dependencies, roles
│   ├── routers/
│   │   ├── chat.py           # POST /api/chat-messages (SSE)
│   │   ├── documents.py      # Document upload/list/delete
│   │   ├── profile.py        # GET/PUT /api/me
│   │   ├── admin.py          # User management, roles, bans
│   │   └── parameters.py     # GET /api/parameters (UI config)
│   ├── pipeline/
│   │   └── orchestrator.py   # Core chat pipeline
│   ├── pipeline_filters/     # PII, injection, offensive, output validation
│   ├── rag/                  # Retriever, vectorstore, embeddings, splitter
│   ├── llm/                  # OpenAI client, humanizer
│   ├── models/               # SQLAlchemy models
│   ├── schemas/              # Pydantic request/response schemas
│   ├── services/             # Escalation, analytics, auth
│   └── tutor_persona.md      # System prompt (Contexto persona)
│
├── frontend/                  # SvelteKit frontend
│   ├── src/
│   │   ├── routes/
│   │   │   ├── +page.svelte          # New chat
│   │   │   ├── c/[id]/+page.svelte   # Existing chat
│   │   │   ├── login/+page.svelte    # Sign in / sign up
│   │   │   ├── admin/+page.svelte    # Admin panel
│   │   │   └── profile/+page.svelte  # User profile
│   │   └── lib/
│   │       ├── apis/                 # Backend API clients
│   │       ├── auth/                 # SuperTokens SDK init
│   │       ├── stores/               # Svelte stores (auth, session, theme)
│   │       └── components/
│   │           ├── chat/             # Chat UI components
│   │           └── layout/           # Sidebar, Navbar
│   └── package.json          # ~15 dependencies (lightweight)
│
├── docker-compose.dev.yaml   # Dev stack (Postgres, Redis, SuperTokens, backend, nginx)
├── docker/                   # Docker init scripts
├── nginx/                    # Nginx reverse proxy config
├── content_packs/            # Course material uploads
└── tests/                    # Test suites
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | SvelteKit 2, Svelte 5, Tailwind CSS v4, TypeScript |
| Backend | FastAPI, SQLAlchemy, asyncio, SSE streaming |
| LLM | OpenAI GPT-4o-mini (chat), text-embedding-ada-002 (RAG) |
| Vector DB | PostgreSQL 16 + pgvector (cosine similarity) |
| Auth | SuperTokens (email/password, RBAC, session cookies) |
| Cache | Redis 7 |
| Proxy | Nginx |
| Container | Docker Compose |

## Quick Start

### Prerequisites
- Docker Desktop
- Node.js 18+
- Python 3.12+
- OpenAI API key

### 1. Start infrastructure
```bash
docker compose -f docker-compose.dev.yaml up -d
```
This starts PostgreSQL, Redis, and SuperTokens.

### 2. Start the backend
```bash
cd backend
cp .env.example .env   # Add your OPENAI_API_KEY
uv venv && uv pip install -r requirements.txt
cd ..
backend/.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 3. Start the frontend
```bash
cd frontend
npm install
npm run dev
```
Open http://localhost:5173

## Key Features

### Chat
- SSE streaming responses with markdown rendering
- Code syntax highlighting (highlight.js)
- LaTeX math rendering (KaTeX)
- Citation badges from RAG sources
- Conversation history (persisted in PostgreSQL)
- Like/dislike feedback on responses

### Safety Pipeline
- PII detection and scrubbing (email, phone, SSN, student ID)
- Prompt injection detection (12+ attack patterns)
- Offensive language filtering
- Output validation (prevents answer leaks, persona drift)
- Risk escalation (frustration, distress, integrity concerns)

### Pedagogy
- Message classification (homework, conceptual, procedural, meta)
- "Attempt first" enforcement for homework questions
- Progressive hint levels (increases with conversation turns)
- Socratic questioning approach

### Admin Panel
- User search with role management (super_admin, admin, user_uploader)
- Document upload permission toggle with limits
- Token usage tracking with budget limits
- Per-user document management (list, soft-delete)
- Violation tracking and ban/unban

### Document Upload
- PDF, DOCX, TXT, MD, CSV, XLSX support
- Automatic text extraction, chunking, and embedding
- Vision extraction for PDF images (GPT-4o)
- Visibility: global (admin) or private (user)
- Upload limits enforced per-user

### Auth & RBAC
- SuperTokens email/password authentication
- Role-based access: super_admin, admin, user_uploader, user
- Permission-gated endpoints
- httpOnly session cookies (no tokens in localStorage)

### UI
- Dark mode, light mode, OLED dark mode, system auto
- Responsive (mobile sidebar collapse)
- Open WebUI-inspired design
- Theme dropdown with 4 options

## Environment Variables

### Backend (`backend/.env`)
```
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://tutor_dev@localhost:5432/ai_tutor
SUPERTOKENS_CONNECTION_URI=http://localhost:3567
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-ada-002
CORS_ALLOW_ORIGINS=http://localhost:5173,http://localhost
```

### Frontend (`frontend/.env`)
```
VITE_API_BASE_URL=http://localhost:8000
```

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/chat-messages` | User | Send message (SSE stream) |
| GET | `/api/conversations` | User | List conversations |
| GET | `/api/conversations/:id` | User | Get conversation |
| DELETE | `/api/conversations/:id` | User | Delete conversation |
| GET | `/api/messages` | User | List messages |
| POST | `/api/messages/:id/feedbacks` | User | Like/dislike |
| GET | `/api/parameters` | Public | UI config |
| GET | `/api/me` | User | Profile + email |
| PUT | `/api/me` | User | Update display name |
| POST | `/api/datasets/:course/documents/upload` | Uploader | Upload document |
| GET | `/api/datasets/:course/documents` | User | List documents |
| DELETE | `/api/datasets/:course/documents/:id` | Owner/Admin | Soft-delete document |
| GET | `/api/admin/users` | Admin | List users by role |
| GET | `/api/admin/users/:id/profile` | Admin | User profile details |
| POST | `/api/admin/users/:id/role` | Super Admin | Assign role |
| DELETE | `/api/admin/users/:id/role` | Super Admin | Remove role |
| POST | `/api/admin/users/:id/ban` | Admin | Ban user |
| POST | `/api/admin/users/:id/unban` | Admin | Unban user |