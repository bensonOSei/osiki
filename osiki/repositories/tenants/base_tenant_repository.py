from abc import ABC, abstractmethod

from osiki.models.base import AttributeValue
from osiki.models.tenant import Tenant


class BaseTenantRepository(ABC):
    @abstractmethod
    async def upsert(
        self, external_id: str, name: str, attributes: dict[str, AttributeValue]
    ) -> Tenant: ...

    @abstractmethod
    async def get_by_external_id(self, external_id: str) -> Tenant | None: ...

    @abstractmethod
    async def search(self, q: str | None, skip: int, limit: int) -> list[Tenant]:
        """Active tenants, oldest first; ``q`` is a case-insensitive prefix of
        the name or external id."""

    @abstractmethod
    async def count(self, q: str | None) -> int:
        """Tenants ``search`` ranges over."""

    @abstractmethod
    async def get_many(self, external_ids: list[str]) -> list[Tenant]: ...
