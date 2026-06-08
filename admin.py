import os
from pathlib import Path
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, current_app
)
from werkzeug.utils import secure_filename
from db import get_conn, get_settings as load_settings, get_default_tenant_id
from api.flask.adapters import FlaskSessionProvider
from api import AdminHandler, AuthHandler
from api.dto import (
    AdminLoginRequest, LoginRequest, SettingsUpdateRequest,
    UserInviteRequest, UserEditRequest,
    TenantCreateRequest, TenantEditRequest,
    KnowledgeAddUrlRequest, CuratorActionRequest,
)
from vac_bot.chain import PROVIDER_OPTIONS

session_provider = FlaskSessionProvider()
admin_handler = AdminHandler(session_provider)
auth_handler = AuthHandler(session_provider)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

DEFAULT_BOT_NAME = "B2b BOTS"
DEFAULT_THEME = "dark"
DEFAULT_LANGUAGE = "en"

THEME_OPTIONS = ["dark", "light"]
LANGUAGE_OPTIONS = {
    "en": "English",
    "bn": "বাংলা (Bangla)",
}
PERSONALITY_OPTIONS = [
    "Professional", "Warm and empathetic", "Friendly and conversational",
    "Concise and direct", "Expert and authoritative",
]
TONE_OPTIONS = [
    "Professional and helpful", "Warm and supportive", "Concise and direct",
    "Calm and reassuring", "Friendly and approachable",
]
PURPOSE_OPTIONS = [
    "FAQ assistant", "Support triage assistant", "Onboarding assistant",
    "Policy and guidance assistant", "Knowledge base assistant",
]

ALLOWED_EXTENSIONS = {
    "pdf": "pdf",
    "png": "image", "jpg": "image", "jpeg": "image", "gif": "image", "webp": "image",
    "xlsx": "table", "csv": "table",
    "pptx": "slides",
}


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not admin_handler.is_admin():
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.app_context_processor
def inject_admin_brand_name():
    return admin_handler.get_context_vars()


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        # Try super-admin (env-var) auth first
        result = admin_handler.login(AdminLoginRequest(username=username, password=password))
        if result.success:
            return redirect(url_for("admin.dashboard"))
        # Then try tenant user (DB) auth
        user_result = auth_handler.login(LoginRequest(username=username, password=password))
        if user_result.success:
            session["admin"] = True
            return redirect(url_for("admin.dashboard"))
        flash("Invalid credentials", "error")
    return render_template("admin/login.html")


@admin_bp.route("/logout", methods=["POST"])
def logout():
    admin_handler.logout()
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@admin_required
def dashboard():
    stats = admin_handler.get_dashboard_stats()
    return render_template(
        "admin/dashboard.html",
        url_count=stats["url_count"],
        doc_count=stats["doc_count"],
        settings=stats["settings"],
    )


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        tenant_id = session.get("tenant_id") or get_default_tenant_id()
        theme = request.form.get("theme", DEFAULT_THEME).strip().lower()
        if theme not in THEME_OPTIONS:
            theme = DEFAULT_THEME

        req = SettingsUpdateRequest(
            tenant_id=tenant_id,
            bot_name=(request.form.get("bot_name") or "").strip(),
            theme=theme,
            language=request.form.get("language", "en").strip().lower(),
            personality=request.form.get("personality", ""),
            tone=request.form.get("tone", ""),
            purpose=request.form.get("purpose", ""),
            instructions=request.form.get("instructions", ""),
            llm_provider=(request.form.get("llm_provider") or "openai").strip(),
            llm_model=(request.form.get("llm_model") or "gpt-4o-mini").strip(),
            llm_api_key=(request.form.get("llm_api_key") or "").strip(),
            llm_base_url=(request.form.get("llm_base_url") or "").strip(),
        )
        msg = admin_handler.update_settings(req)

        avatar = request.files.get("bot_avatar")
        if avatar and avatar.filename:
            ext = avatar.filename.rsplit(".", 1)[-1].lower() if "." in avatar.filename else "png"
            if ext in ("png", "jpg", "jpeg", "gif", "webp"):
                avatars_dir = Path(current_app.root_path) / "uploads" / "avatars"
                avatars_dir.mkdir(parents=True, exist_ok=True)
                avatar_path = avatars_dir / f"tenant_{tenant_id}.{ext}"
                avatar.save(str(avatar_path))
                conn = get_conn()
                conn.execute(
                    "UPDATE settings SET bot_avatar=? WHERE tenant_id=?",
                    (f"tenant_{tenant_id}.{ext}", tenant_id),
                )
                conn.commit()
                conn.close()

        flash(msg, "success")
        return redirect(url_for("admin.settings"))

    s = load_settings()
    bot_avatar = s.get("bot_avatar") or ""
    provider_models = {
        "openai": "gpt-4o-mini, gpt-4o, gpt-4-turbo, gpt-3.5-turbo",
        "azure_openai": "gpt-4o-mini, gpt-4o, gpt-4",
        "anthropic": "claude-sonnet-4-20250514, claude-haiku-4-20250514, claude-opus-4-20250514",
        "google": "gemini-2.0-flash, gemini-2.0-pro, gemini-1.5-flash, gemini-1.5-pro",
        "groq": "llama3-70b-8192, llama3-8b-8192, mixtral-8x7b-32768",
        "openai_compat": "custom model name (e.g. deepseek-chat, grok-2-1212, llama3)",
    }
    return render_template(
        "admin/settings.html",
        settings=s,
        bot_avatar_url=bot_avatar,
        theme_options=THEME_OPTIONS,
        language_options=LANGUAGE_OPTIONS,
        personality_options=PERSONALITY_OPTIONS,
        tone_options=TONE_OPTIONS,
        purpose_options=PURPOSE_OPTIONS,
        provider_options=PROVIDER_OPTIONS,
        provider_models=provider_models,
    )


@admin_bp.route("/avatar/<int:tenant_id>")
def tenant_avatar(tenant_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT bot_avatar FROM settings WHERE tenant_id=?", (tenant_id,)
    ).fetchone()
    conn.close()
    if not row or not row["bot_avatar"]:
        return "", 204
    avatar_path = (
        Path(current_app.root_path) / "uploads" / "avatars" / row["bot_avatar"]
    )
    if not avatar_path.exists():
        return "", 204
    ext = avatar_path.suffix.lower().lstrip(".")
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "image/png")
    return open(avatar_path, "rb").read(), 200, {
        "Content-Type": mime,
        "Cache-Control": "max-age=86400",
    }


@admin_bp.route("/knowledge")
@admin_required
def knowledge():
    data = admin_handler.get_knowledge_data()
    return render_template(
        "admin/knowledge.html",
        urls=data["urls"],
        docs=data["docs"],
        pdfs=data["pdfs"],
        images=data["images"],
        tables=data["tables"],
        slides=data["slides"],
        scanned=data["scanned"],
    )


@admin_bp.route("/curator")
@admin_required
def curator():
    state = admin_handler.get_curator_state()
    return render_template(
        "admin/curator.html",
        queue=state["queue"],
        snapshots=state["snapshots"],
    )


@admin_bp.route("/curator/scan", methods=["POST"])
@admin_required
def curator_scan():
    try:
        msg = admin_handler.queue_curator_scan()
        flash(msg, "success")
    except Exception as exc:
        flash(f"Could not queue curator scan: {exc}", "error")
    return redirect(url_for("admin.curator"))


@admin_bp.route("/curator/item/<int:item_id>/action", methods=["POST"])
@admin_required
def curator_item_action(item_id):
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    action = (request.form.get("action") or "").strip().lower()
    msg = admin_handler.curator_item_action(
        CuratorActionRequest(tenant_id=tenant_id, item_id=item_id, action=action)
    )
    if "not found" in msg.lower():
        flash(msg, "error")
    elif "unknown" in msg.lower():
        flash(msg, "error")
    else:
        flash(msg, "success")
    return redirect(url_for("admin.curator"))


@admin_bp.route("/access")
@admin_required
def access():
    data = admin_handler.get_access_data()
    return render_template(
        "admin/access.html",
        admins=data["admins"],
        invite_result=data["invite_result"],
    )


@admin_bp.route("/access/users/add", methods=["POST"])
@admin_required
def add_user():
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    req = UserInviteRequest(
        tenant_id=tenant_id,
        email=(request.form.get("email") or "").strip(),
        password=(request.form.get("password") or "").strip(),
    )
    if not req.email:
        flash("Email is required", "error")
        return redirect(url_for("admin.access"))
    msg = admin_handler.add_user(req)
    flash(msg, "success" if "created" in msg else "error")
    return redirect(url_for("admin.access"))


@admin_bp.route("/access/users/<int:user_id>/edit", methods=["POST"])
@admin_required
def edit_user(user_id):
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    msg = admin_handler.edit_user(
        UserEditRequest(user_id=user_id, tenant_id=tenant_id)
    )
    flash(msg, "success" if "updated" in msg else "error")
    return redirect(url_for("admin.access"))


@admin_bp.route("/access/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    msg = admin_handler.delete_user(user_id)
    flash(msg, "success" if "deleted" in msg.lower() else "error")
    return redirect(url_for("admin.access"))


@admin_bp.route("/tenants/new", methods=["GET", "POST"])
@admin_required
def new_tenant():
    if request.method == "POST":
        msg = admin_handler.create_tenant(
            TenantCreateRequest(name=(request.form.get("name") or "").strip())
        )
        flash(msg, "success" if "created" in msg.lower() else "error")
        if "created" in msg.lower():
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("admin.new_tenant"))
    return render_template("admin/new_tenant.html")


@admin_bp.route("/tenants")
@admin_required
def tenants():
    return render_template("admin/tenants.html", tenants=admin_handler.list_tenants())


@admin_bp.route("/tenants/<int:tenant_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_tenant(tenant_id):
    if request.method == "POST":
        msg = admin_handler.edit_tenant(
            TenantEditRequest(
                tenant_id=tenant_id,
                name=(request.form.get("name") or "").strip(),
            )
        )
        flash(msg, "success" if "updated" in msg.lower() else "error")
        if "updated" in msg.lower():
            return redirect(url_for("admin.tenants"))
    tenant = admin_handler.get_tenant(tenant_id)
    if not tenant:
        flash("Tenant not found", "error")
        return redirect(url_for("admin.tenants"))
    return render_template("admin/edit_tenant.html", tenant=tenant)


@admin_bp.route("/tenants/<int:tenant_id>/delete", methods=["POST"])
@admin_required
def delete_tenant(tenant_id):
    msg = admin_handler.delete_tenant(tenant_id)
    flash(msg, "error" if "cannot" in msg.lower() else "success")
    return redirect(url_for("admin.tenants"))


@admin_bp.route("/knowledge/url/add", methods=["POST"])
@admin_required
def add_url():
    tenant_id = session.get("tenant_id") or get_default_tenant_id()
    msg = admin_handler.add_url(
        KnowledgeAddUrlRequest(
            tenant_id=tenant_id,
            url=(request.form.get("url") or "").strip(),
        )
    )
    flash(msg, "success" if "added" in msg.lower() else "error")
    return redirect(url_for("admin.knowledge"))


@admin_bp.route("/knowledge/url/<int:url_id>/delete", methods=["POST"])
@admin_required
def delete_url(url_id):
    msg = admin_handler.delete_url(url_id, bool(request.form.get("rebuild")))
    flash(msg, "success")
    if request.form.get("rebuild"):
        return redirect(url_for("admin.rebuild"))
    return redirect(url_for("admin.knowledge"))


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
        flash(
            f"Unsupported file type (.{ext}). Allowed: pdf, png, jpg, jpeg, gif, webp, xlsx, csv, pptx",
            "error",
        )
        return redirect(url_for("admin.knowledge"))

    filename = secure_filename(file.filename)
    msg = admin_handler.upload_doc(filename, file.read(), doc_type)
    flash(msg, "success")
    return redirect(url_for("admin.knowledge"))


@admin_bp.route("/knowledge/doc/<int:doc_id>/delete", methods=["POST"])
@admin_required
def delete_doc(doc_id):
    msg = admin_handler.delete_doc(doc_id, bool(request.form.get("rebuild")))
    flash(msg, "success")
    if request.form.get("rebuild"):
        return redirect(url_for("admin.rebuild"))
    return redirect(url_for("admin.knowledge"))


@admin_bp.route("/knowledge/rebuild", methods=["POST"])
@admin_required
def rebuild():
    try:
        msg = admin_handler.rebuild_index()
        flash(msg, "success")
    except Exception as e:
        flash(f"Rebuild failed: {e}", "error")
    return redirect(url_for("admin.dashboard"))
