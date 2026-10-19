from typing import Annotated

from fastapi import APIRouter, Header, Response, status

from osiki.api.dependencies import EnvironmentStateRepository, SnapshotBuilderDep
from osiki.decision.models import Snapshot

router = APIRouter(prefix="/snapshot", tags=["snapshot"])

# The body depends on the X-Osiki-Environment header, and a snapshot is
# private configuration: shared caches must neither mix environments nor
# store it at all.
_CACHE_HEADERS = {"Vary": "X-Osiki-Environment", "Cache-Control": "private"}


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
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={"ETag": etag, **_CACHE_HEADERS},
        )
    response.headers["ETag"] = etag
    response.headers.update(_CACHE_HEADERS)
    return snapshot


@router.get("/version")
async def get_snapshot_version(state: EnvironmentStateRepository) -> dict[str, int]:
    return {"version": await state.get_config_version()}
