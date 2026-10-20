import time

from beanie import PydanticObjectId
from loguru import logger

from osiki.models.group_role import GroupRole
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)
from osiki.repositories.group_roles.base_group_role_repository import (
    BaseGroupRoleRepository,
)


class MongoDBGroupRoleRepository(BaseGroupRoleRepository):
    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        self.environment_id = environment_id
        self._state = state

    async def create(self, group_role: GroupRole) -> GroupRole:
        group_role.environment_id = self.environment_id
        await group_role.insert()
        await self._state.bump_assignments_version()
        logger.info(
            "Role assigned to group",
            group_role_id=str(group_role.id),
            group_id=str(group_role.group_id),
            role_id=str(group_role.role_id),
            scope=group_role.scope.to_dict(),
        )
        return group_role

    async def get_by_id(self, group_role_id: str) -> GroupRole | None:
        return await GroupRole.find_one(
            {
                "_id": PydanticObjectId(group_role_id),
                "environment_id": self.environment_id,
            }
        )

    async def get_group_roles(self, group_id: str) -> list[GroupRole]:
        now = time.time()
        return await GroupRole.find(
            GroupRole.environment_id == self.environment_id,
            GroupRole.group_id == PydanticObjectId(group_id),
            GroupRole.is_active == True,
            {"$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]},
        ).to_list()

    async def get_roles_for_groups(
        self, group_ids: list[str], *, now: float | None = None
    ) -> list[GroupRole]:
        now = time.time() if now is None else now
        object_ids = [PydanticObjectId(gid) for gid in group_ids]
        return await GroupRole.find(
            GroupRole.environment_id == self.environment_id,
            {"group_id": {"$in": object_ids}},
            GroupRole.is_active == True,
            {"$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]},
        ).to_list()

    async def get_groups_with_role(self, role_id: str) -> list[GroupRole]:
        return await GroupRole.find(
            GroupRole.environment_id == self.environment_id,
            GroupRole.role_id == PydanticObjectId(role_id),
            GroupRole.is_active == True,
        ).to_list()

    async def find_assignment(
        self, group_id: str, role_id: str, tenant_id: str | None = None
    ) -> GroupRole | None:
        query: dict[str, object] = {
            "group_id": PydanticObjectId(group_id),
            "role_id": PydanticObjectId(role_id),
            "is_active": True,
            # None matches only project-wide rows (tenant_id null or missing).
            "scope.tenant_id": tenant_id,
        }
        return await GroupRole.find_one(
            GroupRole.environment_id == self.environment_id, query
        )

    async def revoke(self, group_role_id: str) -> bool:
        group_role = await self.get_by_id(group_role_id)
        if not group_role:
            logger.warning(
                "Attempted to revoke non-existent group role assignment",
                group_role_id=group_role_id,
            )
            return False
        group_role.is_active = False
        group_role.updated_at = time.time()
        await group_role.save()
        await self._state.bump_assignments_version()
        logger.info(
            "Role revoked from group",
            group_role_id=group_role_id,
            group_id=str(group_role.group_id),
            role_id=str(group_role.role_id),
        )
        return True

    async def get_expired(self, current_time: float) -> list[GroupRole]:
        return await GroupRole.find(
            GroupRole.environment_id == self.environment_id,
            {
                "is_active": True,
                "expires_at": {"$ne": None, "$lte": current_time},
            },
        ).to_list()
