from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from osiki.decision.models import EffectiveGrant


class AuthorizationResult(BaseModel):
    allowed: bool
    matched_permission: str | None = None
    matched_via: str | None = None
    condition: str | None = None
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
        record: dict[str, Any] | None = None,
    ) -> AuthorizationResult:
        """Decide whether a user may perform action on resource within scope.

        user_id is the user's EXTERNAL id. Denial reasons: "unknown_user" plus
        those of ``osiki.decision.decide`` ("not_tenant_member",
        "no_permission", "record_required", "condition_failed").
        """

    @abstractmethod
    async def effective_grants(
        self, user_id: str, scope: dict[str, str] | None = None
    ) -> list[EffectiveGrant] | None:
        """The grants the user (EXTERNAL id) holds in scope; None if unknown."""
