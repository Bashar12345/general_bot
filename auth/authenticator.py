from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AuthResult:
    success: bool = False
    user_id: Optional[int] = None
    tenant_id: Optional[int] = None
    username: str = ""
    role: str = "viewer"
    error: str = ""


class Authenticator(ABC):
    @abstractmethod
    def authenticate(self, username: str, password: str) -> AuthResult:
        ...
