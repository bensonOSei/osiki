import time

from beanie import PydanticObjectId
from loguru import logger

from osiki.models.group import Group
from osiki.repositories.groups.base_group_repository import BaseGroupRepository


class MongoDBGroupRepository(BaseGroupRepository):
    async def create(self, group: Group) -> Group:
        await group.insert()
        logger.debug("Group created", group_id=str(group.id), name=group.name)
        return group

    async def get_by_id(self, group_id: str) -> Group | None:
        group = await Group.get(PydanticObjectId(group_id))
        if not group:
            logger.debug("Group not found", group_id=group_id)
        return group

    async def get_by_name(self, name: str) -> Group | None:
        return await Group.find_one(Group.name == name)

    async def update(self, group: Group) -> Group:
        group.updated_at = time.time()
        await group.save()
        logger.debug("Group updated", group_id=str(group.id))
        return group

    async def deactivate(self, group_id: str) -> bool:
        group = await self.get_by_id(group_id)
        if not group:
            logger.warning(
                "Attempted to deactivate non-existent group", group_id=group_id
            )
            return False
        group.is_active = False
        group.updated_at = time.time()
        await group.save()
        logger.info("Group deactivated", group_id=group_id)
        return True

    async def reactivate(self, group_id: str) -> bool:
        group = await self.get_by_id(group_id)
        if not group:
            logger.warning(
                "Attempted to reactivate non-existent group", group_id=group_id
            )
            return False
        group.is_active = True
        group.updated_at = time.time()
        await group.save()
        logger.info("Group reactivated", group_id=group_id)
        return True

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Group]:
        return (
            await Group.find(Group.is_active == True).skip(skip).limit(limit).to_list()
        )
