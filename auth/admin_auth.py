import os
from auth.authenticator import Authenticator, AuthResult
from repositories.tenant_repo import TenantRepository


class AdminAuthenticator(Authenticator):
    def __init__(self, tenant_repo: TenantRepository | None = None):
        self._username = os.getenv("ADMIN_USERNAME", "admin")
        self._password = os.getenv("ADMIN_PASSWORD", "admin123")
        self._tenant_repo = tenant_repo or TenantRepository()

    def authenticate(self, username: str, password: str) -> AuthResult:
        if username != self._username or password != self._password:
            return AuthResult(success=False, error="Invalid credentials")
        tenant = self._tenant_repo.get_default()
        return AuthResult(
            success=True,
            user_id=0,
            tenant_id=tenant.id if tenant else 1,
            username=username,
            role="admin",
        )
