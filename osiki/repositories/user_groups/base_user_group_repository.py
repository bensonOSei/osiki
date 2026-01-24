from abc import ABC, abstractmethod

from osiki.models.user_group import UserGroup


class BaseUserGroupRepository(ABC):
    @abstractmethod
    async def create(self, user_group: UserGroup) -> UserGroup: ...

    @abstractmethod
    async def get_by_id(self, user_group_id: str) -> UserGroup | None: ...

    @abstractmethod
    async def get_user_groups(self, user_id: str) -> list[UserGroup]: ...

    @abstractmethod
    async def get_group_members(self, group_id: str) -> list[UserGroup]: ...

    @abstractmethod
    async def find_membership(
        self, user_id: str, group_id: str
    ) -> UserGroup | None: ...

    @abstractmethod
    async def remove(self, user_group_id: str) -> bool: ...
