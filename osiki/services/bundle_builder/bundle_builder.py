"""Build one user's ``UserBundle``: attributes, tenants and assignments."""

from osiki.decision.models import AssignmentEntry, UserBundle, Via
from osiki.models.group_role import GroupRole
from osiki.models.user_role import UserRole
from osiki.repositories.group_roles.base_group_role_repository import (
    BaseGroupRoleRepository,
)
from osiki.repositories.tenant_members.base_tenant_member_repository import (
    BaseTenantMemberRepository,
)
from osiki.repositories.tenants.base_tenant_repository import BaseTenantRepository
from osiki.repositories.user_groups.base_user_group_repository import (
    BaseUserGroupRepository,
)
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)
from osiki.repositories.users.base_user_repository import BaseUserRepository


class BundleBuilder:
    """Assemble a user's bundle from the repositories, deny-safe.

    An unknown or inactive user has no bundle (``None``). ``tenants`` holds
    only memberships whose tenant document exists and is active, so a stale
    membership is no membership. Assignments are the user's active direct
    roles (``via="direct"``) followed by the active roles of the user's active
    group memberships (``via="group"``), each in repository order.
    """

    def __init__(
        self,
        user_repo: BaseUserRepository,
        user_role_repo: BaseUserRoleRepository,
        user_group_repo: BaseUserGroupRepository,
        group_role_repo: BaseGroupRoleRepository,
        tenant_member_repo: BaseTenantMemberRepository,
        tenant_repo: BaseTenantRepository,
    ) -> None:
        self._user_repo = user_repo
        self._user_role_repo = user_role_repo
        self._user_group_repo = user_group_repo
        self._group_role_repo = group_role_repo
        self._tenant_member_repo = tenant_member_repo
        self._tenant_repo = tenant_repo

    async def build(self, user_external_id: str) -> UserBundle | None:
        user = await self._user_repo.get_by_external_id(user_external_id)
        if user is None or not user.is_active:
            return None
        internal_id = str(user.id)

        direct = await self._user_role_repo.get_user_roles(internal_id)
        memberships = await self._user_group_repo.get_user_groups(internal_id)
        group_ids = [str(m.group_id) for m in memberships if m.is_active]
        via_group = (
            await self._group_role_repo.get_roles_for_groups(group_ids)
            if group_ids
            else []
        )

        tenant_ids = await self._tenant_member_repo.tenants_for_user(user_external_id)
        tenants = await self._tenant_repo.get_many(tenant_ids) if tenant_ids else []

        return UserBundle(
            user_id=user_external_id,
            attributes=dict(user.attributes),
            tenants={
                t.external_id: dict(t.attributes)
                for t in tenants
                if t.is_active and t.external_id in tenant_ids
            },
            assignments=[
                *_entries(direct, "direct"),
                *_entries(via_group, "group"),
            ],
        )


def _entries(
    assignments: list[UserRole] | list[GroupRole], via: Via
) -> list[AssignmentEntry]:
    return [
        AssignmentEntry(
            role_id=str(a.role_id),
            scope=a.scope.to_dict(),
            expires_at=a.expires_at,
            via=via,
        )
        for a in assignments
        if a.is_active
    ]
