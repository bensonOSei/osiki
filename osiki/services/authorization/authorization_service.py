from loguru import logger

from osiki.repositories.tenant_members.base_tenant_member_repository import (
    BaseTenantMemberRepository,
)
from osiki.repositories.users.base_user_repository import BaseUserRepository
from osiki.services.authorization.base_authorization_service import (
    AuthorizationResult,
    BaseAuthorizationService,
)
from osiki.services.permission_resolver.base_permission_resolver import (
    BasePermissionResolver,
)


class AuthorizationService(BaseAuthorizationService):
    def __init__(
        self,
        permission_resolver: BasePermissionResolver,
        user_repository: BaseUserRepository,
        tenant_member_repository: BaseTenantMemberRepository,
    ) -> None:
        self._permission_resolver = permission_resolver
        self._user_repo = user_repository
        self._tenant_member_repo = tenant_member_repository

    def _deny(
        self, user_id: str, resource: str, action: str, reason: str
    ) -> AuthorizationResult:
        logger.info(
            "Authorization denied",
            user_id=user_id,
            resource=resource,
            action=action,
            reason=reason,
        )
        return AuthorizationResult(allowed=False, denial_reason=reason)

    async def authorize(
        self,
        user_id: str,
        resource: str,
        action: str,
        scope: dict[str, str] | None = None,
    ) -> AuthorizationResult:
        logger.debug(
            "Authorizing access",
            user_id=user_id,
            resource=resource,
            action=action,
            scope=scope,
        )
        user = await self._user_repo.get_by_external_id(user_id)
        if user is None or not user.is_active:
            return self._deny(user_id, resource, action, "unknown_user")

        if scope and "tenant_id" in scope:
            if not await self._tenant_member_repo.is_member(
                scope["tenant_id"], user_id
            ):
                return self._deny(user_id, resource, action, "not_tenant_member")

        permissions = await self._permission_resolver.get_effective_permissions(
            str(user.id), scope
        )

        required_permission = f"{resource}:{action}"
        if required_permission in permissions:
            logger.info(
                "Authorization granted",
                user_id=user_id,
                resource=resource,
                action=action,
                matched_permission=required_permission,
            )
            return AuthorizationResult(
                allowed=True,
                matched_permission=required_permission,
            )

        wildcards = [
            f"{resource}:*",
            f"*:{action}",
            "*:*",
        ]

        for wildcard in wildcards:
            if wildcard in permissions:
                logger.info(
                    "Authorization granted via wildcard",
                    user_id=user_id,
                    resource=resource,
                    action=action,
                    matched_permission=wildcard,
                )
                return AuthorizationResult(
                    allowed=True,
                    matched_permission=wildcard,
                )

        return self._deny(user_id, resource, action, "no_permission")
