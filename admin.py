import os
from pathlib import Path
from functools import wraps
from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, jsonify, flash, current_app
)
from werkzeug.utils import secure_filename
from db import get_conn, get_settings as load_settings

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "admin123")

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("admin.dashboard"))
        flash("Invalid credentials", "error")
    return render_template("admin/login.html")

@admin_bp.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("admin.login"))

@admin_bp.route("/")
@admin_required
def dashboard():
    conn = get_conn()
    url_count = conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0]
    doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    settings = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
    conn.close()
    return render_template("admin/dashboard.html",
                           url_count=url_count,
                           doc_count=doc_count,
                           settings=dict(settings) if settings else {})

@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        conn = get_conn()
        conn.execute(
            "UPDATE settings SET bot_name=?, personality=?, tone=?, purpose=?, instructions=?, updated_at=? WHERE id=1",
            (
                request.form.get("bot_name", "VALR-Bot"),
                request.form.get("personality", ""),
                request.form.get("tone", ""),
                request.form.get("purpose", ""),
                request.form.get("instructions", ""),
                datetime.now(timezone.utc).isoformat(),
            )
        )
        conn.commit()
        conn.close()
        from vac_bot.chain import rebuild_chain
        rebuild_chain()
        flash("Settings saved and chain will rebuild on next question.", "success")
        return redirect(url_for("admin.settings"))
    settings = load_settings()
    return render_template("admin/settings.html", settings=settings)

@admin_bp.route("/knowledge")
@admin_required
def knowledge():
    conn = get_conn()
    urls = conn.execute("SELECT * FROM urls ORDER BY created_at DESC").fetchall()
    docs = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template("admin/knowledge.html",
                           urls=[dict(r) for r in urls],
                           docs=[dict(r) for r in docs])

@admin_bp.route("/knowledge/url/add", methods=["POST"])
@admin_required
def add_url():
    url = request.form.get("url", "").strip()
    if not url:
        flash("URL is required", "error")
        return redirect(url_for("admin.knowledge"))
    conn = get_conn()
    conn.execute("INSERT INTO urls (url) VALUES (?)", (url,))
    conn.commit()
    conn.close()
    flash("URL added.", "success")
    return redirect(url_for("admin.knowledge"))

@admin_bp.route("/knowledge/url/<int:url_id>/delete", methods=["POST"])
@admin_required
def delete_url(url_id):
    conn = get_conn()
    conn.execute("DELETE FROM urls WHERE id=?", (url_id,))
    conn.commit()
    conn.close()
    flash("URL removed.", "success")
    if request.form.get("rebuild"):
        return redirect(url_for("admin.rebuild"))
    return redirect(url_for("admin.knowledge"))

@admin_bp.route("/knowledge/pdf/upload", methods=["POST"])
@admin_required
def upload_pdf():
    if "file" not in request.files:
        flash("No file selected", "error")
        return redirect(url_for("admin.knowledge"))
    file = request.files["file"]
    if not file or not file.filename.lower().endswith(".pdf"):
        flash("Only PDF files are allowed", "error")
        return redirect(url_for("admin.knowledge"))
    filename = secure_filename(file.filename)
    uploads_dir = Path(current_app.root_path) / "uploads"
    uploads_dir.mkdir(exist_ok=True)
    filepath = uploads_dir / filename
    file.save(str(filepath))
    conn = get_conn()
    conn.execute("INSERT INTO documents (filename, filepath, status) VALUES (?, ?, ?)",
                 (filename, str(filepath), "ready"))
    conn.commit()
    conn.close()
    flash(f"Uploaded {filename}. Rebuild index to include it.", "success")
    return redirect(url_for("admin.knowledge"))

@admin_bp.route("/knowledge/pdf/<int:doc_id>/delete", methods=["POST"])
@admin_required
def delete_pdf(doc_id):
    conn = get_conn()
    row = conn.execute("SELECT filepath FROM documents WHERE id=?", (doc_id,)).fetchone()
    if row:
        fp = row["filepath"]
        if os.path.exists(fp):
            os.remove(fp)
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    conn.commit()
    conn.close()
    flash("PDF removed.", "success")
    if request.form.get("rebuild"):
        return redirect(url_for("admin.rebuild"))
    return redirect(url_for("admin.knowledge"))

@admin_bp.route("/knowledge/rebuild", methods=["POST"])
@admin_required
def rebuild():
    from vac_bot.loader import rebuild_vectordb
    from vac_bot.chain import rebuild_chain

    conn = get_conn()
    conn.execute("INSERT INTO index_log (status) VALUES ('in_progress')")
    log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    try:
        result = rebuild_vectordb()
        rebuild_chain()
        count = result.get("count", 0)
        warnings = result.get("warnings", [])

        conn = get_conn()
        conn.execute(
            "UPDATE index_log SET completed_at=?, total_chunks=?, status=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), count, "completed", log_id)
        )
        conn.commit()
        conn.close()

        msg = f"Index rebuilt with {count} chunks."
        if warnings:
            msg += f" Warnings ({len(warnings)}): " + "; ".join(warnings[:3])
            if len(warnings) > 3:
                msg += f" (+{len(warnings)-3} more)"
        flash(msg, "success" if count > 0 else "warning")
    except Exception as e:
        conn = get_conn()
        conn.execute(
            "UPDATE index_log SET completed_at=?, status=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), f"failed: {e}", log_id)
        )
        conn.commit()
        conn.close()
        flash(f"Rebuild failed: {e}", "error")
    return redirect(url_for("admin.dashboard"))
