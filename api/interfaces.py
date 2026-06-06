from abc import ABC, abstractmethod
from typing import Optional, Any


class SessionProvider(ABC):
    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any: ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None: ...

    @abstractmethod
    def pop(self, key: str, default: Any = None) -> Any: ...

    @abstractmethod
    def get_tenant_id(self) -> Optional[int]: ...

    @abstractmethod
    def get_user_id(self) -> Optional[int]: ...

    @abstractmethod
    def is_logged_in(self) -> bool: ...

    @abstractmethod
    def is_admin_logged_in(self) -> bool: ...
