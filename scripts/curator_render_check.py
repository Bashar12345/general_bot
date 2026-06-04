from tempfile import TemporaryDirectory
from pathlib import Path
import sqlite3
import sys, os
sys.path.insert(0, os.getcwd())
import db

with TemporaryDirectory() as tmp:
    db.DB_PATH = Path(tmp) / "admin.db"
    db.init_db()
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO urls (tenant_id, url, content_hash, crawl_history_json) VALUES (?, ?, ?, ?)", (1, "https://example.com/docs", "oldhash", "[1,1]"))
    conn.execute("INSERT INTO curator_queue (tenant_id, job_type, title, reason, payload_json, status) VALUES (?, ?, ?, ?, ?, ?)", (1, "reindex", "Content changed - re-index ready", "File hash mismatch", '{"pages":12}', "pending"))
    conn.execute("INSERT INTO curator_queue (tenant_id, job_type, title, reason, payload_json, status) VALUES (?, ?, ?, ?, ?, ?)", (1, "dedup", "3 near-duplicate chunk pairs found", "3 candidate pairs", '{}', "pending"))
    conn.commit()
    conn.close()

    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as session_data:
        session_data['admin'] = True
        session_data['tenant_id'] = 1

    resp = client.get('/admin/curator')
    print('STATUS', resp.status_code)
    body = resp.get_data(as_text=True)
    print('HAS_NEEDS', 'Needs your review' in body)
    print('HAS_CONTENT', 'Content changed - re-index ready' in body)
    print('HAS_DUP', '3 near-duplicate' in body)
    print('CURATOR_RENDER_OK')
