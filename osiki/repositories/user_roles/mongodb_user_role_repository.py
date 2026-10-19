import time

from beanie import PydanticObjectId
from loguru import logger
from pymongo.asynchronous.client_session import AsyncClientSession

from osiki.models.user_role import UserRole
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)


class MongoDBUserRoleRepository(BaseUserRoleRepository):
    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        self.environment_id = environment_id
        self._state = state

    async def create(
        self, user_role: UserRole, *, session: AsyncClientSession | None = None
    ) -> UserRole:
        user_role.environment_id = self.environment_id
        await user_role.insert(session=session)
        await self._state.bump_assignments_version(session=session)
        logger.info(
            "Role assigned to user",
            user_role_id=str(user_role.id),
            user_id=str(user_role.user_id),
            role_id=str(user_role.role_id),
            scope=user_role.scope.to_dict(),
        )
        return user_role

    async def get_by_id(
        self, user_role_id: str, *, session: AsyncClientSession | None = None
    ) -> UserRole | None:
        return await UserRole.find_one(
            {
                "_id": PydanticObjectId(user_role_id),
                "environment_id": self.environment_id,
            },
            session=session,
        )

    async def get_user_roles(
        self, user_id: str, *, session: AsyncClientSession | None = None
    ) -> list[UserRole]:
        now = time.time()
        return await UserRole.find(
            UserRole.environment_id == self.environment_id,
            UserRole.user_id == PydanticObjectId(user_id),
            UserRole.is_active == True,
            {"$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]},
            session=session,
        ).to_list()

    async def get_users_with_role(self, role_id: str) -> list[UserRole]:
        return await UserRole.find(
            UserRole.environment_id == self.environment_id,
            UserRole.role_id == PydanticObjectId(role_id),
            UserRole.is_active == True,
        ).to_list()

    async def get_by_tenant(
        self,
        tenant_id: str,
        role_id: str | None = None,
        *,
        session: AsyncClientSession | None = None,
    ) -> list[UserRole]:
        query: dict[str, object] = {
            "scope.tenant_id": tenant_id,
            "is_active": True,
        }
        if role_id:
            query["role_id"] = PydanticObjectId(role_id)
        return await UserRole.find(
            UserRole.environment_id == self.environment_id, query, session=session
        ).to_list()

    async def find_assignment(
        self,
        user_id: str,
        role_id: str,
        tenant_id: str | None = None,
        *,
        session: AsyncClientSession | None = None,
    ) -> UserRole | None:
        query: dict[str, object] = {
            "user_id": PydanticObjectId(user_id),
            "role_id": PydanticObjectId(role_id),
            "is_active": True,
            # None matches only project-wide rows (tenant_id null or missing).
            "scope.tenant_id": tenant_id,
        }
        return await UserRole.find_one(
            UserRole.environment_id == self.environment_id, query, session=session
        )

    async def revoke(
        self, user_role_id: str, *, session: AsyncClientSession | None = None
    ) -> bool:
        user_role = await self.get_by_id(user_role_id, session=session)
        if not user_role:
            logger.warning(
                "Attempted to revoke non-existent user role assignment",
                user_role_id=user_role_id,
            )
            return False
        user_role.is_active = False
        user_role.updated_at = time.time()
        await user_role.save(session=session)
        await self._state.bump_assignments_version(session=session)
        logger.info(
            "Role revoked from user",
            user_role_id=user_role_id,
            user_id=str(user_role.user_id),
            role_id=str(user_role.role_id),
        )
        return True

    async def get_expired(self, current_time: float) -> list[UserRole]:
        return await UserRole.find(
            UserRole.environment_id == self.environment_id,
            {
                "is_active": True,
                "expires_at": {"$ne": None, "$lte": current_time},
            },
        ).to_list()
