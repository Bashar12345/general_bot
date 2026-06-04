import os
from pathlib import Path
from functools import wraps
from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, jsonify, flash, current_app
)
from werkzeug.utils import secure_filename
from db import get_conn, get_settings as load_settings, get_default_tenant_id
from db import get_tenant
from vac_bot.curator import get_curator_dashboard_state, run_change_detection
from werkzeug.security import generate_password_hash
import requests
import re
import time

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "admin123")
DEFAULT_BOT_NAME = "Betopia AI"
DEFAULT_THEME = "dark"

THEME_OPTIONS = [
    "dark",
    "light",
]

PERSONALITY_OPTIONS = [
    "Professional",
    "Warm and empathetic",
    "Friendly and conversational",
    "Concise and direct",
    "Expert and authoritative",
]

TONE_OPTIONS = [
    "Professional and helpful",
    "Warm and supportive",
    "Concise and direct",
    "Calm and reassuring",
    "Friendly and approachable",
]

PURPOSE_OPTIONS = [
    "FAQ assistant",
    "Support triage assistant",
    "Onboarding assistant",
    "Policy and guidance assistant",
    "Knowledge base assistant",
]

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.app_context_processor
def inject_admin_brand_name():
    tid = session.get("tenant_id") or get_default_tenant_id()
    settings = load_settings(tid)
    theme = (settings.get("theme") or DEFAULT_THEME).strip().lower()
    if theme not in THEME_OPTIONS:
        theme = DEFAULT_THEME
    tenant = get_tenant(tid)
    tenant_name = tenant.get("name") if tenant else "Tenant"
    tenant_slug = tenant.get("slug") if tenant else "default"
    bot_avatar = settings.get("bot_avatar") or ""
    bot_avatar_url = url_for("admin.tenant_avatar", tenant_id=tid) if bot_avatar else None
    return {
        "admin_brand_name": settings.get("bot_name") or DEFAULT_BOT_NAME,
        "admin_theme": theme,
        "tenant_name": tenant_name,
        "tenant_slug": tenant_slug,
        "tenant_id": tid,
        "tenant_plan": "Pro plan",
        "bot_avatar_url": bot_avatar_url,
    }

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session["admin"] = True
            session["tenant_id"] = get_default_tenant_id()
            session["user_role"] = "admin"
            return redirect(url_for("admin.dashboard"))
        flash("Invalid credentials", "error")
    return render_template("admin/login.html")

@admin_bp.route("/logout", methods=["POST"])
def logout():
    session.pop("admin", None)
    session.pop("tenant_id", None)
    session.pop("user_role", None)
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
        theme = request.form.get("theme", DEFAULT_THEME).strip().lower()
        if theme not in THEME_OPTIONS:
            theme = DEFAULT_THEME
        tenant_id = session.get("tenant_id") or get_default_tenant_id()
        conn = get_conn()
        row = conn.execute("SELECT id FROM settings WHERE tenant_id=?", (tenant_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO settings (tenant_id, bot_name) VALUES (?, ?)", (tenant_id, request.form.get("bot_name", "").strip() or DEFAULT_BOT_NAME))
        conn.execute(
            "UPDATE settings SET bot_name=?, theme=?, personality=?, tone=?, purpose=?, instructions=?, updated_at=? WHERE tenant_id=?",
            (
                request.form.get("bot_name", "").strip() or DEFAULT_BOT_NAME,
                theme,
                request.form.get("personality", ""),
                request.form.get("tone", ""),
                request.form.get("purpose", ""),
                request.form.get("instructions", ""),
                datetime.now(timezone.utc).isoformat(),
                tenant_id,
            )
        )
        avatar = request.files.get("bot_avatar")
        if avatar and avatar.filename:
            ext = avatar.filename.rsplit(".", 1)[-1].lower() if "." in avatar.filename else "png"
            if ext in ("png", "jpg", "jpeg", "gif", "webp"):
                avatars_dir = Path(current_app.root_path) / "uploads" / "avatars"
                avatars_dir.mkdir(parents=True, exist_ok=True)
                avatar_path = avatars_dir / f"tenant_{tenant_id}.{ext}"
                avatar.save(str(avatar_path))
                conn.execute("UPDATE settings SET bot_avatar=? WHERE tenant_id=?", (f"tenant_{tenant_id}.{ext}", tenant_id))
        conn.commit()
        conn.close()
        from vac_bot.chain import rebuild_chain
        rebuild_chain()
        flash("Settings saved and chain will rebuild on next question.", "success")
        return redirect(url_for("admin.settings"))
    settings = load_settings()
    return render_template(
        "admin/settings.html",
        settings=settings,
        theme_options=THEME_OPTIONS,
        personality_options=PERSONALITY_OPTIONS,
        tone_options=TONE_OPTIONS,
        purpose_options=PURPOSE_OPTIONS,
    )

@admin_bp.route("/avatar/<int:tenant_id>")
def tenant_avatar(tenant_id):
    conn = get_conn()
    row = conn.execute("SELECT bot_avatar FROM settings WHERE tenant_id=?", (tenant_id,)).fetchone()
    conn.close()
    if not row or not row["bot_avatar"]:
        return "", 204
    avatar_path = Path(current_app.root_path) / "uploads" / "avatars" / row["bot_avatar"]
    if not avatar_path.exists():
        return "", 204
    ext = avatar_path.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
    return open(avatar_path, "rb").read(), 200, {"Content-Type": mime, "Cache-Control": "max-age=86400"}

@admin_bp.route("/knowledge")
@admin_required
def knowledge():
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    conn = get_conn()
    urls = conn.execute("SELECT * FROM urls WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,)).fetchall()
    docs = conn.execute("SELECT * FROM documents WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,)).fetchall()
    conn.close()
    pdfs = [d for d in docs if d["doc_type"] in (None, "", "pdf")]
    images = [d for d in docs if d["doc_type"] == "image"]
    tables = [d for d in docs if d["doc_type"] == "table"]
    slides = [d for d in docs if d["doc_type"] == "slides"]
    scanned = [d for d in docs if d["doc_type"] == "scanned"]
    return render_template("admin/knowledge.html",
                           urls=[dict(r) for r in urls],
                           docs=[dict(r) for r in docs],
                           pdfs=[dict(r) for r in pdfs],
                           images=[dict(r) for r in images],
                           tables=[dict(r) for r in tables],
                           slides=[dict(r) for r in slides],
                           scanned=[dict(r) for r in scanned])


@admin_bp.route("/curator")
@admin_required
def curator():
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    state = get_curator_dashboard_state(tenant_id)
    return render_template(
        "admin/curator.html",
        queue=state["queue"],
        snapshots=state["snapshots"],
    )


@admin_bp.route("/curator/scan", methods=["POST"])
@admin_required
def curator_scan():
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    try:
        from vac_bot.tasks import run_change_detection_task
        task = run_change_detection_task.delay(tenant_id=tenant_id)
        flash(f"Curator scan queued. Task {task.id} will update the work queue in the background.", "success")
    except Exception as exc:
        flash(f"Could not queue curator scan: {exc}", "error")
    return redirect(url_for("admin.curator"))


@admin_bp.route("/curator/item/<int:item_id>/action", methods=["POST"])
@admin_required
def curator_item_action(item_id):
    action = (request.form.get("action") or "").strip().lower()
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM curator_queue WHERE id=? AND tenant_id=?",
        (item_id, tenant_id),
    ).fetchone()
    if not row:
        conn.close()
        flash("Queue item not found.", "error")
        return redirect(url_for("admin.curator"))

    if action == "approve":
        conn.execute(
            "UPDATE curator_queue SET status=?, completed_at=? WHERE id=?",
            ("approved", datetime.now(timezone.utc).isoformat(), item_id),
        )
        conn.commit()
        conn.close()
        try:
            from vac_bot.tasks import run_reindex_task
            run_reindex_task.delay(tenant_id=tenant_id)
            flash("Item approved and re-index queued.", "success")
        except Exception as exc:
            flash(f"Item approved, but re-index could not be queued: {exc}", "error")
        return redirect(url_for("admin.curator"))

    if action == "dismiss":
        conn.execute(
            "UPDATE curator_queue SET status=?, completed_at=? WHERE id=?",
            ("dismissed", datetime.now(timezone.utc).isoformat(), item_id),
        )
        conn.commit()
        conn.close()
        flash("Item dismissed.", "success")
        return redirect(url_for("admin.curator"))

    conn.close()
    flash("Unknown queue action.", "error")
    return redirect(url_for("admin.curator"))


@admin_bp.route("/access")
@admin_required
def access():
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    conn = get_conn()
    users = conn.execute("SELECT id, username, role FROM users WHERE tenant_id=?", (tenant_id,)).fetchall()
    conn.close()
    admins = [dict(u) for u in users] if users else []
    invite_result = {
        "user": session.pop("last_invited_user", None),
        "temporary_password": session.pop("last_temporary_password", None),
    }
    return render_template("admin/access.html", admins=admins, invite_result=invite_result)


@admin_bp.route("/access/users/add", methods=["POST"])
@admin_required
def add_user():
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    email = (request.form.get("email") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or "viewer").strip()
    if not email:
        flash("Email is required", "error")
        return redirect(url_for("admin.access"))
    generated_pw = None
    if not password:
        # generate a temporary password
        import secrets
        password = secrets.token_urlsafe(8)
        generated_pw = password
    pw_hash = generate_password_hash(password)
    import time
    last_error = None
    for attempt in range(3):
        conn = None
        try:
            conn = get_conn()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO users (tenant_id, username, password_hash, role) VALUES (?, ?, ?, ?)",
                (tenant_id, email, pw_hash, role),
            )
            conn.commit()
            session["last_invited_user"] = email
            session["last_temporary_password"] = password
            flash(f"User {email} created.", "success")
            return redirect(url_for("admin.access"))
        except Exception as exc:
            last_error = exc
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if conn is not None:
                conn.close()
            if "database is locked" in str(exc).lower() and attempt < 2:
                time.sleep(0.25 * (attempt + 1))
                continue
            break
        finally:
            if conn is not None:
                conn.close()
    flash(f"Could not create user: {last_error}", "error")
    return redirect(url_for("admin.access"))


@admin_bp.route("/access/users/<int:user_id>/edit", methods=["POST"])
@admin_required
def edit_user(user_id):
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    role = (request.form.get("role") or "").strip()
    if role not in ("viewer", "admin"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin.access"))
    conn = get_conn()
    user = conn.execute(
        "SELECT * FROM users WHERE id=? AND tenant_id=?", (user_id, tenant_id)
    ).fetchone()
    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for("admin.access"))
    conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    conn.commit()
    conn.close()
    flash(f"User {user['username']} role updated to {role}.", "success")
    return redirect(url_for("admin.access"))


@admin_bp.route("/access/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    conn = get_conn()
    user = conn.execute(
        "SELECT * FROM users WHERE id=? AND tenant_id=?", (user_id, tenant_id)
    ).fetchone()
    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for("admin.access"))
    conn.execute("DELETE FROM users WHERE id=? AND tenant_id=?", (user_id, tenant_id))
    conn.commit()
    conn.close()
    flash(f"User {user['username']} deleted.", "success")
    return redirect(url_for("admin.access"))


@admin_bp.route("/tenants/new", methods=["GET", "POST"])
@admin_required
def new_tenant():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Tenant name required", "error")
            return redirect(url_for("admin.new_tenant"))
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "tenant"
        last_error = None
        for attempt in range(3):
            conn = None
            try:
                conn = get_conn()
                safe_name = name
                while conn.execute("SELECT 1 FROM tenants WHERE name=?", (safe_name,)).fetchone():
                    safe_name = re.sub(r"\s*\(\d+\)$", "", safe_name).strip()
                    n = 1
                    while conn.execute("SELECT 1 FROM tenants WHERE name=?", (f"{safe_name} ({n})",)).fetchone():
                        n += 1
                    safe_name = f"{safe_name} ({n})"
                name = safe_name
                while conn.execute("SELECT 1 FROM tenants WHERE slug=?", (slug,)).fetchone():
                    n = 1
                    while conn.execute("SELECT 1 FROM tenants WHERE slug=?", (f"{slug}-{n}",)).fetchone():
                        n += 1
                    slug = f"{slug}-{n}"
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT INTO tenants (name, slug) VALUES (?, ?)", (name, slug))
                tenant_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute("INSERT INTO settings (tenant_id, bot_name) VALUES (?, ?)", (tenant_id, f"{name} Assistant"))
                conn.commit()
                conn.close()
                # create an empty chroma collection by calling vectordb rebuild with no docs
                try:
                    vurl = os.getenv("VEKTORDB_URL", "http://vectordb:5001")
                    requests.post(f"{vurl}/rebuild", json={"documents": []}, headers={"X-Tenant-Id": str(tenant_id)}, timeout=10)
                except Exception:
                    pass
                flash(f"Tenant '{name}' created.", "success")
                return redirect(url_for("admin.dashboard"))
            except Exception as exc:
                last_error = exc
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                if conn is not None:
                    conn.close()
                if "database is locked" in str(exc).lower() and attempt < 2:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                break
            finally:
                if conn is not None:
                    conn.close()
        flash(f"Could not create tenant: {last_error}", "error")
        return redirect(url_for("admin.new_tenant"))
    return render_template("admin/new_tenant.html")

@admin_bp.route("/tenants")
@admin_required
def tenants():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tenants ORDER BY id").fetchall()
    conn.close()
    return render_template("admin/tenants.html", tenants=[dict(r) for r in rows])

@admin_bp.route("/tenants/<int:tenant_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_tenant(tenant_id):
    conn = get_conn()
    tenant = conn.execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    if not tenant:
        conn.close()
        flash("Tenant not found", "error")
        return redirect(url_for("admin.tenants"))
    if request.method == "POST":
        new_name = (request.form.get("name") or "").strip()
        if not new_name:
            flash("Name is required", "error")
            conn.close()
            return render_template("admin/edit_tenant.html", tenant=dict(tenant))
        try:
            conn.execute("UPDATE tenants SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_name, tenant_id))
            conn.commit()
            conn.close()
            flash("Tenant updated.", "success")
            return redirect(url_for("admin.tenants"))
        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"Could not update: {e}", "error")
            return render_template("admin/edit_tenant.html", tenant=dict(tenant))
    conn.close()
    return render_template("admin/edit_tenant.html", tenant=dict(tenant))

@admin_bp.route("/tenants/<int:tenant_id>/delete", methods=["POST"])
@admin_required
def delete_tenant(tenant_id):
    if tenant_id == 1:
        flash("Cannot delete the default tenant.", "error")
        return redirect(url_for("admin.tenants"))
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM users WHERE tenant_id=?", (tenant_id,))
        conn.execute("DELETE FROM settings WHERE tenant_id=?", (tenant_id,))
        conn.execute("DELETE FROM urls WHERE tenant_id=?", (tenant_id,))
        conn.execute("DELETE FROM documents WHERE tenant_id=?", (tenant_id,))
        conn.execute("DELETE FROM index_log WHERE tenant_id=?", (tenant_id,))
        conn.execute("DELETE FROM curator_queue WHERE tenant_id=?", (tenant_id,))
        conn.execute("DELETE FROM source_snapshots WHERE tenant_id=?", (tenant_id,))
        conn.execute("DELETE FROM tenants WHERE id=?", (tenant_id,))
        conn.commit()
        conn.close()
        flash("Tenant deleted.", "success")
    except Exception as e:
        conn.rollback()
        conn.close()
        flash(f"Could not delete: {e}", "error")
    return redirect(url_for("admin.tenants"))

@admin_bp.route("/knowledge/url/add", methods=["POST"])
@admin_required
def add_url():
    url = request.form.get("url", "").strip()
    if not url:
        flash("URL is required", "error")
        return redirect(url_for("admin.knowledge"))
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    conn = get_conn()
    conn.execute("INSERT INTO urls (tenant_id, url) VALUES (?, ?)", (tenant_id, url))
    conn.commit()
    conn.close()
    flash("URL added.", "success")
    return redirect(url_for("admin.knowledge"))

@admin_bp.route("/knowledge/url/<int:url_id>/delete", methods=["POST"])
@admin_required
def delete_url(url_id):
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    conn = get_conn()
    conn.execute("DELETE FROM urls WHERE id=? AND tenant_id=?", (url_id, tenant_id))
    conn.commit()
    conn.close()
    flash("URL removed.", "success")
    if request.form.get("rebuild"):
        return redirect(url_for("admin.rebuild"))
    return redirect(url_for("admin.knowledge"))

ALLOWED_EXTENSIONS = {
    "pdf": "pdf",
    "png": "image", "jpg": "image", "jpeg": "image", "gif": "image", "webp": "image",
    "xlsx": "table", "csv": "table",
    "pptx": "slides",
}

@admin_bp.route("/knowledge/doc/upload", methods=["POST"])
@admin_required
def upload_doc():
    if "file" not in request.files:
        flash("No file selected", "error")
        return redirect(url_for("admin.knowledge"))
    file = request.files["file"]
    if not file or not file.filename:
        flash("No file selected", "error")
        return redirect(url_for("admin.knowledge"))
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    doc_type = ALLOWED_EXTENSIONS.get(ext)
    if not doc_type:
        flash(f"Unsupported file type (.{ext}). Allowed: pdf, png, jpg, jpeg, gif, webp, xlsx, csv, pptx", "error")
        return redirect(url_for("admin.knowledge"))
    filename = secure_filename(file.filename)
    uploads_dir = Path(current_app.root_path) / "uploads"
    uploads_dir.mkdir(exist_ok=True)
    filepath = uploads_dir / filename
    file.save(str(filepath))
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    conn = get_conn()
    conn.execute("INSERT INTO documents (tenant_id, filename, filepath, status, doc_type) VALUES (?, ?, ?, ?, ?)",
                 (tenant_id, filename, str(filepath), "ready", doc_type))
    conn.commit()
    conn.close()
    flash(f"Uploaded {filename}. Rebuild index to include it.", "success")
    return redirect(url_for("admin.knowledge"))

@admin_bp.route("/knowledge/doc/<int:doc_id>/delete", methods=["POST"])
@admin_required
def delete_doc(doc_id):
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    conn = get_conn()
    row = conn.execute("SELECT filepath, filename FROM documents WHERE id=? AND tenant_id=?", (doc_id, tenant_id)).fetchone()
    if row:
        fp = row["filepath"]
        if os.path.exists(fp):
            os.remove(fp)
    conn.execute("DELETE FROM documents WHERE id=? AND tenant_id=?", (doc_id, tenant_id))
    conn.commit()
    conn.close()
    flash(f"Removed {row['filename']}.", "success")
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
        tenant_id = session.get("tenant_id") or get_default_tenant_id()
        result = rebuild_vectordb(tenant_id=tenant_id)
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
