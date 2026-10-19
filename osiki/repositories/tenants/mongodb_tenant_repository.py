import time

from beanie.operators import In
from loguru import logger

from osiki.models.base import AttributeValue
from osiki.models.tenant import Tenant
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)
from osiki.repositories.tenants.base_tenant_repository import BaseTenantRepository


class MongoDBTenantRepository(BaseTenantRepository):
    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        self.environment_id = environment_id
        self._state = state

    async def upsert(
        self, external_id: str, name: str, attributes: dict[str, AttributeValue]
    ) -> Tenant:
        tenant = await Tenant.find_one(
            Tenant.environment_id == self.environment_id,
            Tenant.external_id == external_id,
        )
        if tenant is None:
            tenant = Tenant(
                environment_id=self.environment_id,
                external_id=external_id,
                name=name,
                attributes=attributes,
            )
            await tenant.insert()
            await self._state.bump_assignments_version()
            logger.debug("Tenant created", external_id=external_id)
            return tenant
        tenant.name = name
        tenant.attributes = attributes
        tenant.updated_at = time.time()
        await tenant.save()
        await self._state.bump_assignments_version()
        logger.debug("Tenant updated", external_id=external_id)
        return tenant

    async def get_by_external_id(self, external_id: str) -> Tenant | None:
        return await Tenant.find_one(
            Tenant.environment_id == self.environment_id,
            Tenant.external_id == external_id,
            Tenant.is_active == True,
        )

    async def get_many(self, external_ids: list[str]) -> list[Tenant]:
        return await Tenant.find(
            Tenant.environment_id == self.environment_id,
            In(Tenant.external_id, external_ids),
            Tenant.is_active == True,
        ).to_list()
