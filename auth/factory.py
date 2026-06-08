from auth.authenticator import Authenticator, AuthResult
from auth.admin_auth import AdminAuthenticator
from auth.user_auth import UserAuthenticator


class AuthFactory:
    _admin_auth: AdminAuthenticator | None = None
    _user_auth: UserAuthenticator | None = None

    @classmethod
    def admin(cls) -> Authenticator:
        if cls._admin_auth is None:
            cls._admin_auth = AdminAuthenticator()
        return cls._admin_auth

    @classmethod
    def user(cls) -> Authenticator:
        if cls._user_auth is None:
            cls._user_auth = UserAuthenticator()
        return cls._user_auth

    @classmethod
    def authenticate_admin(cls, username: str, password: str) -> AuthResult:
        return cls.admin().authenticate(username, password)

    @classmethod
    def authenticate_user(cls, username: str, password: str) -> AuthResult:
        return cls.user().authenticate(username, password)