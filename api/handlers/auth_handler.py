from typing import Optional
from api.dto import (
    LoginRequest, SignupRequest, AuthResponse,
    ChangePasswordRequest,
)
from api.interfaces import SessionProvider
from auth import AuthResult
from services.auth_service import AuthService


class AuthHandler:
    def __init__(self, session_provider: SessionProvider):
        self._auth_service = AuthService(session_provider)

    def login(self, req: LoginRequest) -> AuthResponse:
        if not req.username or not req.password:
            return AuthResponse(success=False, error="Username and password required")
        result = self._auth_service.login_user(req.username, req.password)
        if result.success:
            return AuthResponse(
                success=True, user_id=result.user_id,
                tenant_id=result.tenant_id, username=result.username,
                role=result.role, redirect_url="/",
            )
        return AuthResponse(success=False, error="Invalid credentials")

    def signup(self, req: SignupRequest) -> AuthResponse:
        result = self._auth_service.signup(req.business_name, req.email, req.password)
        if result.success:
            return AuthResponse(
                success=True, user_id=result.user_id,
                tenant_id=result.tenant_id, username=result.username,
                role=result.role, redirect_url="/",
            )
        return AuthResponse(success=False, error=result.error or "Signup failed")

    def logout(self) -> None:
        self._auth_service.logout_user()

    def change_password(self, req: ChangePasswordRequest) -> AuthResponse:
        if not req.current_password or not req.new_password:
            return AuthResponse(success=False, error="Both current and new password are required")
        ok, msg = self._auth_service.change_password(
            req.user_id, req.current_password, req.new_password
        )
        if ok:
            return AuthResponse(success=True, redirect_url="/")
        return AuthResponse(success=False, error=msg)

    def is_logged_in(self) -> bool:
        return self._auth_service.is_logged_in()
