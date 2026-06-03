import importlib
import sys
import types
import sqlite3
from pathlib import Path


def _import_vectordb_app():
    if "langchain_chroma" not in sys.modules:
        fake_module = types.ModuleType("langchain_chroma")

        class PlaceholderChroma:
            @classmethod
            def from_documents(cls, *args, **kwargs):
                return object()

        fake_module.Chroma = PlaceholderChroma
        sys.modules["langchain_chroma"] = fake_module

    if "chromadb" not in sys.modules:
        chromadb_module = types.ModuleType("chromadb")
        api_module = types.ModuleType("chromadb.api")
        client_module = types.ModuleType("chromadb.api.client")

        class SharedSystemClient:
            _identifier_to_system = {}

            @staticmethod
            def clear_system_cache():
                return None

        class PersistentClient:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        client_module.SharedSystemClient = SharedSystemClient
        api_module.client = client_module
        chromadb_module.api = api_module
        chromadb_module.PersistentClient = PersistentClient

        sys.modules["chromadb"] = chromadb_module
        sys.modules["chromadb.api"] = api_module
        sys.modules["chromadb.api.client"] = client_module

    return importlib.import_module("vectordb.app")


def test_clear_chroma_dir_resets_state_and_removes_files(monkeypatch, tmp_path):
    vectordb_app = _import_vectordb_app()

    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    (chroma_dir / "chroma.sqlite3").write_text("db")
    (chroma_dir / "segment.dat").write_text("data")

    class FakeClient:
        def __init__(self):
            self.cleared = False

        def clear_system_cache(self):
            self.cleared = True

    fake_client = FakeClient()

    monkeypatch.setattr(vectordb_app, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(vectordb_app, "_db", object())
    monkeypatch.setattr(vectordb_app, "_client", fake_client)

    vectordb_app._clear_chroma_dir()

    assert vectordb_app._db is None
    assert vectordb_app._client is None
    assert fake_client.cleared is True
    assert chroma_dir.exists()
    assert list(chroma_dir.iterdir()) == []


def test_rebuild_endpoint_creates_collection_from_documents(monkeypatch, tmp_path):
    vectordb_app = _import_vectordb_app()

    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()

    monkeypatch.setattr(vectordb_app, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(vectordb_app, "_clear_chroma_dir", lambda: None)
    monkeypatch.setattr(vectordb_app, "_get_or_create_client", lambda: "fake-client")
    monkeypatch.setattr(vectordb_app.chromadb.api.client.SharedSystemClient, "_identifier_to_system", {"existing": object()}, raising=False)
    monkeypatch.setattr(vectordb_app.chromadb.api.client.SharedSystemClient, "clear_system_cache", lambda: None)

    captured = {}

    class FakeChroma:
        @classmethod
        def from_documents(cls, docs, embeddings, client, collection_name):
            captured["docs"] = docs
            captured["client"] = client
            captured["collection_name"] = collection_name
            return "fake-db"

    monkeypatch.setattr(vectordb_app, "Chroma", FakeChroma)

    with vectordb_app.app.test_request_context(
        "/rebuild",
        method="POST",
        json={"documents": [{"page_content": "hello", "metadata": {"source": "pdf:test.pdf"}}]},
    ):
        response = vectordb_app.rebuild()

    assert response.get_json() == {"status": "ok", "count": 1}
    assert captured["client"] == "fake-client"
    assert captured["collection_name"] == "langchain"
    assert captured["docs"][0].page_content == "hello"


def test_delete_pdf_removes_row_and_file(monkeypatch, tmp_path):
    db_path = tmp_path / "admin.db"
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    pdf_path = uploads_dir / "sample.pdf"
    pdf_path.write_text("pdf content")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE documents (id INTEGER PRIMARY KEY, filename TEXT NOT NULL, filepath TEXT NOT NULL, status TEXT DEFAULT 'ready', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO documents (id, filename, filepath, status) VALUES (?, ?, ?, ?)",
        (1, "sample.pdf", str(pdf_path), "ready"),
    )
    conn.commit()
    conn.close()

    db_module = importlib.import_module("db")
    monkeypatch.setattr(db_module, "init_db", lambda: None)
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    app_module = importlib.import_module("app")
    admin_module = importlib.import_module("admin")

    def fake_get_conn():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(admin_module, "get_conn", fake_get_conn)
    monkeypatch.setattr(admin_module, "current_app", app_module.app)

    client = app_module.app.test_client()
    with client.session_transaction() as session_data:
        session_data["admin"] = True

    response = client.post("/admin/knowledge/pdf/1/delete")

    assert response.status_code == 302
    assert not pdf_path.exists()

    verification_conn = sqlite3.connect(db_path)
    remaining = verification_conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    verification_conn.close()
    assert remaining == 0


def test_homepage_uses_saved_bot_name(monkeypatch, tmp_path):
    db_path = tmp_path / "admin.db"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE settings (id INTEGER PRIMARY KEY, bot_name TEXT NOT NULL DEFAULT 'Betopia AI', personality TEXT DEFAULT '', tone TEXT DEFAULT '', purpose TEXT DEFAULT '', instructions TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO settings (id, bot_name, personality, tone, purpose, instructions) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Nova Assist", "", "", "", ""),
    )
    conn.commit()
    conn.close()

    db_module = importlib.import_module("db")
    monkeypatch.setattr(db_module, "init_db", lambda: None)
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    app_module = importlib.import_module("app")

    client = app_module.app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Nova Assist" in body
    assert "Intelligent Enterprise Assistant — Nova Assist" in body


def test_homepage_uses_saved_theme(monkeypatch, tmp_path):
    db_path = tmp_path / "admin.db"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE settings (id INTEGER PRIMARY KEY, bot_name TEXT NOT NULL DEFAULT 'Betopia AI', theme TEXT DEFAULT 'dark', personality TEXT DEFAULT '', tone TEXT DEFAULT '', purpose TEXT DEFAULT '', instructions TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO settings (id, bot_name, theme, personality, tone, purpose, instructions) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "Nova Assist", "light", "", "", "", ""),
    )
    conn.commit()
    conn.close()

    db_module = importlib.import_module("db")
    monkeypatch.setattr(db_module, "init_db", lambda: None)
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    app_module = importlib.import_module("app")

    client = app_module.app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'body class="theme-light"' in body


def test_admin_login_uses_saved_brand_name_and_logout_posts(monkeypatch, tmp_path):
    db_path = tmp_path / "admin.db"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE settings (id INTEGER PRIMARY KEY, bot_name TEXT NOT NULL DEFAULT 'Betopia AI', personality TEXT DEFAULT '', tone TEXT DEFAULT '', purpose TEXT DEFAULT '', instructions TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO settings (id, bot_name, personality, tone, purpose, instructions) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Nova Assist", "", "", "", ""),
    )
    conn.commit()
    conn.close()

    db_module = importlib.import_module("db")
    monkeypatch.setattr(db_module, "init_db", lambda: None)
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    app_module = importlib.import_module("app")

    client = app_module.app.test_client()
    login_response = client.get("/admin/login")
    assert login_response.status_code == 200
    assert "Nova Assist Admin" in login_response.get_data(as_text=True)

    with client.session_transaction() as session_data:
        session_data["admin"] = True

    logout_response = client.post("/admin/logout")

    assert logout_response.status_code == 302
    assert logout_response.headers["Location"].endswith("/admin/login")


def test_admin_settings_theme_toggle_renders_selected_mode(monkeypatch, tmp_path):
    db_path = tmp_path / "admin.db"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE settings (id INTEGER PRIMARY KEY, bot_name TEXT NOT NULL DEFAULT 'Betopia AI', theme TEXT DEFAULT 'dark', personality TEXT DEFAULT '', tone TEXT DEFAULT '', purpose TEXT DEFAULT '', instructions TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO settings (id, bot_name, theme, personality, tone, purpose, instructions) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "Nova Assist", "dark", "", "", "", ""),
    )
    conn.commit()
    conn.close()

    db_module = importlib.import_module("db")
    monkeypatch.setattr(db_module, "init_db", lambda: None)
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    app_module = importlib.import_module("app")

    client = app_module.app.test_client()
    with client.session_transaction() as session_data:
        session_data["admin"] = True

    response = client.post(
        "/admin/settings",
        data={
            "bot_name": "Nova Assist",
            "theme": "light",
            "personality": "",
            "tone": "",
            "purpose": "",
            "instructions": "",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'body class="theme-light"' in body
    assert 'value="light" selected' in body
