import sqlite3
import os
import json
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent
INSTANCE_DIR = BASE / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)
DB_PATH = INSTANCE_DIR / "admin.db"

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def migrate_db():
    conn = get_conn()
    migrations = [
        "ALTER TABLE settings ADD COLUMN tenant_id INTEGER DEFAULT 1",
        "ALTER TABLE settings ADD COLUMN theme TEXT DEFAULT 'dark'",
        "ALTER TABLE urls ADD COLUMN tenant_id INTEGER DEFAULT 1",
        "ALTER TABLE urls ADD COLUMN last_indexed_at TIMESTAMP",
        "ALTER TABLE urls ADD COLUMN version INTEGER DEFAULT 0",
        "ALTER TABLE urls ADD COLUMN content_hash TEXT",
        "ALTER TABLE urls ADD COLUMN last_crawled_at TIMESTAMP",
        "ALTER TABLE urls ADD COLUMN crawl_frequency TEXT DEFAULT 'monthly'",
        "ALTER TABLE urls ADD COLUMN change_count_recent INTEGER DEFAULT 0",
        "ALTER TABLE urls ADD COLUMN stable_run_count INTEGER DEFAULT 0",
        "ALTER TABLE urls ADD COLUMN last_change_at TIMESTAMP",
        "ALTER TABLE urls ADD COLUMN crawl_history_json TEXT DEFAULT '[]'",
        "ALTER TABLE documents ADD COLUMN tenant_id INTEGER DEFAULT 1",
        "ALTER TABLE documents ADD COLUMN last_indexed_at TIMESTAMP",
        "ALTER TABLE documents ADD COLUMN version INTEGER DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN content_hash TEXT",
        "ALTER TABLE documents ADD COLUMN last_crawled_at TIMESTAMP",
        "ALTER TABLE documents ADD COLUMN crawl_frequency TEXT DEFAULT 'monthly'",
        "ALTER TABLE documents ADD COLUMN change_count_recent INTEGER DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN stable_run_count INTEGER DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN last_change_at TIMESTAMP",
        "ALTER TABLE documents ADD COLUMN crawl_history_json TEXT DEFAULT '[]'",
        "ALTER TABLE index_log ADD COLUMN tenant_id INTEGER DEFAULT 1",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass

    try:
        conn.execute("UPDATE settings SET tenant_id=1 WHERE tenant_id IS NULL OR tenant_id=0")
        conn.execute("UPDATE urls SET tenant_id=1 WHERE tenant_id IS NULL OR tenant_id=0")
        conn.execute("UPDATE documents SET tenant_id=1 WHERE tenant_id IS NULL OR tenant_id=0")
        conn.execute("UPDATE index_log SET tenant_id=1 WHERE tenant_id IS NULL OR tenant_id=0")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER DEFAULT 1,
            bot_name TEXT NOT NULL DEFAULT 'Betopia AI',
            theme TEXT DEFAULT 'dark',
            personality TEXT DEFAULT '',
            tone TEXT DEFAULT '',
            purpose TEXT DEFAULT '',
            instructions TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER DEFAULT 1,
            url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_indexed_at TIMESTAMP,
            version INTEGER DEFAULT 0,
            content_hash TEXT,
            last_crawled_at TIMESTAMP,
            crawl_frequency TEXT DEFAULT 'monthly',
            change_count_recent INTEGER DEFAULT 0,
            stable_run_count INTEGER DEFAULT 0,
            last_change_at TIMESTAMP,
            crawl_history_json TEXT DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER DEFAULT 1,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            status TEXT DEFAULT 'ready',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_indexed_at TIMESTAMP,
            version INTEGER DEFAULT 0,
            content_hash TEXT,
            last_crawled_at TIMESTAMP,
            crawl_frequency TEXT DEFAULT 'monthly',
            change_count_recent INTEGER DEFAULT 0,
            stable_run_count INTEGER DEFAULT 0,
            last_change_at TIMESTAMP,
            crawl_history_json TEXT DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS index_log (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER DEFAULT 1,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            total_chunks INTEGER,
            url_count INTEGER,
            pdf_count INTEGER,
            status TEXT DEFAULT 'in_progress'
        );
        CREATE TABLE IF NOT EXISTS curator_queue (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            job_type TEXT NOT NULL,
            source_type TEXT,
            source_id TEXT,
            title TEXT NOT NULL,
            reason TEXT,
            payload_json TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 50,
            scheduled_at TIMESTAMP,
            completed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS source_snapshots (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_label TEXT,
            content_hash TEXT,
            content_length INTEGER,
            etag TEXT,
            last_modified TEXT,
            changed INTEGER DEFAULT 0,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    migrate_db()
    conn.execute(
        "INSERT OR IGNORE INTO tenants (id, name, slug, status) VALUES (?, ?, ?, ?)",
        (1, "Default Tenant", "default", "active")
    )
    row = conn.execute("SELECT COUNT(*) FROM settings").fetchone()
    if row[0] == 0:
        conn.execute(
            "INSERT INTO settings (id, tenant_id, bot_name, theme, personality, tone, purpose, instructions) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                "Betopia AI",
                "dark",
                "a knowledgeable, professional AI assistant from Betopia Limited",
                "professional and helpful. Be concise, clear, and friendly. Use 'we' for Betopia. End with next steps or an offer to help further.",
                "Betopia Limited is a global enterprise technology company delivering AI-powered cloud, ERP, cybersecurity, and digital transformation solutions.",
                'If the provided context does not contain relevant information to answer the question, do not make up an answer. Say:\n"I\'m not sure about that one — that\'s not covered in our current knowledge base. Reach out at betopialimited.com/contact and we\'ll get you the right answer."'
            )
        )
    else:
        conn.execute("UPDATE settings SET tenant_id=1 WHERE id=1")
    conn.commit()
    conn.close()

def get_default_tenant_id():
    conn = get_conn()
    row = conn.execute("SELECT id FROM tenants ORDER BY id LIMIT 1").fetchone()
    conn.close()
    return int(row[0]) if row else 1

def mark_indexed(source_type, source_ids):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    table = "urls" if source_type == "url" else "documents"
    id_col = "id"
    for sid in source_ids:
        conn.execute(
            f"UPDATE {table} SET last_indexed_at=?, version=COALESCE(version,0)+1 WHERE {id_col}=?",
            (now, sid)
        )
    conn.commit()
    conn.close()

def get_next_version(source_type, source_id):
    conn = get_conn()
    table = "urls" if source_type == "url" else "documents"
    id_col = "url" if source_type == "url" else "id"
    row = conn.execute(
        f"SELECT COALESCE(version,0) as v FROM {table} WHERE {id_col}=?",
        (source_id,)
    ).fetchone()
    conn.close()
    return (row["v"] + 1) if row else 1

def get_settings(tenant_id=None):
    conn = get_conn()
    if tenant_id is None:
        row = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
    else:
        row = conn.execute("SELECT * FROM settings WHERE tenant_id=? ORDER BY id LIMIT 1", (tenant_id,)).fetchone()
        if row is None:
            row = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
    conn.close()
    if row is None:
        return {}
    return dict(row)


def upsert_source_snapshot(tenant_id, source_type, source_id, source_label, content_hash, content_length=None, etag=None, last_modified=None, changed=False):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO source_snapshots (
            tenant_id, source_type, source_id, source_label, content_hash,
            content_length, etag, last_modified, changed, checked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tenant_id or 1,
            source_type,
            str(source_id),
            source_label,
            content_hash,
            content_length,
            etag,
            last_modified,
            1 if changed else 0,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def create_curator_job(tenant_id, job_type, title, source_type=None, source_id=None, reason=None, payload=None, priority=50, status="pending", scheduled_at=None):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO curator_queue (
            tenant_id, job_type, source_type, source_id, title, reason,
            payload_json, status, priority, scheduled_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tenant_id or 1,
            job_type,
            source_type,
            None if source_id is None else str(source_id),
            title,
            reason,
            json.dumps(payload or {}, ensure_ascii=False),
            status,
            priority,
            scheduled_at,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def list_curator_queue(tenant_id=None, status=None, limit=100):
    conn = get_conn()
    params = []
    where = []
    if tenant_id is not None:
        where.append("tenant_id = ?")
        params.append(tenant_id)
    if status:
        where.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM curator_queue"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY priority DESC, created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def list_source_snapshots(tenant_id=None, limit=100):
    conn = get_conn()
    params = []
    where = []
    if tenant_id is not None:
        where.append("tenant_id = ?")
        params.append(tenant_id)
    sql = "SELECT * FROM source_snapshots"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY checked_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]
