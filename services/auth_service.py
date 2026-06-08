import re
from typing import Optional
from werkzeug.security import generate_password_hash
from auth import AuthFactory, AuthResult
from repositories.user_repo import UserRepository
from repositories.tenant_repo import TenantRepository
from api.interfaces import SessionProvider


class AuthService:
    def __init__(self, session_provider: SessionProvider):
        self._session = session_provider
        self._user_repo = UserRepository()
        self._tenant_repo = TenantRepository()

    def login_user(self, username: str, password: str) -> AuthResult:
        result = AuthFactory.authenticate_user(username, password)
        if result.success:
            self._set_session(
                user_id=result.user_id,
                tenant_id=result.tenant_id,
                username=result.username,
                role=result.role,
            )
        return result

    def login_admin(self, username: str, password: str) -> AuthResult:
        result = AuthFactory.authenticate_admin(username, password)
        if result.success:
            self._session.set("admin", True)
            self._set_session(
                user_id=result.user_id,
                tenant_id=result.tenant_id,
                username=result.username,
                role=result.role,
            )
        return result

    def signup(
        self, business_name: str, email: str, password: str
    ) -> AuthResult:
        if not business_name or not email or not password:
            return AuthResult(success=False, error="All fields are required")
        if len(password) < 6:
            return AuthResult(success=False, error="Password must be at least 6 characters")
        if self._user_repo.exists_by_username(email):
            return AuthResult(success=False, error="An account with this email already exists")

        slug = re.sub(r"[^a-z0-9]+", "-", business_name.lower()).strip("-") or "tenant"
        from db import get_conn

        conn = get_conn()
        try:
            name = business_name
            while conn.execute("SELECT 1 FROM tenants WHERE name=?", (name,)).fetchone():
                name = re.sub(r"\s*\(\d+\)$", "", name).strip()
                n = 1
                while conn.execute("SELECT 1 FROM tenants WHERE name=?", (f"{name} ({n})",)).fetchone():
                    n += 1
                name = f"{name} ({n})"
            while conn.execute("SELECT 1 FROM tenants WHERE slug=?", (slug,)).fetchone():
                n = 1
                while conn.execute("SELECT 1 FROM tenants WHERE slug=?", (f"{slug}-{n}",)).fetchone():
                    n += 1
                slug = f"{slug}-{n}"
            conn.execute(
                "INSERT INTO tenants (name, slug, status) VALUES (?, ?, ?)",
                (name, slug, "active"),
            )
            tenant_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO settings (tenant_id, bot_name) VALUES (?, ?)",
                (tenant_id, name + " Bot"),
            )
            conn.execute(
                "INSERT INTO users (tenant_id, username, password_hash, role) VALUES (?, ?, ?, ?)",
                (tenant_id, email, generate_password_hash(password), "tenant"),
            )
            conn.commit()
            user = conn.execute(
                "SELECT id FROM users WHERE username=?", (email,)
            ).fetchone()
            conn.close()
            self._set_session(
                user_id=user["id"],
                tenant_id=tenant_id,
                username=email,
                role="tenant",
            )
            return AuthResult(success=True, user_id=user["id"], tenant_id=tenant_id, username=email, role="tenant")
        except Exception as e:
            conn.close()
            return AuthResult(success=False, error=str(e))

    def logout_user(self) -> None:
        self._session.pop("user_id", None)
        self._session.pop("tenant_id", None)
        self._session.pop("username", None)
        self._session.pop("user_role", None)

    def logout_admin(self) -> None:
        self._session.pop("admin", None)
        self._session.pop("user_id", None)
        self._session.pop("tenant_id", None)
        self._session.pop("username", None)
        self._session.pop("user_role", None)

    def change_password(self, user_id: int, current: str, newpw: str) -> tuple[bool, str]:
        from werkzeug.security import check_password_hash
        user = self._user_repo.get_by_id(user_id)
        if user is None:
            return False, "User not found"
        if not check_password_hash(user.password_hash, current):
            return False, "Current password is incorrect"
        self._user_repo.update_password(user_id, generate_password_hash(newpw))
        return True, "Password updated"

    def is_logged_in(self) -> bool:
        return self._session.is_logged_in()

    def is_admin_logged_in(self) -> bool:
        return self._session.is_admin_logged_in()

    def _set_session(self, user_id: int, tenant_id: int, username: str, role: str) -> None:
        self._session.set("user_id", user_id)
        self._session.set("tenant_id", tenant_id)
        self._session.set("username", username)
        self._session.set("user_role", role)
