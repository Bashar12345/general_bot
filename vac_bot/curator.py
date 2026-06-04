import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from db import (
    get_conn,
    list_curator_queue,
    list_source_snapshots,
)
from vac_bot.loader import extract_pdf_text, scrape_url


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_text(text):
    return " ".join((text or "").split())


def sha256_text(text):
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _rolling_history(raw_history, changed):
    try:
        history = list(json.loads(raw_history or "[]"))
    except Exception:
        history = []
    history.append(1 if changed else 0)
    return history[-5:]


def _history_stats(history):
    recent_changes = sum(1 for value in history if value)
    stable_run = 0
    for value in reversed(history):
        if value:
            break
        stable_run += 1
    return recent_changes, stable_run


def _update_source_record(conn, table_name, row, content_hash, changed, source_label, content_length=None):
    history = _rolling_history(row["crawl_history_json"], changed)
    recent_changes, stable_run = _history_stats(history)
    crawl_frequency = row["crawl_frequency"] or "monthly"
    if recent_changes >= 3:
        crawl_frequency = "daily"
    elif len(history) >= 5 and recent_changes == 0:
        crawl_frequency = "monthly"

    now = _now_iso()
    conn.execute(
        f"""
        UPDATE {table_name}
        SET content_hash = ?,
            last_crawled_at = ?,
            crawl_frequency = ?,
            change_count_recent = ?,
            stable_run_count = ?,
            last_change_at = CASE WHEN ? = 1 THEN ? ELSE last_change_at END,
            crawl_history_json = ?
        WHERE id = ?
        """,
        (
            content_hash,
            now,
            crawl_frequency,
            recent_changes,
            stable_run,
            1 if changed else 0,
            now,
            json.dumps(history),
            row["id"],
        ),
    )
    conn.execute(
        """
        INSERT INTO source_snapshots (
            tenant_id, source_type, source_id, source_label, content_hash,
            content_length, etag, last_modified, changed, checked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["tenant_id"],
            "url" if table_name == "urls" else "pdf",
            str(row["id"]),
            source_label,
            content_hash,
            content_length,
            None,
            None,
            1 if changed else 0,
            _now_iso(),
        ),
    )


def _queue_reindex(tenant_id, table_name, row, reason, payload):
    source_type = "url" if table_name == "urls" else "pdf"
    title = f"Re-index {source_type.upper()}: {row['url'] if table_name == 'urls' else row['filename']}"
    return {
        "tenant_id": tenant_id,
        "job_type": "reindex",
        "source_type": source_type,
        "source_id": row["id"],
        "title": title,
        "reason": reason,
        "payload": payload,
        "priority": 80,
    }


def scan_url_sources(tenant_id=None):
    conn = get_conn()
    params = []
    sql = "SELECT * FROM urls"
    if tenant_id is not None:
        sql += " WHERE tenant_id = ?"
        params.append(tenant_id)
    rows = conn.execute(sql, params).fetchall()
    changed = 0
    queued = 0
    errors = []
    now = _now_iso()

    for row in rows:
        try:
            text, title = scrape_url(row["url"])
            normalized = normalize_text(text)
            content_hash = sha256_text(normalized) if normalized else None
            previous_hash = row["content_hash"]
            has_baseline = bool(previous_hash)
            source_changed = bool(has_baseline and content_hash and content_hash != previous_hash)

            _update_source_record(
                conn,
                "urls",
                row,
                content_hash,
                source_changed,
                title or row["url"],
                content_length=len(normalized),
            )
            if source_changed:
                changed += 1
                queued += 1
                job = _queue_reindex(
                    row["tenant_id"],
                    "urls",
                    row,
                    "URL content changed and needs re-indexing.",
                    {
                        "source_type": "url",
                        "source_id": row["id"],
                        "url": row["url"],
                        "detected_at": now,
                        "content_hash": content_hash,
                    },
                )
                conn.execute(
                    """
                    INSERT INTO curator_queue (
                        tenant_id, job_type, source_type, source_id, title, reason,
                        payload_json, status, priority, scheduled_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job["tenant_id"],
                        job["job_type"],
                        job["source_type"],
                        str(job["source_id"]),
                        job["title"],
                        job["reason"],
                        json.dumps(job["payload"], ensure_ascii=False),
                        "pending",
                        job["priority"],
                        None,
                        _now_iso(),
                    ),
                )
        except Exception as exc:
            errors.append(f"URL scan failed ({row['url']}): {exc}")

    conn.commit()
    conn.close()
    return {
        "source_type": "url",
        "scanned": len(rows),
        "changed": changed,
        "queued": queued,
        "errors": errors,
    }


def scan_pdf_sources(tenant_id=None):
    conn = get_conn()
    params = []
    sql = "SELECT * FROM documents"
    if tenant_id is not None:
        sql += " WHERE tenant_id = ?"
        params.append(tenant_id)
    rows = conn.execute(sql, params).fetchall()
    changed = 0
    queued = 0
    errors = []
    now = _now_iso()

    for row in rows:
        filepath = Path(row["filepath"])
        try:
            if not filepath.exists():
                raise FileNotFoundError(str(filepath))

            pdf_bytes = filepath.read_bytes()
            pages = extract_pdf_text(str(filepath))
            extracted_text = "\n".join(page.get("text", "") for page in pages)
            normalized = normalize_text(extracted_text)
            content_hash = sha256_text(normalized) if normalized else hashlib.sha256(pdf_bytes).hexdigest()
            previous_hash = row["content_hash"]
            has_baseline = bool(previous_hash)
            source_changed = bool(has_baseline and content_hash and content_hash != previous_hash)

            _update_source_record(
                conn,
                "documents",
                row,
                content_hash,
                source_changed,
                row["filename"],
                content_length=len(pdf_bytes),
            )
            if source_changed:
                changed += 1
                queued += 1
                job = _queue_reindex(
                    row["tenant_id"],
                    "documents",
                    row,
                    "PDF content changed and needs re-indexing.",
                    {
                        "source_type": "pdf",
                        "source_id": row["id"],
                        "filename": row["filename"],
                        "filepath": row["filepath"],
                        "detected_at": now,
                        "content_hash": content_hash,
                    },
                )
                conn.execute(
                    """
                    INSERT INTO curator_queue (
                        tenant_id, job_type, source_type, source_id, title, reason,
                        payload_json, status, priority, scheduled_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job["tenant_id"],
                        job["job_type"],
                        job["source_type"],
                        str(job["source_id"]),
                        job["title"],
                        job["reason"],
                        json.dumps(job["payload"], ensure_ascii=False),
                        "pending",
                        job["priority"],
                        None,
                        _now_iso(),
                    ),
                )
        except Exception as exc:
            errors.append(f"PDF scan failed ({row['filename']}): {exc}")

    conn.commit()
    conn.close()
    return {
        "source_type": "pdf",
        "scanned": len(rows),
        "changed": changed,
        "queued": queued,
        "errors": errors,
    }


def run_change_detection(tenant_id=None):
    url_result = scan_url_sources(tenant_id=tenant_id)
    pdf_result = scan_pdf_sources(tenant_id=tenant_id)
    return {
        "tenant_id": tenant_id or 1,
        "scanned": url_result["scanned"] + pdf_result["scanned"],
        "changed": url_result["changed"] + pdf_result["changed"],
        "queued": url_result["queued"] + pdf_result["queued"],
        "errors": url_result["errors"] + pdf_result["errors"],
        "details": [url_result, pdf_result],
    }


def get_curator_dashboard_state(tenant_id=None):
    return {
        "queue": list_curator_queue(tenant_id=tenant_id),
        "snapshots": list_source_snapshots(tenant_id=tenant_id),
    }
