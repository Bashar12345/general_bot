from abc import ABC, abstractmethod
from typing import Optional, TypeVar, Generic

T = TypeVar("T")


class Repository(ABC, Generic[T]):
    @abstractmethod
    def get_by_id(self, entity_id: int) -> Optional[T]:
        ...

    @abstractmethod
    def save(self, entity: T) -> T:
        ...
