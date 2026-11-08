from abc import ABC, abstractmethod

from pymongo.asynchronous.client_session import AsyncClientSession

from osiki.models.role import Role


class BaseRoleRepository(ABC):
    @abstractmethod
    async def create(
        self, role: Role, *, session: AsyncClientSession | None = None
    ) -> Role: ...

    @abstractmethod
    async def get_by_id(
        self, role_id: str, *, session: AsyncClientSession | None = None
    ) -> Role | None: ...

    @abstractmethod
    async def get_by_name(
        self,
        name: str,
        tenant_id: str | None = None,
        *,
        session: AsyncClientSession | None = None,
    ) -> Role | None:
        """The active role named ``name`` among a tenant's roles, or among the
        project roles when ``tenant_id`` is None."""

    @abstractmethod
    async def name_in_use(self, name: str, tenant_id: str | None = None) -> bool:
        """Whether any role, active or deleted, holds ``name`` among a tenant's
        roles (project roles when ``tenant_id`` is None). The unique name index
        covers deleted roles too."""

    @abstractmethod
    async def list_tenant(
        self, tenant_id: str, *, session: AsyncClientSession | None = None
    ) -> list[Role]:
        """Every active role owned by the tenant."""

    @abstractmethod
    async def list_templates(
        self, *, session: AsyncClientSession | None = None
    ) -> list[Role]:
        """Every active project role flagged ``is_template``."""

    @abstractmethod
    async def list_copies(
        self, template_id: str, *, session: AsyncClientSession | None = None
    ) -> list[Role]:
        """Every tenant copy of the template, deactivated copies included."""

    @abstractmethod
    async def get_by_ids(self, role_ids: list[str]) -> list[Role]: ...

    @abstractmethod
    async def copies_of(self, role_ids: list[str]) -> dict[str, int]:
        """Active tenant roles copied from each role. Roles without any are absent."""

    @abstractmethod
    async def project_role_ids(self, role_ids: list[str]) -> set[str]:
        """The ids that name a project role (tenant-owned roles excluded),
        deleted or not."""

    @abstractmethod
    async def get_all_active(self) -> list[Role]:
        """Every active role in the environment, unpaginated."""

    @abstractmethod
    async def get_children(self, parent_role_id: str) -> list[Role]: ...

    @abstractmethod
    async def update(
        self, role: Role, *, session: AsyncClientSession | None = None
    ) -> Role: ...

    @abstractmethod
    async def update_if_unchanged(
        self,
        role: Role,
        expected_updated_at: float,
        *,
        session: AsyncClientSession | None = None,
    ) -> bool:
        """Save ``role`` only while the stored ``updated_at`` still equals
        ``expected_updated_at``; False (nothing written) once another write
        has moved it. Bumps the environment state as ``update`` does."""

    @abstractmethod
    async def deactivate(
        self, role_id: str, *, session: AsyncClientSession | None = None
    ) -> bool: ...

    @abstractmethod
    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Role]:
        """Active project roles (tenant-owned roles are excluded)."""

    @abstractmethod
    async def count_active_project(self) -> int:
        """How many active project roles exist (tenant-owned roles excluded)."""

    @abstractmethod
    async def add_permission(
        self, role_id: str, permission_id: str, condition_id: str | None = None
    ) -> bool: ...

    @abstractmethod
    async def remove_permission(
        self, role_id: str, permission_id: str, condition_id: str | None = None
    ) -> bool: ...

    @abstractmethod
    async def is_condition_in_use(self, condition_id: str) -> bool: ...
