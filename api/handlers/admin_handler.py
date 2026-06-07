import os
import re
import secrets
import time
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from werkzeug.security import generate_password_hash
from api.dto import (
    AdminLoginRequest, AdminLoginResponse,
    SettingsUpdateRequest,
    UserInviteRequest, UserEditRequest,
    TenantCreateRequest, TenantEditRequest,
    KnowledgeAddUrlRequest,
    CuratorActionRequest,
)
from api.interfaces import SessionProvider
from services.auth_service import AuthService
from db import get_conn, get_settings as load_settings, get_default_tenant_id, get_tenant
from vac_bot.curator import get_curator_dashboard_state


class AdminHandler:
    def __init__(self, session_provider: SessionProvider):
        self._session = session_provider
        self._auth_service = AuthService(session_provider)

    # --- Auth ---

    def login(self, req: AdminLoginRequest) -> AdminLoginResponse:
        result = self._auth_service.login_admin(req.username, req.password)
        if result.success:
            return AdminLoginResponse(success=True)
        return AdminLoginResponse(success=False, error="Invalid credentials")

    def logout(self) -> None:
        self._auth_service.logout_admin()

    def is_admin(self) -> bool:
        return self._session.is_admin_logged_in()

    # --- Dashboard ---

    def get_dashboard_stats(self) -> dict:
        conn = get_conn()
        url_count = conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0]
        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        settings = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
        conn.close()
        return {
            "url_count": url_count,
            "doc_count": doc_count,
            "settings": dict(settings) if settings else {},
        }

    # --- Settings ---

    def update_settings(self, req: SettingsUpdateRequest) -> str:
        conn = get_conn()
        row = conn.execute("SELECT id FROM settings WHERE tenant_id=?", (req.tenant_id,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO settings (tenant_id, bot_name, language) VALUES (?, ?, ?)",
                (req.tenant_id, req.bot_name or "B2b BOTS", req.language or "en"),
            )
        conn.execute(
            "UPDATE settings SET bot_name=?, theme=?, language=?, personality=?, tone=?, purpose=?, instructions=?, llm_provider=?, llm_model=?, llm_api_key=?, llm_base_url=?, updated_at=? WHERE tenant_id=?",
            (
                req.bot_name or "B2b BOTS",
                req.theme,
                req.language,
                req.personality,
                req.tone,
                req.purpose,
                req.instructions,
                req.llm_provider,
                req.llm_model,
                req.llm_api_key,
                req.llm_base_url,
                datetime.now(timezone.utc).isoformat(),
                req.tenant_id,
            )
        )
        conn.commit()
        conn.close()
        from vac_bot.chain import rebuild_chain
        rebuild_chain()
        return "Settings saved and chain will rebuild on next question."

    def get_settings(self) -> dict:
        return load_settings()

    def get_context_vars(self) -> dict:
        tid = self._session.get("tenant_id") or get_default_tenant_id()
        settings = load_settings(tid)
        theme = (settings.get("theme") or "dark").strip().lower()
        tenant = get_tenant(tid)
        tenant_name = tenant.get("name") if tenant else "Tenant"
        tenant_slug = tenant.get("slug") if tenant else "default"
        bot_avatar = settings.get("bot_avatar") or ""
        DEFAULT_BOT_NAME = "B2b BOTS"
        return {
            "admin_brand_name": settings.get("bot_name") or DEFAULT_BOT_NAME,
            "admin_theme": theme,
            "admin_language": settings.get("language") or "en",
            "tenant_name": tenant_name,
            "tenant_slug": tenant_slug,
            "tenant_id": tid,
            "tenant_plan": "Pro plan",
            "bot_avatar_url": bot_avatar,
        }

    def delete_avatar(self, tenant_id: int) -> None:
        conn = get_conn()
        row = conn.execute("SELECT bot_avatar FROM settings WHERE tenant_id=?", (tenant_id,)).fetchone()
        if row and row["bot_avatar"]:
            avatar_path = Path(os.getcwd()) / "uploads" / "avatars" / row["bot_avatar"]
            if avatar_path.exists():
                avatar_path.unlink()
            conn.execute("UPDATE settings SET bot_avatar='' WHERE tenant_id=?", (tenant_id,))
            conn.commit()
        conn.close()

    # --- Knowledge ---

    def get_knowledge_data(self) -> dict:
        tenant_id = self._session.get_tenant_id() or get_default_tenant_id()
        conn = get_conn()
        urls = conn.execute(
            "SELECT * FROM urls WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,)
        ).fetchall()
        docs = conn.execute(
            "SELECT * FROM documents WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,)
        ).fetchall()
        conn.close()
        all_docs = [dict(d) for d in docs]
        return {
            "urls": [dict(u) for u in urls],
            "docs": all_docs,
            "pdfs": [d for d in all_docs if d["doc_type"] in (None, "", "pdf")],
            "images": [d for d in all_docs if d["doc_type"] == "image"],
            "tables": [d for d in all_docs if d["doc_type"] == "table"],
            "slides": [d for d in all_docs if d["doc_type"] == "slides"],
            "scanned": [d for d in all_docs if d["doc_type"] == "scanned"],
        }

    def add_url(self, req: KnowledgeAddUrlRequest) -> str:
        if not req.url:
            return "URL is required"
        conn = get_conn()
        conn.execute("INSERT INTO urls (tenant_id, url) VALUES (?, ?)", (req.tenant_id, req.url))
        conn.commit()
        conn.close()
        return "URL added."

    def delete_url(self, url_id: int, rebuild: bool = False) -> str:
        tenant_id = self._session.get_tenant_id() or get_default_tenant_id()
        conn = get_conn()
        conn.execute("DELETE FROM urls WHERE id=? AND tenant_id=?", (url_id, tenant_id))
        conn.commit()
        conn.close()
        return "URL removed."

    def upload_doc(self, filename: str, file_data: bytes, doc_type: str) -> str:
        uploads_dir = Path(os.getcwd()) / "uploads"
        uploads_dir.mkdir(exist_ok=True)
        filepath = uploads_dir / filename
        filepath.write_bytes(file_data)
        tenant_id = self._session.get_tenant_id() or get_default_tenant_id()
        conn = get_conn()
        conn.execute(
            "INSERT INTO documents (tenant_id, filename, filepath, status, doc_type) VALUES (?, ?, ?, ?, ?)",
            (tenant_id, filename, str(filepath), "ready", doc_type),
        )
        conn.commit()
        conn.close()
        return f"Uploaded {filename}. Rebuild index to include it."

    def delete_doc(self, doc_id: int, rebuild: bool = False) -> str:
        tenant_id = self._session.get_tenant_id() or get_default_tenant_id()
        conn = get_conn()
        row = conn.execute(
            "SELECT filepath, filename FROM documents WHERE id=? AND tenant_id=?",
            (doc_id, tenant_id),
        ).fetchone()
        if row:
            fp = row["filepath"]
            if os.path.exists(fp):
                os.remove(fp)
        conn.execute("DELETE FROM documents WHERE id=? AND tenant_id=?", (doc_id, tenant_id))
        conn.commit()
        conn.close()
        return f"Removed {row['filename']}."

    def rebuild_index(self) -> str:
        from vac_bot.loader import rebuild_vectordb
        from vac_bot.chain import rebuild_chain

        conn = get_conn()
        conn.execute("INSERT INTO index_log (status) VALUES ('in_progress')")
        log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        try:
            tenant_id = self._session.get_tenant_id() or get_default_tenant_id()
            result = rebuild_vectordb(tenant_id=tenant_id)
            rebuild_chain()
            count = result.get("count", 0)
            warnings = result.get("warnings", [])

            conn = get_conn()
            conn.execute(
                "UPDATE index_log SET completed_at=?, total_chunks=?, status=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), count, "completed", log_id),
            )
            conn.commit()
            conn.close()

            msg = f"Index rebuilt with {count} chunks."
            if warnings:
                msg += f" Warnings ({len(warnings)}): " + "; ".join(warnings[:3])
                if len(warnings) > 3:
                    msg += f" (+{len(warnings)-3} more)"
            return msg
        except Exception as e:
            conn = get_conn()
            conn.execute(
                "UPDATE index_log SET completed_at=?, status=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), f"failed: {e}", log_id),
            )
            conn.commit()
            conn.close()
            raise

    # --- Curator ---

    def get_curator_state(self) -> dict:
        tenant_id = self._session.get_tenant_id() or get_default_tenant_id()
        return get_curator_dashboard_state(tenant_id)

    def queue_curator_scan(self) -> str:
        tenant_id = self._session.get_tenant_id() or get_default_tenant_id()
        from vac_bot.tasks import run_change_detection_task
        task = run_change_detection_task.delay(tenant_id=tenant_id)
        return f"Curator scan queued. Task {task.id} will update the work queue in the background."

    def curator_item_action(self, req: CuratorActionRequest) -> str:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM curator_queue WHERE id=? AND tenant_id=?",
            (req.item_id, req.tenant_id),
        ).fetchone()
        if not row:
            conn.close()
            return "Queue item not found."

        if req.action == "approve":
            conn.execute(
                "UPDATE curator_queue SET status=?, completed_at=? WHERE id=?",
                ("approved", datetime.now(timezone.utc).isoformat(), req.item_id),
            )
            conn.commit()
            conn.close()
            try:
                from vac_bot.tasks import run_reindex_task
                run_reindex_task.delay(tenant_id=req.tenant_id)
                return "Item approved and re-index queued."
            except Exception as exc:
                return f"Item approved, but re-index could not be queued: {exc}"

        if req.action == "dismiss":
            conn.execute(
                "UPDATE curator_queue SET status=?, completed_at=? WHERE id=?",
                ("dismissed", datetime.now(timezone.utc).isoformat(), req.item_id),
            )
            conn.commit()
            conn.close()
            return "Item dismissed."

        conn.close()
        return "Unknown queue action."

    # --- Access ---

    def get_access_data(self) -> dict:
        tenant_id = self._session.get_tenant_id() or get_default_tenant_id()
        conn = get_conn()
        users = conn.execute(
            "SELECT id, username, role FROM users WHERE tenant_id=?", (tenant_id,)
        ).fetchall()
        conn.close()
        admins = [dict(u) for u in users] if users else []
        invite_result = {
            "user": self._session.pop("last_invited_user", None),
            "temporary_password": self._session.pop("last_temporary_password", None),
        }
        return {"admins": admins, "invite_result": invite_result}

    def add_user(self, req: UserInviteRequest) -> str:
        password = req.password
        generated = False
        if not password:
            password = secrets.token_urlsafe(8)
            generated = True

        pw_hash = generate_password_hash(password)
        last_error = None
        for attempt in range(3):
            conn = None
            try:
                conn = get_conn()
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO users (tenant_id, username, password_hash, role) VALUES (?, ?, ?, ?)",
                    (req.tenant_id, req.email, pw_hash, req.role),
                )
                conn.commit()
                self._session.set("last_invited_user", req.email)
                self._session.set("last_temporary_password", password if generated else "")
                return f"User {req.email} created."
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
                    try:
                        conn.close()
                    except Exception:
                        pass
        return f"Could not create user: {last_error}"

    def edit_user(self, req: UserEditRequest) -> str:
        if req.role not in ("viewer", "admin"):
            return "Invalid role."
        conn = get_conn()
        user = conn.execute(
            "SELECT * FROM users WHERE id=? AND tenant_id=?", (req.user_id, req.tenant_id)
        ).fetchone()
        if not user:
            conn.close()
            return "User not found."
        conn.execute("UPDATE users SET role=? WHERE id=?", (req.role, req.user_id))
        conn.commit()
        conn.close()
        return f"User {user['username']} role updated to {req.role}."

    def delete_user(self, user_id: int) -> str:
        tenant_id = self._session.get_tenant_id() or get_default_tenant_id()
        conn = get_conn()
        user = conn.execute(
            "SELECT * FROM users WHERE id=? AND tenant_id=?", (user_id, tenant_id)
        ).fetchone()
        if not user:
            conn.close()
            return "User not found."
        conn.execute("DELETE FROM users WHERE id=? AND tenant_id=?", (user_id, tenant_id))
        conn.commit()
        conn.close()
        return f"User {user['username']} deleted."

    # --- Tenants ---

    def list_tenants(self) -> list:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM tenants ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def create_tenant(self, req: TenantCreateRequest) -> str:
        if not req.name:
            return "Tenant name required"
        slug = re.sub(r"[^a-z0-9]+", "-", req.name.lower()).strip("-") or "tenant"
        last_error = None
        for attempt in range(3):
            conn = None
            try:
                conn = get_conn()
                safe_name = req.name
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
                conn.execute(
                    "INSERT INTO settings (tenant_id, bot_name) VALUES (?, ?)",
                    (tenant_id, f"{name} Assistant"),
                )
                conn.commit()
                conn.close()
                try:
                    vurl = os.getenv("VEKTORDB_URL", "http://vectordb:5001")
                    requests.post(
                        f"{vurl}/rebuild",
                        json={"documents": []},
                        headers={"X-Tenant-Id": str(tenant_id)},
                        timeout=10,
                    )
                except Exception:
                    pass
                return f"Tenant '{name}' created."
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
                    try:
                        conn.close()
                    except Exception:
                        pass
        return f"Could not create tenant: {last_error}"

    def get_tenant(self, tenant_id: int) -> Optional[dict]:
        return get_tenant(tenant_id)

    def edit_tenant(self, req: TenantEditRequest) -> str:
        conn = get_conn()
        tenant = conn.execute("SELECT * FROM tenants WHERE id=?", (req.tenant_id,)).fetchone()
        if not tenant:
            conn.close()
            return "Tenant not found"
        try:
            conn.execute(
                "UPDATE tenants SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (req.name, req.tenant_id),
            )
            conn.commit()
            conn.close()
            return "Tenant updated."
        except Exception as e:
            conn.rollback()
            conn.close()
            return f"Could not update: {e}"

    def delete_tenant(self, tenant_id: int) -> str:
        if tenant_id == 1:
            return "Cannot delete the default tenant."
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
            return "Tenant deleted."
        except Exception as e:
            conn.rollback()
            conn.close()
            return f"Could not delete: {e}"
