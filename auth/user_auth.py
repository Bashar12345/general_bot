from werkzeug.security import check_password_hash
from auth.authenticator import Authenticator, AuthResult
from repositories.user_repo import UserRepository


class UserAuthenticator(Authenticator):
    def __init__(self, user_repo: UserRepository | None = None):
        self._user_repo = user_repo or UserRepository()

    def authenticate(self, username: str, password: str) -> AuthResult:
        user = self._user_repo.get_by_username(username)
        if user is None or user.id is None:
            return AuthResult(success=False, error="Invalid credentials")
        if not check_password_hash(user.password_hash, password):
            return AuthResult(success=False, error="Invalid credentials")
        return AuthResult(
            success=True,
            user_id=user.id,
            tenant_id=user.tenant_id,
            username=user.username,
            role=user.role,
        )
