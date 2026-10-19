from pymongo.asynchronous.client_session import AsyncClientSession

from osiki.models.tenant_member import TenantMember
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)
from osiki.repositories.tenant_members.base_tenant_member_repository import (
    BaseTenantMemberRepository,
)


class MongoDBTenantMemberRepository(BaseTenantMemberRepository):
    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        self.environment_id = environment_id
        self._state = state

    async def _find(
        self, tenant_id: str, user_id: str, session: AsyncClientSession | None
    ) -> TenantMember | None:
        return await TenantMember.find_one(
            TenantMember.environment_id == self.environment_id,
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id == user_id,
            session=session,
        )

    async def add(
        self, tenant_id: str, user_id: str, *, session: AsyncClientSession | None = None
    ) -> None:
        if await self._find(tenant_id, user_id, session) is not None:
            return
        await TenantMember(
            environment_id=self.environment_id, tenant_id=tenant_id, user_id=user_id
        ).insert(session=session)
        await self._state.bump_assignments_version(session=session)

    async def remove(
        self, tenant_id: str, user_id: str, *, session: AsyncClientSession | None = None
    ) -> bool:
        member = await self._find(tenant_id, user_id, session)
        if member is None:
            return False
        await member.delete(session=session)
        await self._state.bump_assignments_version(session=session)
        return True

    async def is_member(
        self, tenant_id: str, user_id: str, *, session: AsyncClientSession | None = None
    ) -> bool:
        return await self._find(tenant_id, user_id, session) is not None

    async def tenants_for_user(self, user_id: str) -> list[str]:
        rows = await TenantMember.find(
            TenantMember.environment_id == self.environment_id,
            TenantMember.user_id == user_id,
        ).to_list()
        return [row.tenant_id for row in rows]

    async def members(self, tenant_id: str, skip: int, limit: int) -> list[str]:
        rows = (
            await TenantMember.find(
                TenantMember.environment_id == self.environment_id,
                TenantMember.tenant_id == tenant_id,
            )
            .sort("+created_at", "+_id")
            .skip(skip)
            .limit(limit)
            .to_list()
        )
        return [row.user_id for row in rows]
