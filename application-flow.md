# Application Architecture & Flow

> **Project:** general_bot — Multi-Tenant RAG Chatbot with Admin Console  
> **Stack:** Python 3.12, Flask 3.0, LangChain 0.2, ChromaDB, Celery 5.4, Redis, SQLite  
> **Pattern:** Clean Architecture (Hexagonal) with Microservice Decomposition

---

## 1. Application Bootstrap

The bootstrap sequence defines how the system initialises from cold start, covering process startup, dependency wiring, and infrastructure readiness.

### 1.1 Container Orchestration

Docker Compose manages five cooperating services with explicit dependency ordering:

```
redis ──> vectordb ──> valr-bot ──> worker
                                  ──> beat
```

| Service   | Image / Build     | Entry Point                              | Port  | Role                                  |
|-----------|-------------------|------------------------------------------|-------|---------------------------------------|
| `redis`   | `redis:7-alpine`  | `redis-server`                           | 6379  | Message broker for Celery             |
| `vectordb`| `./vectordb/`     | `gunicorn app:app` (1 worker, 300s t/o)  | 5001  | ChromaDB vector search microservice   |
| `valr-bot`| `./Dockerfile`    | `gunicorn app:app` (1 worker, 120s t/o)  | 5000  | Main Flask application                |
| `worker`  | `./Dockerfile`    | `celery -A vac_bot.tasks worker`         | —     | Async task consumer (Celery)          |
| `beat`    | `./Dockerfile`    | `celery -A vac_bot.tasks beat`           | —     | Scheduled task trigger (Celery Beat)  |

### 1.2 Application Initialisation (`app.py`)

```
┌──────────────────────────────────────────────────────────────┐
│  Flask.create_app()                                          │
│                                                              │
│  1. Instantiate Flask(__name__)                              │
│  2. Configure secret_key from FLASK_SECRET_KEY env           │
│  3. Enter app context:                                       │
│     └─ init_db() → create tables, run migrations, seed data  │
│  4. Initialise API layer:                                    │
│     ├─ FlaskSessionProvider (wraps flask.session)            │
│     ├─ AuthHandler(session_provider)                         │
│     ├─ ChatHandler(session_provider)                         │
│     └─ AdminHandler()                                        │
│  5. Register admin Blueprint at /admin                       │
│  6. Register before_request middleware:                      │
│     └─ set_tenant_context() → g.tenant_id                   │
│  7. Register context_processor:                              │
│     └─ inject_globals() → template globals                  │
│  8. Ready to serve (gunicorn)                                │
└──────────────────────────────────────────────────────────────┘
```

**Key behaviours during bootstrap:**

- **Database initialisation** (`db.py:init_db`): Creates all 8 tables (`tenants`, `users`, `settings`, `urls`, `documents`, `index_log`, `curator_queue`, `source_snapshots`), applies schema migrations, and seeds a default tenant with baseline settings.
- **Multi-tenancy context**: `set_tenant_context()` extracts `tenant_id` from the user session or falls back to the default tenant, storing it in `flask.g` for downstream access.
- **Template globals**: `inject_globals()` injects `admin_brand_name` and `is_logged_in` into every Jinja2 template.

### 1.3 Celery Task Infrastructure (`vac_bot/tasks.py`)

Celery is configured with Redis as both broker and result backend. The beat scheduler is pre-configured with one recurring task:

```python
beat_schedule = {
    "nightly-change-detection": {
        "task": "vac_bot.tasks.run_change_detection_task",
        "schedule": 86400,  # Once per 24 hours
    },
}
```

Available async tasks:

| Task                              | Trigger        | Description                                |
|-----------------------------------|----------------|--------------------------------------------|
| `run_change_detection_task`       | Celery Beat    | Scans all URLs/documents for content drift |
| `run_reindex_task(source_type, …)`| Manual / Chain | Re-indexes a changed source into ChromaDB  |

---

## 2. User Request → Response Flow

### 2.1 High-Level Request Lifecycle

```
Client (Browser)                    Flask App                     Services / Microservices
     │                                  │                                │
     │─── HTTP Request ──────────────►  │                                │
     │                                  │                                │
     │                                  ├── before_request               │
     │                                  │   └─ set_tenant_context()      │
     │                                  │                                │
     │                                  ├── Route Handler                │
     │                                  │   ├─ auth routes  ──► AuthHandler
     │                                  │   ├─ chat routes  ──► ChatHandler
     │                                  │   ├─ admin routes ──► AdminHandler
     │                                  │   └─ health       ──► direct    │
     │                                  │                                │
     │                                  ├── API Handler                  │
     │                                  │   ├─ validates DTOs            │
     │                                  │   ├─ calls service layer       │
     │                                  │   └─ returns result            │
     │                                  │                                │
     │                                  ├── Response                     │
     │                                  │   ├─ JSON for XHR endpoints    │
     │                                  │   └─ HTML for page renders     │
     │◄──── HTTP Response ─────────────┘                                │
```

### 2.2 Route Table

#### Public Routes (`app.py`)

| Method | Path              | Handler              | Description                    |
|--------|-------------------|----------------------|--------------------------------|
| GET    | `/`               | `index()`            | Landing page or chat UI        |
| POST   | `/ask`            | `ask_question()`     | Chat query → RAG response      |
| GET    | `/login`          | `user_login()`       | User login page                |
| POST   | `/login`          | `user_login()`       | User login submission          |
| GET    | `/signup`         | `signup()`           | Registration page              |
| POST   | `/signup`         | `signup()`           | Registration submission        |
| POST   | `/logout`         | `user_logout()`      | Terminate session              |
| GET    | `/change_password`| `change_password()`  | Password change page           |
| POST   | `/change_password`| `change_password()`  | Password change submission     |
| GET    | `/health`         | `health()`           | Health check                   |

#### Admin Routes (`admin.py`, Blueprint at `/admin`)

| Method | Path                                  | Handler              | Description                |
|--------|---------------------------------------|----------------------|----------------------------|
| *      | `/admin/login`                        | `login()`            | Admin authentication       |
| *      | `/admin/logout`                       | `logout()`           | Admin session termination  |
| GET    | `/admin/`                             | `dashboard()`        | Stats & metrics overview   |
| *      | `/admin/settings`                     | `settings()`         | Bot personality/SKU config |
| GET    | `/admin/avatar/<tid>`                 | `tenant_avatar()`    | Serve bot avatar image     |
| GET    | `/admin/knowledge`                    | `knowledge()`        | Knowledge base dashboard   |
| POST   | `/admin/knowledge/url/add`            | `add_url()`          | Add knowledge source URL   |
| POST   | `/admin/knowledge/url/<id>/delete`    | `delete_url()`       | Remove knowledge URL       |
| POST   | `/admin/knowledge/doc/upload`         | `upload_doc()`       | Upload knowledge document  |
| POST   | `/admin/knowledge/doc/<id>/delete`    | `delete_doc()`       | Delete knowledge document  |
| POST   | `/admin/knowledge/rebuild`            | `rebuild()`          | Rebuild vector index       |
| GET    | `/admin/curator`                      | `curator()`          | Curator queue dashboard    |
| POST   | `/admin/curator/scan`                 | `curator_scan()`     | Trigger change detection   |
| POST   | `/admin/curator/item/<id>/action`     | `curator_item_action`| Approve/dismiss queue item |
| GET    | `/admin/access`                       | `access()`           | User management page       |
| POST   | `/admin/access/users/add`             | `add_user()`         | Invite/register user       |
| POST   | `/admin/access/users/<id>/edit`       | `edit_user()`        | Modify user role           |
| POST   | `/admin/access/users/<id>/delete`     | `delete_user()`      | Remove user                |
| *      | `/admin/tenants/new`                  | `new_tenant()`       | Create tenant              |
| GET    | `/admin/tenants`                      | `tenants()`          | List tenants               |
| *      | `/admin/tenants/<id>/edit`            | `edit_tenant()`      | Edit tenant configuration  |
| POST   | `/admin/tenants/<id>/delete`          | `delete_tenant()`    | Remove tenant              |

#### VectorDB Microservice Routes (`vectordb/app.py`)

| Method | Path        | Handler     | Description                            |
|--------|-------------|-------------|----------------------------------------|
| GET    | `/health`   | `health()`  | ChromaDB health check + collection info|
| POST   | `/search`   | `search()`  | k-NN similarity search with scores     |
| POST   | `/rebuild`  | `rebuild()` | Full index rebuild from document batch |
| POST   | `/clear`    | `clear()`   | Clear collection (global or per-tenant)|

### 2.3 Detailed Flow: Chat Query (End-to-End)

This is the most important flow — a user asks a question and receives an LLM-generated, RAG-grounded answer.

```
User Browser                         Flask App                                 VectorDB                    OpenAI API
     │                                   │                                         │                          │
     │  POST /ask                        │                                         │                          │
     │  {"question": "…",                │                                         │                          │
     │   "session_id": "…"}              │                                         │                          │
     │──────────────────────────────────►│                                         │                          │
     │                                   │                                         │                          │
     │                                   │  before_request                         │                          │
     │                                   │  └─ g.tenant_id = session["tenant_id"]  │                          │
     │                                   │                                         │                          │
     │                                   │  ChatHandler.ask_question(request)      │                          │
     │                                   │  └─ Runs async ask() in ThreadPool      │                          │
     │                                   │     (Flask sync wrapper pattern)        │                          │
     │                                   │                                         │                          │
     │                                   │  vac_bot/chain.py:ask()                 │                          │
     │                                   │   1. Rebuild chain if staleness         │                          │
     │                                   │   2. Build RAG prompt template          │                          │
     │                                   │      ├─ System: personality + tone      │                          │
     │                                   │      ├─ Context: retrieved documents    │                          │
     │                                   │      └─ Question: user input            │                          │
     │                                   │                                         │                          │
     │                                   │  ── POST /search ─────────────────────►│                          │
     │                                   │     {"query": "…",                     │                          │
     │                                   │      "tenant_id": N,                   │                          │
     │                                   │      "k": 12}                          │                          │
     │                                   │                                         │                          │
     │                                   │                                         │── embedding ────────────►│
     │                                   │                                         │◄── vectors ──────────────│
     │                                   │                                         │                          │
     │                                   │     ChromaDB similarity_search         │                          │
     │                                   │     (collection: kb_{tenant_id})        │                          │
     │                                   │                                         │                          │
     │                                   │  ◄── top-k results ───────────────────│                          │
     │                                   │                                         │                          │
     │                                   │   3. Inject citations from metadata     │                          │
     │                                   │   4. Call ChatOpenAI (gpt-4o-mini) ────│─────────────►───────────►│
     │                                   │      prompt + context                   │                          │
     │                                   │   5. Parse answer, extract citations    │                          │
     │                                   │   6. Log attribution to DB              │                          │
     │                                   │   7. Count tokens (tiktoken)            │                          │
     │                                   │                                         │                          │
     │                                   │  ◄── Async result ─────────────────────│                          │
     │                                   │                                         │                          │
     │  ◄── JSON Response ──────────────│                                         │                          │
     │      {                            │                                         │                          │
     │        "answer": "…",             │                                         │                          │
     │        "sources": […],            │                                         │                          │
     │        "tokens": {                │                                         │                          │
     │          "prompt": N,             │                                         │                          │
     │          "completion": M          │                                         │                          │
     │        }                          │                                         │                          │
     │      }                            │                                         │                          │
```

**RAG Prompt Template Structure:**

```
System: You are {bot_name}, a {personality} assistant.
Tone: {tone} | Purpose: {purpose}
Instructions: {instructions}

Context:
Source 1: [title](url) — content excerpt …
Source 2: [title](url) — content excerpt …
…

Question: {user_question}
```

### 2.4 Authentication Flow

Two credential domains exist, resolved through an abstract `Authenticator` base class and `AuthFactory` singleton:

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐
│  HTTP Request │────►│ AuthFactory   │────►│ AdminAuthenticator│
│  (admin/*)    │     │ (singleton)   │     │ (env vars check) │
└──────────────┘     └───────────────┘     └──────────────────┘
                            │
┌──────────────┐            │             ┌──────────────────┐
│  HTTP Request │───────────┼────────────►│ UserAuthenticator │
│  (user/*)     │                         │ (DB + werkzeug)  │
└──────────────┘                          └──────────────────┘
```

| Flow     | Authenticator         | Credential Source              | Session Storage    |
|----------|-----------------------|--------------------------------|--------------------|
| Admin    | `AdminAuthenticator`  | `ADMIN_USERNAME` / `ADMIN_PASSWORD` env vars | `flask.session`    |
| User     | `UserAuthenticator`   | `users` table (bcrypt hash)    | `flask.session`    |

**Authentication sequence:**

1. Route receives POST with credentials → `AuthHandler.login()`
2. `AuthHandler` delegates to `AuthService.login_user()` or `AuthService.login_admin()`
3. `AuthService` gets the appropriate `Authenticator` from `AuthFactory`
4. `Authenticator.authenticate(credentials)` validates against source
5. On success: `AuthService` calls `SessionProvider.set_auth()` → `flask.session` updated
6. Response returned (JSON redirect instruction or rendered template)

---

## 3. Database Flow

### 3.1 Architecture Overview

A single SQLite file (`instance/admin.db`) stores all relational data. The vector store (ChromaDB) runs as a separate microservice. No ORM is used — raw `sqlite3` with `Row` factory provides the database interface.

```
┌──────────────────────────────────────────────────────────────────┐
│                    SQLite (instance/admin.db)                     │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐│
│  │ tenants  │  │  users   │  │ settings │  │ urls             ││
│  │──────────│  │──────────│  │──────────│  │──────────────────││
│  │ id (PK)  │  │ id (PK)  │  │ tenant_id│  │ id (PK)          ││
│  │ name     │  │ tenant_id│  │ bot_name │  │ tenant_id (FK)   ││
│  │ slug     │  │ username │  │ theme    │  │ url              ││
│  │ status   │  │ hash     │  │ language │  │ content_hash     ││
│  └──────────┘  │ role     │  │ persona  │  │ crawl_frequency  ││
│                │ created  │  │ tone     │  │ last_indexed_at  ││
│                └──────────┘  │ purpose  │  └──────────────────┘│
│                              │ instruc. │                       │
│  ┌──────────────────┐       │ avatar   │  ┌──────────────────┐│
│  │ documents        │       └──────────┘  │ index_log        ││
│  │──────────────────│                      │──────────────────││
│  │ id (PK)          │                      │ id (PK)          ││
│  │ tenant_id (FK)   │  ┌──────────────────┐│ tenant_id        ││
│  │ filename         │  │ curator_queue    ││ started_at       ││
│  │ filepath         │  │──────────────────││ completed_at     ││
│  │ content_hash     │  │ id (PK)          ││ total_chunks     ││
│  │ status           │  │ tenant_id        ││ status           ││
│  │ doc_type         │  │ source_type      │└──────────────────┘│
│  └──────────────────┘  │ source_id        │                    │
│                         │ change_reason    │  ┌────────────────┐│
│  ┌──────────────────┐   │ status           │  │source_snapshots││
│  │ source_snapshots │   │ priority         │  │ (same schema)  ││
│  │──────────────────│   └──────────────────┘  │ — archived     ││
│  │ id (PK)          │                        └────────────────┘│
│  │ source_type      │                                            │
│  │ content_hash     │                                            │
│  │ etag             │                                            │
│  │ last_modified    │                                            │
│  └──────────────────┘                                            │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                  ChromaDB (vectordb/chroma/)                      │
│                                                                  │
│   Collection: kb_{tenant_id}                                     │
│   ┌─────────────────────────────────────────────────────────────┐│
│   │ Document: {chunk_id}                                        ││
│   │   content: chunk text                                       ││
│   │   metadata: {tenant_id, source_type, source_id,             ││
│   │              title, url, page, chunk_index}                  ││
│   │   embedding: vector (text-embedding-ada-002)                ││
│   └─────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Connection Management (`db.py`)

```python
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row          # Dict-like row access
    conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")   # Referential integrity
    conn.execute("PRAGMA busy_timeout=30000")# 30s busy wait
    return conn
```

Each query function calls `get_conn()`, uses it, and relies on context manager or explicit close for teardown.

### 3.3 Data Access Layer

```
┌──────────────────────────────────────────────────────────────┐
│                     Data Access Layers                         │
│                                                               │
│   ┌─────────────────────────────────────────────────────┐     │
│   │  Repository Layer (repositories/)                    │     │
│   │                                                      │     │
│   │  Repository[T] (ABC)                                 │     │
│   │    ├── get_by_id(id) → T                             │     │
│   │    └── save(entity) → T                              │     │
│   │                                                      │     │
│   │  UserRepository implements Repository[User]          │     │
│   │    ├── get_by_username(name)                         │     │
│   │    ├── get_by_username_and_tenant(name, tid)         │     │
│   │    ├── list_by_tenant(tid)                           │     │
│   │    ├── exists_by_username(name, tid) → bool          │     │
│   │    ├── update_role(id, role)                         │     │
│   │    ├── update_password(id, hash)                     │     │
│   │    └── delete(id)                                    │     │
│   │                                                      │     │
│   │  TenantRepository implements Repository[Tenant]      │     │
│   │    ├── get_default()                                 │     │
│   │    ├── list_all()                                    │     │
│   │    ├── update_name(id, name)                         │     │
│   │    └── delete(id)                                    │     │
│   └─────────────────────────────────────────────────────┘     │
│                                                               │
│   ┌─────────────────────────────────────────────────────┐     │
│   │  Domain Models (models/) — Dataclasses, not ORM     │     │
│   │                                                      │     │
│   │  @dataclass User                                     │     │
│   │    id, tenant_id, username, password_hash, role,     │     │
│   │    created_at, updated_at                            │     │
│   │    @classmethod from_row(row) → User                 │     │
│   │    @property is_admin() → bool                       │     │
│   │                                                      │     │
│   │  @dataclass Tenant                                   │     │
│   │    id, name, slug, status, created_at, updated_at    │     │
│   │    @classmethod from_row(row) → Tenant               │     │
│   └─────────────────────────────────────────────────────┘     │
│                                                               │
│   ┌─────────────────────────────────────────────────────┐     │
│   │  Direct SQL Helpers (db.py)                          │     │
│   │                                                      │     │
│   │  get_settings(tenant_id) → dict                      │     │
│   │  get_tenant(tenant_id) → Row                         │     │
│   │  get_tenant_id_from_name(name) → int                 │     │
│   │  mark_indexed(...)                                   │     │
│   │  log_index(...)                                      │     │
│   │  get_user_count(tenant) → int                        │     │
│   │  get_doc_count(tenant) → int                         │     │
│   │  get_url_count(tenant) → int                         │     │
│   │  get_curator_count(tenant, status) → int             │     │
│   │  + 20+ curator_queue CRUD helpers                    │     │
│   └─────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 Schema Migrations (`db.py:migrate_db`)

Migrations are applied sequentially in `init_db()`, using `ALTER TABLE` statements guarded by existence checks. The current migration set adds columns for content versioning, crawling metadata, and tracking fields:

| Target Table   | Added Columns                                        |
|----------------|------------------------------------------------------|
| `settings`     | `language`, `bot_avatar`                             |
| `documents`    | `version`, `content_hash`, `crawl_frequency`, `crawl_history_json`, `crawl_last_run`, `change_count` |
| `urls`         | `version`, `content_hash`, `crawl_frequency`, `crawl_history_json`, `crawl_last_run`, `change_count` |
| `users`        | `created_at`, `updated_at`                           |
| `tenants`      | `created_at`, `updated_at`                           |

### 3.5 Vector Database Flow

The vector database is a dedicated microservice to isolate ChromaDB's resource profile and avoid blocking the main app:

```
┌─────────────────┐     POST /rebuild      ┌─────────────────────┐
│  vac_bot/loader  │──────────────────────►│  vectordb/app.py    │
│                  │  {documents: […]}     │                     │
│  1. Scrape URLs  │                       │  1. Parse documents │
│  2. Parse PDFs   │                       │  2. Embed (OpenAI)  │
│  3. Chunk docs   │                       │  3. Upsert ChromaDB │
│  4. Collect →    │                       │     (collection:    │
│                  │                       │      kb_{tenant_id})│
│                  │     POST /search      │                     │
│  vac_bot/chain   │──────────────────────►│                     │
│                  │  {query, tenant_id, k}│  1. Embed query     │
│                  │                       │  2. similarity_     │
│                  │     top-k results ◄───│     search_with_    │
│                  │                       │     score           │
└─────────────────┘                       └─────────────────────┘
```

Collection naming convention: `kb_{tenant_id}` for per-tenant isolation. The default collection (`langchain`) is used for fallback.

---

## 4. Content Curation & Change Detection Flow

A nightly scheduled pipeline detects content drift in knowledge sources and queues re-index jobs:

```
Celery Beat                Celery Worker                      System
(Every 24h)                (vac_bot/tasks.py)                    │
     │                          │                                │
     │  run_change_detection    │                                │
     │─────────────────────────►│                                │
     │                          │                                │
     │                          │  For each source (URL/doc):    │
     │                          │  ──────────────────────────     │
     │                          │  1. Fetch current content      │
     │                          │  2. Compute SHA-256 hash       │
     │                          │  3. Compare with snapshot      │
     │                          │     (source_snapshots table)   │
     │                          │                                │
     │                          │  if changed:                    │
     │                          │  ┌────────────────────────────┐│
     │                          │  │ 4. Insert into curator_    ││
     │                          │  │    queue (status: pending) ││
     │                          │  │ 5. Update snapshot hash    ││
     │                          │  │ 6. Adapt crawl frequency   ││
     │                          │  │    (faster if churn high)  ││
     │                          │  └────────────────────────────┘│
     │                          │                                │
     │                          │  if unchanged:                  │
     │                          │  └─ Skip, possibly backoff     │
     │                          │     crawl frequency            │
     │                          │                                │
```

Admin can then review queue items via the Curator dashboard (`/admin/curator`) and approve or dismiss each change. Approved changes trigger `run_reindex_task`, which re-downloads the source, re-chunks, and rebuilds the relevant portion of the vector index.

---

## 5. Multi-Modal Processing Pipeline

When documents contain images, tables, or slides, a specialised pipeline extracts structured content:

```
Uploaded File
     │
     ├── PDF (scanned) ──► PyMuPDF (fitz) extract pages ──► GPT-4o vision OCR ──► text
     ├── Image (png/jpg) ──► GPT-4o vision analysis ──► structured description
     ├── XLSX/CSV ──► openpyxl / csv ──► markdown table
     ├── PPTX ──► python-pptx ──► slide text per slide
     └── PDF (text) ──► pypdf extract ──► plain text
                │
                ▼
     RecursiveCharacterTextSplitter
     (chunk_size=1000, chunk_overlap=200)
                │
                ▼
     Embed + Index → ChromaDB
```

---

## 6. Asynchronous Task Processing

Celery provides async execution for long-running operations, preventing Flask worker blocking:

| Task                     | Queue | Typical Duration | Trigger              |
|--------------------------|-------|-----------------|----------------------|
| Change detection (full)  | default | 30s–5min     | Celery Beat (24h)    |
| URL content refresh      | default | 5s–30s        | Curator approval     |
| Document re-index        | default | 10s–2min       | Curator approval     |
| Vector DB full rebuild   | default | 1min–10min     | Admin manual action  |

**Execution model:** Flask submits tasks with `delay()` or `apply_async()` and returns immediately. Results are not awaited — the system relies on the curator queue for tracking.

---

## 7. Architecture Principles

| Principle    | Implementation                                                    |
|-------------|-------------------------------------------------------------------|
| **Separation of Concerns** | `models/` (data), `repositories/` (access), `auth/` (strategy), `services/` (orchestration), `api/handlers/` (business logic) — each with a single responsibility |
| **Open/Closed** | `Authenticator` ABC allows new authentication methods (OAuth, SSO, SAML) without modifying existing implementations |
| **Liskov Substitution** | `AdminAuthenticator` and `UserAuthenticator` are interchangeable through the `Authenticator` interface |
| **Interface Segregation** | Repository interfaces expose focused methods; `AuthService` provides separate `login_user()` / `login_admin()` |
| **Dependency Inversion** | Routes depend on `AuthService` abstraction; handlers depend on `SessionProvider` interface; repositories depend on `Repository[T]` generic |
| **Multi-Tenancy** | All data scoped by `tenant_id`; per-tenant ChromaDB collections (`kb_{tenant_id}`); tenant context injected via `before_request` middleware |
| **Microservice Decomposition**| Vector database operates as an independent HTTP service, decoupled from the main Flask application |

---

## 8. Configuration & Environment

| Variable                | Default                                      | Scope        |
|-------------------------|----------------------------------------------|-------------|
| `OPENAI_API_KEY`        | *(required)*                                 | Chat + Embed |
| `FLASK_SECRET_KEY`      | `valr-bot-dev-key-change-in-prod`            | Flask session|
| `ADMIN_USERNAME`        | `admin`                                      | Admin auth   |
| `ADMIN_PASSWORD`        | `admin123`                                   | Admin auth   |
| `VEKTORDB_URL`          | `http://vectordb:5001`                       | Chat module  |
| `REDIS_URL`             | `redis://redis:6379/0`                       | Celery broker|
| `CELERY_BROKER_URL`     | `redis://redis:6379/0`                       | Celery       |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/0`                       | Celery       |
| `FLASK_DEBUG`           | `1`                                          | Development  |
