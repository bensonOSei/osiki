import time

from beanie import PydanticObjectId
from loguru import logger

from osiki.models.user import User
from osiki.repositories.users.base_user_repository import BaseUserRepository


class MongoDBUserRepository(BaseUserRepository):
    def __init__(self, environment_id: str) -> None:
        self.environment_id = environment_id

    async def create(self, user: User) -> User:
        user.environment_id = self.environment_id
        await user.insert()
        logger.debug("User created", user_id=str(user.id), external_id=user.external_id)
        return user

    async def get_by_id(self, user_id: str) -> User | None:
        user = await User.find_one(
            {"_id": PydanticObjectId(user_id), "environment_id": self.environment_id}
        )
        if not user:
            logger.debug("User not found", user_id=user_id)
        return user

    async def get_by_external_id(self, external_id: str) -> User | None:
        user = await User.find_one(
            User.environment_id == self.environment_id, User.external_id == external_id
        )
        if not user:
            logger.debug("User not found by external_id", external_id=external_id)
        return user

    async def get_by_email(self, email: str) -> User | None:
        return await User.find_one(
            User.environment_id == self.environment_id, User.email == email
        )

    async def update(self, user: User) -> User:
        user.updated_at = time.time()
        await user.save()
        logger.debug("User updated", user_id=str(user.id))
        return user

    async def deactivate(self, user_id: str) -> bool:
        user = await self.get_by_id(user_id)
        if not user:
            logger.warning("Attempted to deactivate non-existent user", user_id=user_id)
            return False
        user.is_active = False
        user.updated_at = time.time()
        await user.save()
        logger.info("User deactivated", user_id=user_id)
        return True

    async def reactivate(self, user_id: str) -> bool:
        user = await self.get_by_id(user_id)
        if not user:
            logger.warning("Attempted to reactivate non-existent user", user_id=user_id)
            return False
        user.is_active = True
        user.updated_at = time.time()
        await user.save()
        logger.info("User reactivated", user_id=user_id)
        return True

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[User]:
        return (
            await User.find(
                User.environment_id == self.environment_id, User.is_active == True
            )
            .skip(skip)
            .limit(limit)
            .to_list()
        )
