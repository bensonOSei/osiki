from fastapi import APIRouter

from osiki.api.dependencies import AuthorizationServiceDep
from osiki.schemas.authorization import AuthorizationRequest, AuthorizationResponse

router = APIRouter(prefix="/authorization", tags=["authorization"])


@router.post("/check")
async def check_authorization(
    request: AuthorizationRequest,
    auth_service: AuthorizationServiceDep,
) -> AuthorizationResponse:
    scope = request.scope.to_dict() if request.scope else None
    result = await auth_service.authorize(
        user_id=request.user_id,
        resource=request.resource,
        action=request.action,
        scope=scope,
    )
    return AuthorizationResponse(
        allowed=result.allowed,
        matched_permission=result.matched_permission,
        matched_via=result.matched_via,
        denial_reason=result.denial_reason,
        cache_hit=result.cache_hit,
    )
