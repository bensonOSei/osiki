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
    ) -> AuthorizationResult: ...
