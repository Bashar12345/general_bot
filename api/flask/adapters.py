from typing import Any, Optional
from flask import session as flask_session
from api.interfaces import SessionProvider


class FlaskSessionProvider(SessionProvider):
    def get(self, key: str, default: Any = None) -> Any:
        return flask_session.get(key, default)

    def set(self, key: str, value: Any) -> None:
        flask_session[key] = value

    def pop(self, key: str, default: Any = None) -> Any:
        return flask_session.pop(key, default)

    def get_tenant_id(self) -> Optional[int]:
        return flask_session.get("tenant_id")

    def get_user_id(self) -> Optional[int]:
        return flask_session.get("user_id")

    def is_logged_in(self) -> bool:
        return flask_session.get("user_id") is not None

    def is_admin_logged_in(self) -> bool:
        return flask_session.get("admin") is not None or flask_session.get("user_role") == "tenant"
