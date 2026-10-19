from fastapi import APIRouter

from osiki.api.dependencies import EnvironmentStateRepository
from osiki.decision.models import EnvironmentSettings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=EnvironmentSettings)
async def get_settings(state: EnvironmentStateRepository) -> EnvironmentSettings:
    return await state.get_settings()


@router.put("", response_model=EnvironmentSettings)
async def put_settings(
    body: EnvironmentSettings, state: EnvironmentStateRepository
) -> EnvironmentSettings:
    return await state.update_settings(body)
