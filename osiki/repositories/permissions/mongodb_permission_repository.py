from beanie import PydanticObjectId
from loguru import logger

from osiki.models.permission import Permission
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)


class MongoDBPermissionRepository(BasePermissionRepository):
    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        self.environment_id = environment_id
        self._state = state

    async def create(self, permission: Permission) -> Permission:
        permission.environment_id = self.environment_id
        await permission.insert()
        await self._state.bump_config_version()
        logger.debug(
            "Permission created",
            permission_id=str(permission.id),
            resource=permission.resource,
            action=permission.action,
        )
        return permission

    async def get_by_id(self, permission_id: str) -> Permission | None:
        permission = await Permission.find_one(
            {
                "_id": PydanticObjectId(permission_id),
                "environment_id": self.environment_id,
            }
        )
        if not permission:
            logger.debug("Permission not found", permission_id=permission_id)
        return permission

    async def get_by_ids(self, permission_ids: list[str]) -> list[Permission]:
        object_ids = [PydanticObjectId(pid) for pid in permission_ids]
        return await Permission.find(
            Permission.environment_id == self.environment_id,
            {"_id": {"$in": object_ids}, "is_active": True},
        ).to_list()

    async def get_by_resource_action(
        self, resource: str, action: str
    ) -> Permission | None:
        return await Permission.find_one(
            Permission.environment_id == self.environment_id,
            Permission.resource == resource,
            Permission.action == action,
            Permission.is_active == True,
        )

    async def get_by_resource(self, resource: str) -> list[Permission]:
        return await Permission.find(
            Permission.environment_id == self.environment_id,
            Permission.resource == resource,
            Permission.is_active == True,
        ).to_list()

    async def deactivate(self, permission_id: str) -> bool:
        permission = await self.get_by_id(permission_id)
        if not permission:
            logger.warning(
                "Attempted to deactivate non-existent permission",
                permission_id=permission_id,
            )
            return False
        permission.is_active = False
        await permission.save()
        await self._state.bump_config_version()
        logger.info("Permission deactivated", permission_id=permission_id)
        return True

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Permission]:
        return (
            await Permission.find(
                Permission.environment_id == self.environment_id,
                Permission.is_active == True,
            )
            .skip(skip)
            .limit(limit)
            .to_list()
        )
