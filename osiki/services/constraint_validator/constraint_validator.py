import time
from typing import NamedTuple

from beanie import PydanticObjectId
from loguru import logger
from pymongo.asynchronous.client_session import AsyncClientSession

from osiki.models.constraint import ConstraintType, ScopeLevel
from osiki.repositories.constraints.base_constraint_repository import (
    BaseConstraintRepository,
)
from osiki.repositories.group_roles.base_group_role_repository import (
    BaseGroupRoleRepository,
)
from osiki.repositories.groups.base_group_repository import BaseGroupRepository
from osiki.repositories.roles.base_role_repository import BaseRoleRepository
from osiki.repositories.user_groups.base_user_group_repository import (
    BaseUserGroupRepository,
)
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)
from osiki.services.constraint_validator.base_constraint_validator import (
    BaseConstraintValidator,
    ConstraintValidationResult,
)


class _Held(NamedTuple):
    role_id: PydanticObjectId  # canonical
    tenant_id: str | None
    active: bool  # the role document was found active


class ConstraintValidator(BaseConstraintValidator):
    def __init__(
        self,
        constraint_repository: BaseConstraintRepository,
        user_role_repository: BaseUserRoleRepository,
        role_repository: BaseRoleRepository,
        group_role_repository: BaseGroupRoleRepository,
        user_group_repository: BaseUserGroupRepository,
        group_repository: BaseGroupRepository,
    ) -> None:
        self._constraint_repo = constraint_repository
        self._user_role_repo = user_role_repository
        self._role_repo = role_repository
        self._group_role_repo = group_role_repository
        self._user_group_repo = user_group_repository
        self._group_repo = group_repository

    async def _canonical_ids(
        self, role_ids: set[PydanticObjectId]
    ) -> dict[str, tuple[str, bool]]:
        """Each role's (canonical id, found active) pair.

        The canonical id is the template for a tenant copy, else the role's own
        id. A role that is missing or inactive is not found active and keeps
        its own id: it still counts for mutual exclusion (deny-safe) but never
        satisfies a prerequisite. A deactivated template needs no lookup: its
        copies carry ``copied_from``.
        """
        roles = await self._role_repo.get_by_ids([str(rid) for rid in role_ids])
        canonical = {str(rid): (str(rid), False) for rid in role_ids}
        for role in roles:
            canonical[str(role.id)] = (
                str(role.copied_from if role.copied_from is not None else role.id),
                True,
            )
        return canonical

    async def _held(
        self, user_id: str, now: float, session: AsyncClientSession | None
    ) -> list[_Held]:
        """Every active, unexpired role the user holds, directly or through a
        group that is itself still active. A user with no assignments holds
        nothing."""
        assignments = [
            (ur.role_id, ur.scope.tenant_id)
            for ur in await self._user_role_repo.get_user_roles(
                user_id, session=session
            )
            if ur.is_active and (ur.expires_at is None or ur.expires_at > now)
        ]
        # Deleting a group only deactivates it: its members hold nothing then.
        member_of = [
            str(m.group_id)
            for m in await self._user_group_repo.get_user_groups(user_id)
            if m.is_active
        ]
        live = (
            {str(g.id) for g in await self._group_repo.get_by_ids(member_of)}
            if member_of
            else set()
        )
        group_ids = [gid for gid in member_of if gid in live]
        if group_ids:
            group_roles = await self._group_role_repo.get_roles_for_groups(
                group_ids, now=now
            )
            assignments.extend(
                (gr.role_id, gr.scope.tenant_id)
                for gr in group_roles
                if gr.is_active and (gr.expires_at is None or gr.expires_at > now)
            )
        if not assignments:
            return []
        canonical = await self._canonical_ids({rid for rid, _ in assignments})
        return [
            _Held(PydanticObjectId(canonical[str(rid)][0]), t, canonical[str(rid)][1])
            for rid, t in assignments
        ]

    async def validate(
        self,
        user_id: str,
        role_id: str,
        scope: dict[str, str],
        *,
        now: float | None = None,
        session: AsyncClientSession | None = None,
    ) -> ConstraintValidationResult:
        now = time.time() if now is None else now
        logger.debug(
            "Validating constraints for role assignment",
            user_id=user_id,
            role_id=role_id,
            scope=scope,
        )
        constraints = await self._constraint_repo.get_active()
        # Constraints name canonical ids, so a template's binds every copy.
        canonical_role = role_id
        if PydanticObjectId.is_valid(role_id):
            canonical = await self._canonical_ids({PydanticObjectId(role_id)})
            canonical_role = canonical[str(PydanticObjectId(role_id))][0]

        for constraint in constraints:
            if constraint.type == ConstraintType.MUTUAL_EXCLUSION:
                result = await self._check_mutual_exclusion(
                    user_id,
                    canonical_role,
                    scope,
                    constraint.config.role_ids or [],
                    now,
                    session,
                )
                if not result.valid:
                    logger.warning(
                        "Constraint violation: mutual exclusion",
                        constraint_name=constraint.name,
                        user_id=user_id,
                        role_id=role_id,
                    )
                    return ConstraintValidationResult(
                        valid=False,
                        constraint_name=constraint.name,
                        reason=result.reason,
                    )

            elif constraint.type == ConstraintType.CARDINALITY:
                if (
                    constraint.config.role_id
                    and str(constraint.config.role_id) == canonical_role
                ):
                    result = await self._check_cardinality(
                        canonical_role,
                        scope,
                        constraint.config.max_assignments or 0,
                        constraint.config.scope_level or ScopeLevel.GLOBAL,
                        now,
                        session,
                    )
                    if not result.valid:
                        logger.warning(
                            "Constraint violation: cardinality",
                            constraint_name=constraint.name,
                            role_id=role_id,
                            max_assignments=constraint.config.max_assignments,
                        )
                        return ConstraintValidationResult(
                            valid=False,
                            constraint_name=constraint.name,
                            reason=result.reason,
                        )

            elif constraint.type == ConstraintType.PREREQUISITE:
                if (
                    constraint.config.role_id
                    and str(constraint.config.role_id) == canonical_role
                ):
                    result = await self._check_prerequisite(
                        user_id,
                        scope,
                        constraint.config.requires_role_id,
                        now,
                        session,
                    )
                    if not result.valid:
                        logger.warning(
                            "Constraint violation: prerequisite",
                            constraint_name=constraint.name,
                            user_id=user_id,
                            role_id=role_id,
                            requires_role_id=str(constraint.config.requires_role_id),
                        )
                        return ConstraintValidationResult(
                            valid=False,
                            constraint_name=constraint.name,
                            reason=result.reason,
                        )

        logger.debug(
            "All constraints validated successfully",
            user_id=user_id,
            role_id=role_id,
        )
        return ConstraintValidationResult(valid=True)

    async def _check_mutual_exclusion(
        self,
        user_id: str,
        canonical_role: str,
        scope: dict[str, str],
        conflicting_role_ids: list[PydanticObjectId],
        now: float,
        session: AsyncClientSession | None,
    ) -> ConstraintValidationResult:
        role_oid = PydanticObjectId(canonical_role)
        if role_oid not in conflicting_role_ids:
            return ConstraintValidationResult(valid=True)

        # Two roles can apply together unless they are scoped to different
        # tenants, so only that case passes. A project-wide role applies in
        # every tenant, on either side (deny-safe).
        tenant_id = scope.get("tenant_id")
        user_role_ids = {
            held.role_id
            for held in await self._held(user_id, now, session)
            if tenant_id is None
            or held.tenant_id is None
            or held.tenant_id == tenant_id
        }

        for conflicting_id in conflicting_role_ids:
            if conflicting_id != role_oid and conflicting_id in user_role_ids:
                return ConstraintValidationResult(
                    valid=False,
                    reason="User already has a mutually exclusive role",
                )

        return ConstraintValidationResult(valid=True)

    async def _check_cardinality(
        self,
        role_id: str,
        scope: dict[str, str],
        max_assignments: int,
        scope_level: ScopeLevel,
        now: float,
        session: AsyncClientSession | None,
    ) -> ConstraintValidationResult:
        count = 0
        # The template's assignments and those of every tenant copy count.
        role_ids = [
            role_id,
            *(
                str(copy.id)
                for copy in await self._role_repo.list_copies(role_id, session=session)
            ),
        ]
        if scope_level == ScopeLevel.GLOBAL:
            count = await self._user_role_repo.count_active(
                role_ids, {}, now, session=session
            )
        elif scope_level == ScopeLevel.PER_TENANT:
            tenant_id = scope.get("tenant_id")
            if tenant_id:
                count = await self._user_role_repo.count_active(
                    role_ids, {"tenant_id": tenant_id}, now, session=session
                )
        else:
            count = await self._user_role_repo.count_active(
                role_ids, scope, now, exact=True, session=session
            )

        if count >= max_assignments:
            return ConstraintValidationResult(
                valid=False,
                reason=f"Maximum {max_assignments} assignments reached",
            )

        return ConstraintValidationResult(valid=True)

    async def _check_prerequisite(
        self,
        user_id: str,
        scope: dict[str, str],
        requires_role_id: PydanticObjectId | None,
        now: float,
        session: AsyncClientSession | None,
    ) -> ConstraintValidationResult:
        if not requires_role_id:
            return ConstraintValidationResult(valid=True)

        # The prerequisite must hold wherever the new role will apply: held
        # project-wide, or in the same tenant. A role held in another tenant
        # does not count, and a project-wide assignment needs a project-wide
        # prerequisite.
        tenant_id = scope.get("tenant_id")
        user_role_ids = {
            held.role_id
            for held in await self._held(user_id, now, session)
            if held.active and (held.tenant_id is None or held.tenant_id == tenant_id)
        }

        if requires_role_id not in user_role_ids:
            return ConstraintValidationResult(
                valid=False,
                reason="Prerequisite role not assigned",
            )

        return ConstraintValidationResult(valid=True)
