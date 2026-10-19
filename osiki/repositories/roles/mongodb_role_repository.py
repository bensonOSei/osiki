import time

from beanie import PydanticObjectId
from loguru import logger

from osiki.models.role import Grant, Role
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository


class MongoDBRoleRepository(BaseRoleRepository):
    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        self.environment_id = environment_id
        self._state = state

    async def create(self, role: Role) -> Role:
        role.environment_id = self.environment_id
        await role.insert()
        await self._state.bump_config_version()
        logger.debug("Role created", role_id=str(role.id), name=role.name)
        return role

    async def get_by_id(self, role_id: str) -> Role | None:
        role = await Role.find_one(
            {"_id": PydanticObjectId(role_id), "environment_id": self.environment_id}
        )
        if not role:
            logger.debug("Role not found", role_id=role_id)
        return role

    async def get_by_name(self, name: str) -> Role | None:
        return await Role.find_one(
            Role.environment_id == self.environment_id,
            Role.name == name,
            Role.is_active == True,
        )

    async def get_by_ids(self, role_ids: list[str]) -> list[Role]:
        object_ids = [PydanticObjectId(rid) for rid in role_ids]
        return await Role.find(
            Role.environment_id == self.environment_id,
            {"_id": {"$in": object_ids}, "is_active": True},
        ).to_list()

    async def get_all_active(self) -> list[Role]:
        return await Role.find(
            Role.environment_id == self.environment_id, Role.is_active == True
        ).to_list()

    async def get_children(self, parent_role_id: str) -> list[Role]:
        return await Role.find(
            Role.environment_id == self.environment_id,
            Role.parent_role_id == PydanticObjectId(parent_role_id),
            Role.is_active == True,
        ).to_list()

    async def update(self, role: Role) -> Role:
        role.updated_at = time.time()
        await role.save()
        await self._state.bump_config_version()
        logger.debug("Role updated", role_id=str(role.id))
        return role

    async def deactivate(self, role_id: str) -> bool:
        role = await self.get_by_id(role_id)
        if not role:
            logger.warning("Attempted to deactivate non-existent role", role_id=role_id)
            return False
        if role.is_system:
            logger.warning("Attempted to deactivate system role", role_id=role_id)
            return False
        role.is_active = False
        role.updated_at = time.time()
        await role.save()
        await self._state.bump_config_version()
        logger.info("Role deactivated", role_id=role_id)
        return True

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Role]:
        return (
            await Role.find(
                Role.environment_id == self.environment_id, Role.is_active == True
            )
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def add_permission(
        self, role_id: str, permission_id: str, condition_id: str | None = None
    ) -> bool:
        role = await self.get_by_id(role_id)
        if not role:
            logger.warning(
                "Attempted to add permission to non-existent role", role_id=role_id
            )
            return False
        grant = _grant(permission_id, condition_id)
        if grant not in role.grants:
            role.grants.append(grant)
            role.updated_at = time.time()
            await role.save()
            logger.info(
                "Permission added to role",
                role_id=role_id,
                permission_id=permission_id,
                condition_id=condition_id,
            )
        # Bump even on a no-op: over-bumping costs one rebuild, never staleness.
        await self._state.bump_config_version()
        return True

    async def remove_permission(
        self, role_id: str, permission_id: str, condition_id: str | None = None
    ) -> bool:
        role = await self.get_by_id(role_id)
        if not role:
            logger.warning(
                "Attempted to remove permission from non-existent role", role_id=role_id
            )
            return False
        grant = _grant(permission_id, condition_id)
        if grant in role.grants:
            role.grants.remove(grant)
            role.updated_at = time.time()
            await role.save()
            logger.info(
                "Permission removed from role",
                role_id=role_id,
                permission_id=permission_id,
                condition_id=condition_id,
            )
        await self._state.bump_config_version()
        return True

    async def is_condition_in_use(self, condition_id: str) -> bool:
        role = await Role.find_one(
            Role.environment_id == self.environment_id,
            {
                "is_active": True,
                "grants.condition_id": PydanticObjectId(condition_id),
            },
        )
        return role is not None


def _grant(permission_id: str, condition_id: str | None) -> Grant:
    return Grant(
        permission_id=PydanticObjectId(permission_id),
        condition_id=PydanticObjectId(condition_id) if condition_id else None,
    )
