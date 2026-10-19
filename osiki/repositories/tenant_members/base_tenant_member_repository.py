from abc import ABC, abstractmethod


class BaseTenantMemberRepository(ABC):
    @abstractmethod
    async def add(self, tenant_id: str, user_id: str) -> None: ...

    @abstractmethod
    async def remove(self, tenant_id: str, user_id: str) -> bool: ...

    @abstractmethod
    async def is_member(self, tenant_id: str, user_id: str) -> bool: ...

    @abstractmethod
    async def tenants_for_user(self, user_id: str) -> list[str]: ...

    @abstractmethod
    async def members(self, tenant_id: str, skip: int, limit: int) -> list[str]: ...
