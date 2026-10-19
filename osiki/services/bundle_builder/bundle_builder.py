"""Build one user's ``UserBundle``: attributes, tenants, assignments, roles."""

from osiki.decision.models import AssignmentEntry, RoleEntry, UserBundle, Via
from osiki.models.group_role import GroupRole
from osiki.models.user_role import UserRole
from osiki.repositories.conditions.base_condition_repository import (
    BaseConditionRepository,
)
from osiki.repositories.group_roles.base_group_role_repository import (
    BaseGroupRoleRepository,
)
from osiki.repositories.groups.base_group_repository import BaseGroupRepository
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository
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
from osiki.services.snapshot_builder.render import role_entry


class BundleBuilder:
    """Assemble a user's bundle from the repositories, deny-safe.

    An unknown or inactive user has no bundle (``None``). ``tenants`` holds
    only memberships whose tenant document exists and is active, so a stale
    membership is no membership. Assignments are the user's active direct
    roles (``via="direct"``) followed by the active roles of the user's active
    memberships in groups that exist and are active (``via="group"``), each in
    repository order. A deactivated group grants nothing. ``roles`` carries the
    active tenant-owned roles those assignments reference, rendered like the
    snapshot's roles; tenant roles never enter the shared snapshot.
    """

    def __init__(
        self,
        user_repo: BaseUserRepository,
        user_role_repo: BaseUserRoleRepository,
        user_group_repo: BaseUserGroupRepository,
        group_repo: BaseGroupRepository,
        group_role_repo: BaseGroupRoleRepository,
        tenant_member_repo: BaseTenantMemberRepository,
        tenant_repo: BaseTenantRepository,
        role_repo: BaseRoleRepository,
        permission_repo: BasePermissionRepository,
        condition_repo: BaseConditionRepository,
    ) -> None:
        self._user_repo = user_repo
        self._user_role_repo = user_role_repo
        self._user_group_repo = user_group_repo
        self._group_repo = group_repo
        self._group_role_repo = group_role_repo
        self._tenant_member_repo = tenant_member_repo
        self._tenant_repo = tenant_repo
        self._role_repo = role_repo
        self._permission_repo = permission_repo
        self._condition_repo = condition_repo

    async def build(self, user_external_id: str) -> UserBundle | None:
        user = await self._user_repo.get_by_external_id(user_external_id)
        if user is None or not user.is_active:
            return None
        internal_id = str(user.id)

        direct = await self._user_role_repo.get_user_roles(internal_id)
        memberships = await self._user_group_repo.get_user_groups(internal_id)
        member_of = [str(m.group_id) for m in memberships if m.is_active]
        live = (
            {str(g.id) for g in await self._group_repo.get_by_ids(member_of)}
            if member_of
            else set()
        )
        group_ids = [gid for gid in member_of if gid in live]
        via_group = (
            await self._group_role_repo.get_roles_for_groups(group_ids)
            if group_ids
            else []
        )

        tenant_ids = await self._tenant_member_repo.tenants_for_user(user_external_id)
        tenants = await self._tenant_repo.get_many(tenant_ids) if tenant_ids else []

        assignments = [
            *_entries(direct, "direct"),
            *_entries(via_group, "group"),
        ]

        return UserBundle(
            user_id=user_external_id,
            attributes=dict(user.attributes),
            tenants={
                t.external_id: dict(t.attributes)
                for t in tenants
                if t.is_active and t.external_id in tenant_ids
            },
            assignments=assignments,
            roles=await self._tenant_roles(assignments),
        )

    async def _tenant_roles(
        self, assignments: list[AssignmentEntry]
    ) -> list[RoleEntry]:
        # ``get_by_ids`` returns active roles only.
        role_ids = list(dict.fromkeys(a.role_id for a in assignments))
        roles = (
            [
                r
                for r in await self._role_repo.get_by_ids(role_ids)
                if r.tenant_id is not None
            ]
            if role_ids
            else []
        )
        if not roles:
            return []
        permission_ids = list(
            dict.fromkeys(str(g.permission_id) for r in roles for g in r.grants)
        )
        permissions = {
            str(p.id): p.permission_string
            for p in await self._permission_repo.get_by_ids(permission_ids)
            if p.is_active
        }
        condition_keys = {
            str(c.id): c.key for c in await self._condition_repo.get_all()
        }
        return [role_entry(r, permissions, condition_keys) for r in roles]


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
