from abc import ABC, abstractmethod


class BasePermissionResolver(ABC):
    @abstractmethod
    async def get_effective_permissions(
        self, user_id: str, scope: dict[str, str] | None = None
    ) -> set[str]: ...

    @abstractmethod
    async def get_role_ancestors(self, role_id: str) -> list[str]: ...
