from typing import Optional
from db import get_conn
from models.tenant import Tenant
from repositories.base import Repository


class TenantRepository(Repository[Tenant]):
    def get_by_id(self, tenant_id: int) -> Optional[Tenant]:
        conn = get_conn()
        row = conn.execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        conn.close()
        return Tenant.from_row(row)

    def get_default(self) -> Optional[Tenant]:
        conn = get_conn()
        row = conn.execute("SELECT * FROM tenants ORDER BY id LIMIT 1").fetchone()
        conn.close()
        return Tenant.from_row(row)

    def list_all(self) -> list[Tenant]:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM tenants ORDER BY id").fetchall()
        conn.close()
        return [Tenant.from_row(r) for r in rows]

    def save(self, tenant: Tenant) -> Tenant:
        conn = get_conn()
        cur = conn.execute(
            "INSERT INTO tenants (name, slug, status) VALUES (?, ?, ?)",
            (tenant.name, tenant.slug, tenant.status),
        )
        tenant.id = cur.lastrowid
        conn.commit()
        conn.close()
        return tenant

    def update_name(self, tenant_id: int, name: str) -> None:
        conn = get_conn()
        conn.execute(
            "UPDATE tenants SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (name, tenant_id),
        )
        conn.commit()
        conn.close()

    def delete(self, tenant_id: int) -> None:
        conn = get_conn()
        conn.execute("DELETE FROM tenants WHERE id=?", (tenant_id,))
        conn.commit()
        conn.close()
