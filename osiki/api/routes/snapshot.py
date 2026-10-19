from typing import Annotated

from fastapi import APIRouter, Header, Response, status

from osiki.api.dependencies import EnvironmentStateRepository, SnapshotBuilderDep
from osiki.decision.models import Snapshot

router = APIRouter(prefix="/snapshot", tags=["snapshot"])


@router.get("", response_model=Snapshot)
async def get_snapshot(
    response: Response,
    snapshot_builder: SnapshotBuilderDep,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Snapshot | Response:
    snapshot = await snapshot_builder.build()
    etag = f'"{snapshot.version}"'
    if if_none_match == etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag}
        )
    response.headers["ETag"] = etag
    return snapshot


@router.get("/version")
async def get_snapshot_version(state: EnvironmentStateRepository) -> dict[str, int]:
    return {"version": await state.get_config_version()}
