from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone


@dataclass
class User:
    id: Optional[int] = None
    tenant_id: int = 1
    username: str = ""
    password_hash: str = ""
    role: str = "viewer"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @classmethod
    def from_row(cls, row) -> "User":
        if row is None:
            return cls()
        d = dict(row)
        return cls(
            id=d.get("id"),
            tenant_id=d.get("tenant_id", 1),
            username=d.get("username", ""),
            password_hash=d.get("password_hash", ""),
            role=d.get("role", "viewer"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )
