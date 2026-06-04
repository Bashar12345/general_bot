import importlib
import importlib.util
import sqlite3
import sys
import types
from pathlib import Path


def _load_curator_module(monkeypatch):
    fake_package = types.ModuleType("vac_bot")
    fake_package.__path__ = []
    fake_loader = types.ModuleType("vac_bot.loader")
    fake_loader.scrape_url = lambda url: ("", "")
    fake_loader.extract_pdf_text = lambda filepath: []
    sys.modules["vac_bot"] = fake_package
    sys.modules["vac_bot.loader"] = fake_loader

    curator_path = Path(__file__).resolve().parents[1] / "vac_bot" / "curator.py"
    spec = importlib.util.spec_from_file_location("vac_bot.curator", curator_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["vac_bot.curator"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "scrape_url", lambda url: ("", ""))
    monkeypatch.setattr(module, "extract_pdf_text", lambda filepath: [])
    return module


def test_change_detection_queues_reindex_and_updates_crawl_frequency(monkeypatch, tmp_path):
    db_path = tmp_path / "admin.db"

    db_module = importlib.import_module("db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO urls (tenant_id, url, content_hash, crawl_history_json) VALUES (?, ?, ?, ?)",
        (1, "https://example.com/docs", "oldhash", "[1, 1]"),
    )
    conn.commit()
    conn.close()

    curator_module = _load_curator_module(monkeypatch)
    monkeypatch.setattr(curator_module, "scrape_url", lambda url: ("updated content from the page", "Docs Home"))

    result = curator_module.run_change_detection(tenant_id=1)

    assert result["changed"] == 1
    assert result["queued"] == 1
    assert result["errors"] == []

    verification_conn = sqlite3.connect(db_path)
    verification_conn.row_factory = sqlite3.Row
    url_row = verification_conn.execute("SELECT * FROM urls WHERE id=1").fetchone()
    queue_row = verification_conn.execute("SELECT * FROM curator_queue WHERE tenant_id=1").fetchone()
    snapshot_row = verification_conn.execute("SELECT * FROM source_snapshots WHERE tenant_id=1").fetchone()
    verification_conn.close()

    assert url_row["content_hash"] != "oldhash"
    assert url_row["crawl_frequency"] == "daily"
    assert queue_row["job_type"] == "reindex"
    assert queue_row["source_type"] == "url"
    assert snapshot_row["changed"] == 1
