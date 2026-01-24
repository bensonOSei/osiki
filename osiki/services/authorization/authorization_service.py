from loguru import logger

from osiki.services.authorization.base_authorization_service import (
    AuthorizationResult,
    BaseAuthorizationService,
)
from osiki.services.permission_resolver.base_permission_resolver import (
    BasePermissionResolver,
)


class AuthorizationService(BaseAuthorizationService):
    def __init__(self, permission_resolver: BasePermissionResolver) -> None:
        self._permission_resolver = permission_resolver

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
        permissions = await self._permission_resolver.get_effective_permissions(
            user_id, scope
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

        logger.info(
            "Authorization denied",
            user_id=user_id,
            resource=resource,
            action=action,
            reason="no_permission",
        )
        return AuthorizationResult(
            allowed=False,
            denial_reason="no_permission",
        )
