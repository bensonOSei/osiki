import time

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


class ConstraintValidator(BaseConstraintValidator):
    def __init__(
        self,
        constraint_repository: BaseConstraintRepository,
        user_role_repository: BaseUserRoleRepository,
        role_repository: BaseRoleRepository,
        group_role_repository: BaseGroupRoleRepository,
        user_group_repository: BaseUserGroupRepository,
    ) -> None:
        self._constraint_repo = constraint_repository
        self._user_role_repo = user_role_repository
        self._role_repo = role_repository
        self._group_role_repo = group_role_repository
        self._user_group_repo = user_group_repository

    async def _canonical_ids(self, role_ids: set[PydanticObjectId]) -> dict[str, str]:
        """Each role's canonical id: its template for a tenant copy, else itself.

        A role that is gone or inactive keeps its own id, so an assignment of it
        still counts (deny-safe). A deactivated template needs no lookup: the
        copy carries ``copied_from``.
        """
        roles = await self._role_repo.get_by_ids([str(rid) for rid in role_ids])
        canonical = {str(rid): str(rid) for rid in role_ids}
        for role in roles:
            if role.copied_from is not None:
                canonical[str(role.id)] = str(role.copied_from)
        return canonical

    async def _held(
        self, user_id: str, now: float, session: AsyncClientSession | None
    ) -> list[tuple[PydanticObjectId, str | None]]:
        """(canonical role id, tenant) of every active, unexpired role the user
        holds, directly or through a group. A user with no assignments holds
        nothing."""
        assignments = [
            (ur.role_id, ur.scope.tenant_id)
            for ur in await self._user_role_repo.get_user_roles(
                user_id, session=session
            )
            if ur.is_active and (ur.expires_at is None or ur.expires_at > now)
        ]
        memberships = await self._user_group_repo.get_user_groups(user_id)
        if memberships:
            group_roles = await self._group_role_repo.get_roles_for_groups(
                [str(m.group_id) for m in memberships]
            )
            assignments.extend(
                (gr.role_id, gr.scope.tenant_id)
                for gr in group_roles
                if gr.is_active and (gr.expires_at is None or gr.expires_at > now)
            )
        if not assignments:
            return []
        canonical = await self._canonical_ids({rid for rid, _ in assignments})
        return [(PydanticObjectId(canonical[str(rid)]), t) for rid, t in assignments]

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
            canonical_role = canonical[str(PydanticObjectId(role_id))]

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
            rid
            for rid, held_tenant in await self._held(user_id, now, session)
            if tenant_id is None or held_tenant is None or held_tenant == tenant_id
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
            rid
            for rid, held_tenant in await self._held(user_id, now, session)
            if held_tenant is None or held_tenant == tenant_id
        }

        if requires_role_id not in user_role_ids:
            return ConstraintValidationResult(
                valid=False,
                reason="Prerequisite role not assigned",
            )

        return ConstraintValidationResult(valid=True)
