from abc import ABC, abstractmethod

from osiki.models.group import Group


class BaseGroupRepository(ABC):
    @abstractmethod
    async def create(self, group: Group) -> Group: ...

    @abstractmethod
    async def get_by_id(self, group_id: str) -> Group | None: ...

    @abstractmethod
    async def get_by_ids(self, group_ids: list[str]) -> list[Group]:
        """The ACTIVE groups among ``group_ids`` in this environment."""

    @abstractmethod
    async def get_by_name(self, name: str) -> Group | None: ...

    @abstractmethod
    async def update(self, group: Group) -> Group: ...

    @abstractmethod
    async def deactivate(self, group_id: str) -> bool: ...

    @abstractmethod
    async def reactivate(self, group_id: str) -> bool: ...

    @abstractmethod
    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Group]: ...
