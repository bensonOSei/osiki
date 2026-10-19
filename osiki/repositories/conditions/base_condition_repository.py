from abc import ABC, abstractmethod

from osiki.models.condition import Condition


class BaseConditionRepository(ABC):
    @abstractmethod
    async def create(self, condition: Condition) -> Condition: ...

    @abstractmethod
    async def get_by_id(self, condition_id: str) -> Condition | None: ...

    @abstractmethod
    async def get_by_key(self, key: str) -> Condition | None: ...

    @abstractmethod
    async def get_by_ids(self, ids: list[str]) -> list[Condition]: ...

    @abstractmethod
    async def update(self, condition: Condition) -> Condition: ...

    @abstractmethod
    async def deactivate(self, condition_id: str) -> bool: ...

    @abstractmethod
    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Condition]: ...
