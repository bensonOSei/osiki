from loguru import logger

from osiki.repositories.group_roles.base_group_role_repository import (
    BaseGroupRoleRepository,
)
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository
from osiki.repositories.user_groups.base_user_group_repository import (
    BaseUserGroupRepository,
)
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)
from osiki.services.permission_resolver.base_permission_resolver import (
    BasePermissionResolver,
)
from osiki.services.scope_matcher.base_scope_matcher import BaseScopeMatcher


class PermissionResolver(BasePermissionResolver):
    def __init__(
        self,
        user_role_repository: BaseUserRoleRepository,
        user_group_repository: BaseUserGroupRepository,
        group_role_repository: BaseGroupRoleRepository,
        role_repository: BaseRoleRepository,
        permission_repository: BasePermissionRepository,
        scope_matcher: BaseScopeMatcher,
    ) -> None:
        self._user_role_repo = user_role_repository
        self._user_group_repo = user_group_repository
        self._group_role_repo = group_role_repository
        self._role_repo = role_repository
        self._permission_repo = permission_repository
        self._scope_matcher = scope_matcher

    async def get_effective_permissions(
        self, user_id: str, scope: dict[str, str] | None = None
    ) -> set[str]:
        logger.debug(
            "Resolving effective permissions",
            user_id=user_id,
            scope=scope,
        )
        permissions: set[str] = set()

        direct_assignments = await self._user_role_repo.get_user_roles(user_id)
        logger.trace(
            "Found direct role assignments",
            user_id=user_id,
            count=len(direct_assignments),
        )

        user_groups = await self._user_group_repo.get_user_groups(user_id)
        group_ids = [str(ug.group_id) for ug in user_groups]
        logger.trace(
            "Found user groups",
            user_id=user_id,
            group_count=len(group_ids),
        )

        group_assignments = []
        if group_ids:
            group_assignments = await self._group_role_repo.get_roles_for_groups(
                group_ids
            )
            logger.trace(
                "Found group role assignments",
                group_count=len(group_ids),
                assignment_count=len(group_assignments),
            )

        all_assignments = [
            *[(a.role_id, a.scope.to_dict()) for a in direct_assignments],
            *[(a.role_id, a.scope.to_dict()) for a in group_assignments],
        ]

        # Always filter: an empty request scope must not match tenant-scoped
        # assignments.
        all_assignments = [
            (role_id, user_scope)
            for role_id, user_scope in all_assignments
            if self._scope_matcher.matches(user_scope, scope or {})
        ]
        logger.trace(
            "Filtered assignments by scope",
            remaining_count=len(all_assignments),
        )

        for role_id, _ in all_assignments:
            ancestor_ids = await self.get_role_ancestors(str(role_id))
            roles = await self._role_repo.get_by_ids(ancestor_ids)

            for role in roles:
                if not role.is_active:
                    continue
                # Conditional grants grant nothing here: this resolver cannot
                # evaluate conditions, so granting them would widen access.
                perm_ids = [
                    str(g.permission_id) for g in role.grants if g.condition_id is None
                ]
                if perm_ids:
                    perms = await self._permission_repo.get_by_ids(perm_ids)
                    for perm in perms:
                        permissions.add(perm.permission_string)

        logger.debug(
            "Resolved effective permissions",
            user_id=user_id,
            permission_count=len(permissions),
        )
        return permissions

    async def get_role_ancestors(self, role_id: str) -> list[str]:
        ancestors: list[str] = []
        visited: set[str] = set()
        current_id: str | None = role_id

        while current_id:
            if current_id in visited:
                logger.error(
                    "Circular role hierarchy detected",
                    role_id=current_id,
                    visited=list(visited),
                )
                raise ValueError(f"Circular role hierarchy detected at {current_id}")

            visited.add(current_id)

            role = await self._role_repo.get_by_id(current_id)
            if not role:
                # Only add initial role if not found (backward compatibility)
                if not ancestors:
                    ancestors.append(current_id)
                break

            ancestors.append(current_id)
            current_id = str(role.parent_role_id) if role.parent_role_id else None

        logger.trace(
            "Resolved role ancestors",
            role_id=role_id,
            ancestor_count=len(ancestors),
        )
        return ancestors
