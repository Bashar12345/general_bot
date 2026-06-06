from typing import Optional
from db import get_conn
from models.user import User
from repositories.base import Repository


class UserRepository(Repository[User]):
    def get_by_id(self, user_id: int) -> Optional[User]:
        conn = get_conn()
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        return User.from_row(row)

    def get_by_username(self, username: str) -> Optional[User]:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        conn.close()
        return User.from_row(row)

    def get_by_username_and_tenant(self, username: str, tenant_id: int) -> Optional[User]:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND tenant_id=?",
            (username, tenant_id),
        ).fetchone()
        conn.close()
        return User.from_row(row)

    def list_by_tenant(self, tenant_id: int) -> list[User]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM users WHERE tenant_id=?", (tenant_id,)
        ).fetchall()
        conn.close()
        return [User.from_row(r) for r in rows]

    def exists_by_username(self, username: str) -> bool:
        conn = get_conn()
        row = conn.execute(
            "SELECT 1 FROM users WHERE username=?", (username,)
        ).fetchone()
        conn.close()
        return row is not None

    def save(self, user: User) -> User:
        conn = get_conn()
        cur = conn.execute(
            "INSERT INTO users (tenant_id, username, password_hash, role) VALUES (?, ?, ?, ?)",
            (user.tenant_id, user.username, user.password_hash, user.role),
        )
        user.id = cur.lastrowid
        conn.commit()
        conn.close()
        return user

    def update_role(self, user_id: int, role: str) -> None:
        conn = get_conn()
        conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        conn.commit()
        conn.close()

    def update_password(self, user_id: int, password_hash: str) -> None:
        conn = get_conn()
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id)
        )
        conn.commit()
        conn.close()

    def delete(self, user_id: int, tenant_id: int) -> None:
        conn = get_conn()
        conn.execute("DELETE FROM users WHERE id=? AND tenant_id=?", (user_id, tenant_id))
        conn.commit()
        conn.close()
