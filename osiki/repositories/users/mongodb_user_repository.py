import time

from beanie import PydanticObjectId
from loguru import logger
from pymongo.asynchronous.client_session import AsyncClientSession

from osiki.models.base import AttributeValue, attributes_equal
from osiki.models.user import User
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)
from osiki.repositories.users.base_user_repository import BaseUserRepository


class MongoDBUserRepository(BaseUserRepository):
    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        self.environment_id = environment_id
        self._state = state

    async def create(
        self, user: User, *, session: AsyncClientSession | None = None
    ) -> User:
        user.environment_id = self.environment_id
        await user.insert(session=session)
        await self._state.bump_assignments_version(session=session)
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

    async def update(
        self, user: User, *, session: AsyncClientSession | None = None
    ) -> User:
        user.updated_at = time.time()
        await user.save(session=session)
        await self._state.bump_assignments_version(session=session)
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
        await self._state.bump_assignments_version()
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
        await self._state.bump_assignments_version()
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

    async def upsert_by_external_id(
        self,
        external_id: str,
        name: str | None,
        email: str | None,
        attributes: dict[str, AttributeValue] | None,
        *,
        session: AsyncClientSession | None = None,
    ) -> User:
        user = await User.find_one(
            User.environment_id == self.environment_id,
            User.external_id == external_id,
            session=session,
        )
        if user is None:
            user = User(
                external_id=external_id,
                name=name,
                email=email,
                attributes=attributes or {},
            )
            return await self.create(user, session=session)
        changed = False
        if name is not None and name != user.name:
            user.name, changed = name, True
        if email is not None and email != user.email:
            user.email, changed = email, True
        if attributes is not None and not attributes_equal(attributes, user.attributes):
            user.attributes, changed = attributes, True
        if not changed:
            # A no-op sync must not bump the version: that flushes every
            # SDK's bundle cache.
            return user
        return await self.update(user, session=session)
