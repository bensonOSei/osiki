from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession

from osiki.models.tenant_team_lock import TenantTeamLock
from osiki.repositories.tenant_team_locks.base_tenant_team_lock_repository import (
    BaseTenantTeamLockRepository,
)


class MongoDBTenantTeamLockRepository(BaseTenantTeamLockRepository):
    def __init__(self, environment_id: str) -> None:
        self.environment_id = environment_id

    def _key(self, tenant_id: str) -> dict[str, str]:
        return {"environment_id": self.environment_id, "tenant_id": tenant_id}

    async def ensure(self, tenant_id: str) -> None:
        await TenantTeamLock.get_pymongo_collection().update_one(
            self._key(tenant_id), {"$setOnInsert": {"version": 0}}, upsert=True
        )

    async def bump(
        self, tenant_id: str, *, session: AsyncClientSession | None = None
    ) -> int:
        doc = await TenantTeamLock.get_pymongo_collection().find_one_and_update(
            self._key(tenant_id),
            {"$inc": {"version": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        # upsert + ReturnDocument.AFTER always yields the document.
        assert doc is not None
        version: int = doc["version"]
        return version
