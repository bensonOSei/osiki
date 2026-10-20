from abc import ABC, abstractmethod

from osiki.models.group_role import GroupRole


class BaseGroupRoleRepository(ABC):
    @abstractmethod
    async def create(self, group_role: GroupRole) -> GroupRole: ...

    @abstractmethod
    async def get_by_id(self, group_role_id: str) -> GroupRole | None: ...

    @abstractmethod
    async def get_group_roles(self, group_id: str) -> list[GroupRole]: ...

    @abstractmethod
    async def get_roles_for_groups(
        self, group_ids: list[str], *, now: float | None = None
    ) -> list[GroupRole]:
        """Active assignments unexpired at ``now`` (default: the current time)."""

    @abstractmethod
    async def get_groups_with_role(self, role_id: str) -> list[GroupRole]: ...

    @abstractmethod
    async def find_assignment(
        self, group_id: str, role_id: str, tenant_id: str | None = None
    ) -> GroupRole | None:
        """The active assignment scoped to ``tenant_id``.

        ``tenant_id=None`` matches only the project-wide assignment (no tenant),
        never a tenant-scoped one.
        """

    @abstractmethod
    async def revoke(self, group_role_id: str) -> bool: ...

    @abstractmethod
    async def get_expired(self, current_time: float) -> list[GroupRole]: ...
