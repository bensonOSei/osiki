from beanie import PydanticObjectId
from loguru import logger

from osiki.models.constraint import ConstraintType, ScopeLevel
from osiki.repositories.constraints.base_constraint_repository import (
    BaseConstraintRepository,
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
    ) -> None:
        self._constraint_repo = constraint_repository
        self._user_role_repo = user_role_repository

    async def validate(
        self, user_id: str, role_id: str, scope: dict[str, str]
    ) -> ConstraintValidationResult:
        logger.debug(
            "Validating constraints for role assignment",
            user_id=user_id,
            role_id=role_id,
            scope=scope,
        )
        constraints = await self._constraint_repo.get_active()

        for constraint in constraints:
            if constraint.type == ConstraintType.MUTUAL_EXCLUSION:
                result = await self._check_mutual_exclusion(
                    user_id, role_id, scope, constraint.config.role_ids or []
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
                    and str(constraint.config.role_id) == role_id
                ):
                    result = await self._check_cardinality(
                        role_id,
                        scope,
                        constraint.config.max_assignments or 0,
                        constraint.config.scope_level or ScopeLevel.GLOBAL,
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
                    and str(constraint.config.role_id) == role_id
                ):
                    result = await self._check_prerequisite(
                        user_id, scope, constraint.config.requires_role_id
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
        role_id: str,
        scope: dict[str, str],
        conflicting_role_ids: list[PydanticObjectId],
    ) -> ConstraintValidationResult:
        role_oid = PydanticObjectId(role_id)
        if role_oid not in conflicting_role_ids:
            return ConstraintValidationResult(valid=True)

        # Two roles can apply together unless they are scoped to different
        # tenants, so only that case passes. A project-wide role applies in
        # every tenant, on either side (deny-safe).
        tenant_id = scope.get("tenant_id")
        user_role_ids = {
            ur.role_id
            for ur in await self._user_role_repo.get_user_roles(user_id)
            if tenant_id is None
            or ur.scope.tenant_id is None
            or ur.scope.tenant_id == tenant_id
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
    ) -> ConstraintValidationResult:
        if scope_level == ScopeLevel.GLOBAL:
            assignments = await self._user_role_repo.get_users_with_role(role_id)
            count = len(assignments)
        elif scope_level == ScopeLevel.PER_TENANT:
            tenant_id = scope.get("tenant_id")
            if tenant_id:
                assignments = await self._user_role_repo.get_by_tenant(
                    tenant_id, role_id
                )
                count = len(assignments)
            else:
                count = 0
        else:
            count = 0

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
    ) -> ConstraintValidationResult:
        if not requires_role_id:
            return ConstraintValidationResult(valid=True)

        # The prerequisite must hold wherever the new role will apply: held
        # project-wide, or in the same tenant. A role held in another tenant
        # does not count, and a project-wide assignment needs a project-wide
        # prerequisite.
        tenant_id = scope.get("tenant_id")
        user_role_ids = {
            ur.role_id
            for ur in await self._user_role_repo.get_user_roles(user_id)
            if ur.scope.tenant_id is None or ur.scope.tenant_id == tenant_id
        }

        if requires_role_id not in user_role_ids:
            return ConstraintValidationResult(
                valid=False,
                reason="Prerequisite role not assigned",
            )

        return ConstraintValidationResult(valid=True)
