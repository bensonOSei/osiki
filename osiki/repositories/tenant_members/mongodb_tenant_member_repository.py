from osiki.models.tenant_member import TenantMember
from osiki.repositories.tenant_members.base_tenant_member_repository import (
    BaseTenantMemberRepository,
)


class MongoDBTenantMemberRepository(BaseTenantMemberRepository):
    def __init__(self, environment_id: str) -> None:
        self.environment_id = environment_id

    async def _find(self, tenant_id: str, user_id: str) -> TenantMember | None:
        return await TenantMember.find_one(
            TenantMember.environment_id == self.environment_id,
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id == user_id,
        )

    async def add(self, tenant_id: str, user_id: str) -> None:
        if await self._find(tenant_id, user_id) is not None:
            return
        await TenantMember(
            environment_id=self.environment_id, tenant_id=tenant_id, user_id=user_id
        ).insert()

    async def remove(self, tenant_id: str, user_id: str) -> bool:
        member = await self._find(tenant_id, user_id)
        if member is None:
            return False
        await member.delete()
        return True

    async def is_member(self, tenant_id: str, user_id: str) -> bool:
        return await self._find(tenant_id, user_id) is not None

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
