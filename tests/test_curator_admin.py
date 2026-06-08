import importlib
import sqlite3


def test_curator_scan_page_is_available(monkeypatch, tmp_path):
    db_path = tmp_path / "admin.db"

    db_module = importlib.import_module("db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()

    app_module = importlib.import_module("app")
    client = app_module.app.test_client()
    with client.session_transaction() as session_data:
        session_data["admin"] = True
        session_data["tenant_id"] = 1

    response = client.get("/tenant/curator")
    assert response.status_code == 200
    assert "Curator Queue" in response.get_data(as_text=True)


def test_curator_queue_item_can_be_dismissed(monkeypatch, tmp_path):
    db_path = tmp_path / "admin.db"

    db_module = importlib.import_module("db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO curator_queue (tenant_id, job_type, title, status) VALUES (?, ?, ?, ?)",
        (1, "reindex", "Re-index URL", "pending"),
    )
    conn.commit()
    conn.close()

    app_module = importlib.import_module("app")
    client = app_module.app.test_client()
    with client.session_transaction() as session_data:
        session_data["admin"] = True
        session_data["tenant_id"] = 1

    response = client.post(
        "/tenant/curator/item/1/action",
        data={"action": "dismiss"},
    )

    assert response.status_code == 302

    verification_conn = sqlite3.connect(db_path)
    verification_conn.row_factory = sqlite3.Row
    row = verification_conn.execute("SELECT status FROM curator_queue WHERE id=1").fetchone()
    verification_conn.close()
    assert row["status"] == "dismissed"
