from abc import ABC, abstractmethod

from pymongo.asynchronous.client_session import AsyncClientSession


class BaseTenantTeamLockRepository(ABC):
    @abstractmethod
    async def ensure(self, tenant_id: str) -> None:
        """Create the tenant's lock document if missing; never changes it.

        Run outside a transaction, so two first writers in a fresh tenant
        conflict on the ``$inc`` of an existing document, not on its insert.
        """

    @abstractmethod
    async def bump(
        self, tenant_id: str, *, session: AsyncClientSession | None = None
    ) -> int:
        """Atomically increment the tenant's lock version; return the new value."""
