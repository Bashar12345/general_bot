# Setup & Run Guide

## Prerequisites

- **Docker & Docker Compose** (recommended) or **Python 3.12** (local)
- **OpenAI API key** with access to `gpt-4o-mini`, `gpt-4o` (vision), and `text-embedding-ada-002`

---

## 1. Environment Configuration

Create a `.env` file in the project root:

```ini
# Required
OPENAI_API_KEY="sk-..."

# Optional (defaults shown)
FLASK_SECRET_KEY="change-me-in-production"
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
```

> **Security:** Change `ADMIN_USERNAME` / `ADMIN_PASSWORD` in production. Never commit the real `.env` file.

---

## 2. Docker Compose (Recommended)

### Start all services

```bash
docker compose up -d --build
```

This brings up five containers:

| Container      | Port  | Purpose                    | Start depends on |
|----------------|-------|----------------------------|------------------|
| `valr-redis`   | 6379  | Celery message broker      | —                |
| `valr-vectordb`| 5001  | ChromaDB vector search API | —                |
| `valr-bot`     | 5000  | Main Flask application     | vectordb, redis  |
| `valr-worker`  | —     | Celery async task consumer | redis, vectordb  |
| `valr-beat`    | —     | Celery scheduled tasks     | redis, vectordb  |

### Verify health

```bash
curl http://localhost:5000/health
# {"status":"ok"}

curl http://localhost:5001/health
# {"status":"ok","index_loaded":true}
```

### Stop

```bash
docker compose down                         # stop, preserve volumes
docker compose down -v                      # stop, delete volumes (wipes ChromaDB)
```

### View logs

```bash
docker compose logs -f valr-bot             # app logs
docker compose logs -f worker               # celery worker logs
```

---

## 3. Local Development (Without Docker)

### 3.1 Redis (required for Celery)

```bash
docker run -d --name valr-redis -p 6379:6379 redis:7-alpine
```

### 3.2 Vector Database Microservice

```bash
cd vectordb
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py                              # runs on :5001
```

### 3.3 Main Application

```bash
# From project root
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Ensure VEKTORDB_URL is set
export VEKTORDB_URL=http://localhost:5001

flask run --host 0.0.0.0 --port 5000       # runs on :5000
```

### 3.4 Celery Worker & Beat (optional, for async tasks)

```bash
# Terminal 3 — worker
celery -A vac_bot.tasks.celery_app worker --loglevel=info

# Terminal 4 — beat scheduler
celery -A vac_bot.tasks.celery_app beat --loglevel=info
```

---

## 4. Access Points

| Service   | URL                        | Default Credentials      |
|-----------|----------------------------|--------------------------|
| Chat UI   | http://localhost:5000      | User sign-up or admin    |
| Admin     | http://localhost:5000/admin/login | `admin` / `admin123` |
| Health    | http://localhost:5000/health | —                        |

---

## 5. Testing

### Run tests inside Docker

```bash
docker compose exec valr-bot pytest -q
```

### Run tests locally

```bash
# Start dependencies first
docker compose up -d redis vectordb
pytest -q -v
```

---

## 6. Production Deployment

### Environment variables to harden

```ini
FLASK_SECRET_KEY="<generate-with: python -c 'import secrets; print(secrets.token_hex(32))'>"
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="<strong-password>"
FLASK_DEBUG=0
```

### Switch to Gunicorn (production CMD)

The Dockerfile already uses Gunicorn:

```dockerfile
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "120", "app:app"]
```

For multi-worker or multi-host setups, configure a production-grade WSGI server and a reverse proxy (nginx, Caddy) in front of port 5000.

### Persistent volumes to back up

- `vectordb_data` (ChromaDB vectors) — mapped to `vectordb/chroma/`
- `./instance/admin.db` (SQLite relational data)

---

## 7. Database Initialisation

SQLite schema and migrations run automatically at startup via `init_db()` in `app.py:17-18`:

```python
with app.app_context():
    init_db()
```

This creates 8 tables (`tenants`, `users`, `settings`, `urls`, `documents`, `index_log`, `curator_queue`, `source_snapshots`) and seeds a default tenant. No manual migration steps required.

---

## 8. Quick Reference

```bash
# Full stack
docker compose up -d --build

# Rebuild a single service
docker compose up -d --build valr-bot

# Run a one-off command in the app container
docker compose exec valr-bot flask shell

# Tail logs for all services
docker compose logs -f

# Reset everything (including vector DB)
docker compose down -v && docker compose up -d --build
```
