import sqlite3
import os
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
        "ALTER TABLE settings ADD COLUMN theme TEXT DEFAULT 'dark'",
        "ALTER TABLE urls ADD COLUMN last_indexed_at TIMESTAMP",
        "ALTER TABLE urls ADD COLUMN version INTEGER DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN last_indexed_at TIMESTAMP",
        "ALTER TABLE documents ADD COLUMN version INTEGER DEFAULT 0",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
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
            url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_indexed_at TIMESTAMP,
            version INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            status TEXT DEFAULT 'ready',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_indexed_at TIMESTAMP,
            version INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS index_log (
            id INTEGER PRIMARY KEY,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            total_chunks INTEGER,
            url_count INTEGER,
            pdf_count INTEGER,
            status TEXT DEFAULT 'in_progress'
        );
    """)
    migrate_db()
    row = conn.execute("SELECT COUNT(*) FROM settings").fetchone()
    if row[0] == 0:
        conn.execute(
            "INSERT INTO settings (bot_name, theme, personality, tone, purpose, instructions) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "Betopia AI",
                "dark",
                "a knowledgeable, professional AI assistant from Betopia Limited",
                "professional and helpful. Be concise, clear, and friendly. Use 'we' for Betopia. End with next steps or an offer to help further.",
                "Betopia Limited is a global enterprise technology company delivering AI-powered cloud, ERP, cybersecurity, and digital transformation solutions.",
                'If the provided context does not contain relevant information to answer the question, do not make up an answer. Say:\n"I\'m not sure about that one — that\'s not covered in our current knowledge base. Reach out at betopialimited.com/contact and we\'ll get you the right answer."'
            )
        )
    conn.commit()
    conn.close()

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

def get_settings():
    conn = get_conn()
    row = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
    conn.close()
    if row is None:
        return {}
    return dict(row)
