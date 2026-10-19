from fastapi import APIRouter

from osiki.api.dependencies import AuthorizationServiceDep
from osiki.decision.models import FilterResult
from osiki.schemas.authorization import (
    AuthorizationRequest,
    AuthorizationResponse,
    FilterRequest,
)

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
        record=request.record,
    )
    return AuthorizationResponse.model_validate(result)


@router.post("/filter")
async def filter_records(
    request: FilterRequest,
    auth_service: AuthorizationServiceDep,
) -> FilterResult:
    scope = request.scope.to_dict() if request.scope else None
    return await auth_service.filter(
        user_id=request.user_id,
        resource=request.resource,
        action=request.action,
        scope=scope,
    )
