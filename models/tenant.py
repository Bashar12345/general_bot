from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Tenant:
    id: Optional[int] = None
    name: str = ""
    slug: str = ""
    status: str = "active"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Tenant":
        if row is None:
            return cls()
        d = dict(row)
        return cls(
            id=d.get("id"),
            name=d.get("name", ""),
            slug=d.get("slug", ""),
            status=d.get("status", "active"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )
