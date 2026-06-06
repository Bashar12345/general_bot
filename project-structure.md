# Project Structure

```
general_bot/
│
├── .dockerignore
├── .env
├── .gitignore
├── .github/workflows/
│   └── ci.yml                         # CI workflow definition
│
├── .vscode/
│   └── settings.json                  # VS Code workspace settings
│
├── admin.py                           # Flask admin Blueprint — all admin routes
├── api/                               # API layer (interface, DTO, handlers, Flask adapters)
│   ├── __init__.py
│   ├── dto.py                         # Data Transfer Objects (request/response dataclasses)
│   ├── interfaces.py                  # Abstract interfaces (SessionProvider, etc.)
│   ├── flask/
│   │   └── adapters.py                # Flask-specific implementations of interfaces
│   └── handlers/
│       ├── admin_handler.py           # Admin business logic (settings, tenants, access, knowledge)
│       ├── auth_handler.py            # Auth business logic (login, signup, logout)
│       └── chat_handler.py            # Chat business logic (ask question)
│
├── app.py                             # Main Flask app — entry point, routes, context processors
├── auth/                              # Authentication layer
│   ├── __init__.py
│   ├── admin_auth.py                  # Admin authentication logic
│   ├── authenticator.py               # Base authenticator
│   ├── factory.py                     # Auth factory
│   └── user_auth.py                   # User authentication logic
│
├── db.py                              # SQLite database — init, migration, queries
├── docker-compose.yml                 # Docker Compose orchestration
├── Dockerfile                         # Main app Docker image
│
├── instance/
│   └── admin.db                       # SQLite database file (runtime data)
│
├── models/                            # SQLAlchemy ORM models
│   ├── __init__.py
│   ├── tenant.py
│   └── user.py
│
├── readme.md
├── repositories/                      # Data access / repository layer
│   ├── __init__.py
│   ├── base.py
│   ├── tenant_repo.py
│   └── user_repo.py
│
├── requirements.txt
├── services/                          # Business logic services
│   ├── __init__.py
│   └── auth_service.py
│
├── static/                            # Static assets
│   ├── admin.css                      # Admin panel main styles
│   ├── admin_access.css               # Access page styles
│   ├── admin_knowledge.css            # Knowledge base modal styles
│   ├── admin_knowledge.js             # Knowledge base delete modal JS
│   ├── admin_login.css                # Admin login page styles
│   ├── auth.css                       # User auth pages styles
│   ├── chat.css                       # Chat interface styles
│   ├── chat.js                        # Chat interface JS
│   ├── landing_page.css               # Landing page styles
│   └── landing.js                     # Landing page JS
│
├── templates/                         # Jinja2 HTML templates
│   ├── landing.html                   # Public landing page
│   ├── vac_chat.html                  # Chat interface page
│   ├── admin/                         # Admin panel (10 templates)
│   │   ├── access.html                # User/role management
│   │   ├── base.html                  # Admin layout — sidebar, flash messages
│   │   ├── curator.html               # Curator queue & change detection
│   │   ├── dashboard.html             # Stats overview
│   │   ├── edit_tenant.html           # Edit tenant form
│   │   ├── knowledge.html             # URLs & document management
│   │   ├── login.html                 # Admin sign-in
│   │   ├── new_tenant.html            # Create tenant form
│   │   ├── settings.html              # Bot settings (name, theme, language, personality)
│   │   └── tenants.html               # Tenant listing
│   └── user/                          # User-facing auth (4 templates)
│       ├── auth_base.html             # User auth pages layout
│       ├── change_password.html       # Password change form
│       ├── login.html                 # User sign-in
│       └── signup.html                # User registration
│
├── tests/                             # Pytest test suite
│   ├── conftest.py                    # Shared fixtures
│   ├── test_chain.py
│   ├── test_curator.py
│   ├── test_curator_admin.py
│   ├── test_loader.py
│   ├── test_tenant_context.py
│   └── test_vectordb_app.py
│
├── uploads/                           # User-uploaded files (PDFs, CSVs, etc.)
│
├── vac_bot/                           # Core RAG / chatbot logic
│   ├── __init__.py
│   ├── chain.py                       # LLM chain composition
│   ├── curator.py                     # Knowledge curation / change detection
│   ├── loader.py                      # Document loading & indexing
│   ├── multimodal.py                  # Multi-modal (image/table/slide) support
│   ├── static_faq.py                  # Static FAQ fallback
│   └── tasks.py                       # Celery async tasks
│
└── vectordb/                          # Standalone vector database microservice
    ├── .dockerignore
    ├── app.py                          # VectorDB API
    ├── Dockerfile
    ├── requirements.txt
    └── chroma/                         # ChromaDB persistent storage
```

## Directory Descriptions

| Directory | Purpose |
|---|---|
| **`api/`** | Clean architecture layer — defines interfaces (`SessionProvider`), request/response DTOs, and domain handlers. No Flask imports in handlers; Flask adapters bridge the gap. |
| **`auth/`** | Authentication logic with admin and user auth classes, a base authenticator, and a factory pattern for instantiation. |
| **`instance/`** | Runtime data directory — contains the SQLite `admin.db` file (not tracked in git). |
| **`models/`** | SQLAlchemy ORM models for `Tenant` and `User` entities. |
| **`repositories/`** | Data access layer — base CRUD repository plus per-entity repos. |
| **`services/`** | Business logic services — currently `AuthService` which depends on `SessionProvider` interface. |
| **`static/`** | All CSS and JS assets — admin panel styles, auth page styles, chat interface, and landing page. |
| **`templates/`** | Jinja2 templates organized into `admin/` (10 pages) and `user/` (4 pages), plus root-level `landing.html` and `vac_chat.html`. |
| **`tests/`** | Pytest test suite covering chain, curator, loader, tenant context, and vectordb. |
| **`uploads/`** | User-uploaded documents (PDFs, CSVs, images) for the knowledge base. |
| **`vac_bot/`** | Core chatbot engine — document loading, LLM chain composition, knowledge curation, multi-modal processing, static FAQ, and Celery tasks. |
| **`vectordb/`** | Standalone microservice for the vector database (ChromaDB), with its own API, Dockerfile, and persistent storage. |

## Key Architecture Patterns

- **Clean Architecture**: `api/handlers/` contains framework-free business logic. Flask dependencies are injected via interfaces (`SessionProvider` in `api/interfaces.py`) and adapted in `api/flask/adapters.py`.
- **Blueprints**: Admin routes are in a Flask Blueprint (`admin.py`), mounted at `/admin`. Main app routes are in `app.py`.
- **Multi-Tenant**: Each tenant has isolated settings, URLs, documents, users, and curator data — scoped by `tenant_id`.
- **Microservice**: The vector database (ChromaDB) runs as a separate service (`vectordb/`), decoupled from the main app.
