from abc import ABC, abstractmethod

from pydantic import BaseModel


class AuthorizationResult(BaseModel):
    allowed: bool
    matched_permission: str | None = None
    matched_via: str | None = None
    denial_reason: str | None = None
    cache_hit: bool = False


class BaseAuthorizationService(ABC):
    @abstractmethod
    async def authorize(
        self,
        user_id: str,
        resource: str,
        action: str,
        scope: dict[str, str] | None = None,
    ) -> AuthorizationResult:
        """Decide whether a user may perform action on resource within scope.

        user_id is the user's EXTERNAL id. Denial reasons: "unknown_user",
        "not_tenant_member" (scope names a tenant the user isn't a member of)
        and "no_permission".
        """
