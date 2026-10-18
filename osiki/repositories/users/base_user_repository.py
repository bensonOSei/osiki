from abc import ABC, abstractmethod

from osiki.models.base import AttributeValue
from osiki.models.user import User


class BaseUserRepository(ABC):
    @abstractmethod
    async def create(self, user: User) -> User: ...

    @abstractmethod
    async def get_by_id(self, user_id: str) -> User | None: ...

    @abstractmethod
    async def get_by_external_id(self, external_id: str) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def update(self, user: User) -> User: ...

    @abstractmethod
    async def deactivate(self, user_id: str) -> bool: ...

    @abstractmethod
    async def reactivate(self, user_id: str) -> bool: ...

    @abstractmethod
    async def list_active(self, skip: int = 0, limit: int = 100) -> list[User]: ...

    @abstractmethod
    async def upsert_by_external_id(
        self,
        external_id: str,
        name: str | None,
        email: str | None,
        attributes: dict[str, AttributeValue] | None,
    ) -> User: ...
