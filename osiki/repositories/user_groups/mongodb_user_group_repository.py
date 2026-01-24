import time

from beanie import PydanticObjectId
from loguru import logger

from osiki.models.user_group import UserGroup
from osiki.repositories.user_groups.base_user_group_repository import (
    BaseUserGroupRepository,
)


class MongoDBUserGroupRepository(BaseUserGroupRepository):
    async def create(self, user_group: UserGroup) -> UserGroup:
        await user_group.insert()
        logger.info(
            "User added to group",
            user_group_id=str(user_group.id),
            user_id=str(user_group.user_id),
            group_id=str(user_group.group_id),
        )
        return user_group

    async def get_by_id(self, user_group_id: str) -> UserGroup | None:
        return await UserGroup.get(PydanticObjectId(user_group_id))

    async def get_user_groups(self, user_id: str) -> list[UserGroup]:
        return await UserGroup.find(
            UserGroup.user_id == PydanticObjectId(user_id),
            UserGroup.is_active == True,
        ).to_list()

    async def get_group_members(self, group_id: str) -> list[UserGroup]:
        return await UserGroup.find(
            UserGroup.group_id == PydanticObjectId(group_id),
            UserGroup.is_active == True,
        ).to_list()

    async def find_membership(self, user_id: str, group_id: str) -> UserGroup | None:
        return await UserGroup.find_one(
            UserGroup.user_id == PydanticObjectId(user_id),
            UserGroup.group_id == PydanticObjectId(group_id),
            UserGroup.is_active == True,
        )

    async def remove(self, user_group_id: str) -> bool:
        user_group = await self.get_by_id(user_group_id)
        if not user_group:
            logger.warning(
                "Attempted to remove non-existent group membership",
                user_group_id=user_group_id,
            )
            return False
        user_group.is_active = False
        user_group.updated_at = time.time()
        await user_group.save()
        logger.info(
            "User removed from group",
            user_group_id=user_group_id,
            user_id=str(user_group.user_id),
            group_id=str(user_group.group_id),
        )
        return True
