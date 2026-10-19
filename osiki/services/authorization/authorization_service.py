import time
from typing import Any

from loguru import logger

from osiki.decision.decide import decide, effective_grants, list_filter
from osiki.decision.models import DecisionRequest, EffectiveGrant, FilterResult
from osiki.services.authorization.base_authorization_service import (
    AuthorizationResult,
    BaseAuthorizationService,
)
from osiki.services.bundle_builder.bundle_builder import BundleBuilder
from osiki.services.snapshot_builder.snapshot_builder import SnapshotBuilder


class AuthorizationService(BaseAuthorizationService):
    """Every check goes through the pure ``decide`` over a snapshot and bundle."""

    def __init__(
        self, snapshot_builder: SnapshotBuilder, bundle_builder: BundleBuilder
    ) -> None:
        self._snapshot_builder = snapshot_builder
        self._bundle_builder = bundle_builder

    async def authorize(
        self,
        user_id: str,
        resource: str,
        action: str,
        scope: dict[str, str] | None = None,
        record: dict[str, Any] | None = None,
    ) -> AuthorizationResult:
        logger.debug(
            "Authorizing access",
            user_id=user_id,
            resource=resource,
            action=action,
            scope=scope,
        )
        bundle = await self._bundle_builder.build(user_id)
        if bundle is None:
            result = AuthorizationResult(allowed=False, denial_reason="unknown_user")
        else:
            snapshot = await self._snapshot_builder.build()
            decision = decide(
                snapshot,
                bundle,
                DecisionRequest(
                    resource=resource,
                    action=action,
                    scope=scope or {},
                    record=record,
                    now=time.time(),
                ),
            )
            result = AuthorizationResult(**decision.model_dump())
        logger.info(
            "Authorization granted" if result.allowed else "Authorization denied",
            user_id=user_id,
            resource=resource,
            action=action,
            matched_permission=result.matched_permission,
            condition=result.condition,
            reason=result.denial_reason,
        )
        return result

    async def effective_grants(
        self, user_id: str, scope: dict[str, str] | None = None
    ) -> list[EffectiveGrant] | None:
        bundle = await self._bundle_builder.build(user_id)
        if bundle is None:
            return None
        snapshot = await self._snapshot_builder.build()
        return effective_grants(snapshot, bundle, scope or {}, time.time())

    async def filter(
        self,
        user_id: str,
        resource: str,
        action: str,
        scope: dict[str, str] | None = None,
    ) -> FilterResult:
        bundle = await self._bundle_builder.build(user_id)
        if bundle is None:
            return FilterResult(mode="none")
        snapshot = await self._snapshot_builder.build()
        return list_filter(snapshot, bundle, resource, action, scope or {}, time.time())
