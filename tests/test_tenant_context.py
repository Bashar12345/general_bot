import importlib
import sqlite3


def test_login_seeds_default_tenant_in_session(monkeypatch, tmp_path):
    db_path = tmp_path / "admin.db"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE tenants (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, slug TEXT NOT NULL UNIQUE, status TEXT DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO tenants (id, name, slug, status) VALUES (?, ?, ?, ?)",
        (1, "Default Tenant", "default", "active"),
    )
    conn.commit()
    conn.close()

    db_module = importlib.import_module("db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setattr(db_module, "init_db", lambda: None)

    app_module = importlib.import_module("app")

    client = app_module.app.test_client()
    response = client.post(
        "/tenant/login",
        data={"username": "admin", "password": "admin123"},
    )

    assert response.status_code == 302
    with client.session_transaction() as session_data:
        assert session_data["admin"] is True
        assert session_data["tenant_id"] == 1
        assert session_data["user_role"] == "admin"
