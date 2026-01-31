from abc import ABC, abstractmethod

from osiki.models.constraint import Constraint, ConstraintType


class BaseConstraintRepository(ABC):
    @abstractmethod
    async def create(self, constraint: Constraint) -> Constraint: ...

    @abstractmethod
    async def get_by_id(self, constraint_id: str) -> Constraint | None: ...

    @abstractmethod
    async def get_active(self) -> list[Constraint]: ...

    @abstractmethod
    async def get_by_type(
        self, constraint_type: ConstraintType
    ) -> list[Constraint]: ...

    @abstractmethod
    async def get_by_role_id(self, role_id: str) -> list[Constraint]: ...

    @abstractmethod
    async def update(self, constraint: Constraint) -> Constraint: ...

    @abstractmethod
    async def deactivate(self, constraint_id: str) -> bool: ...
