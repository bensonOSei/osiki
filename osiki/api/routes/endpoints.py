import time

from fastapi import APIRouter, Query, status

from osiki.api.dependencies import EndpointRepository
from osiki.api.exceptions import NotFoundError
from osiki.decision.models import EndpointEntry
from osiki.schemas.endpoint import (
    DiscoveredEndpointsCreate,
    DiscoveredEndpointsRecorded,
    EndpointMappingWrite,
    EndpointStatusRead,
)

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


@router.post(
    "/discovered",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DiscoveredEndpointsRecorded,
)
async def record_discovered(
    body: DiscoveredEndpointsCreate, repo: EndpointRepository
) -> DiscoveredEndpointsRecorded:
    recorded = await repo.record_discovered(
        [(e.method, e.path) for e in body.endpoints], time.time()
    )
    return DiscoveredEndpointsRecorded(recorded=recorded)


@router.get("", response_model=list[EndpointStatusRead])
async def list_endpoints(repo: EndpointRepository) -> list[EndpointStatusRead]:
    rows: dict[tuple[str, str], EndpointStatusRead] = {}
    for found in await repo.list_discovered():
        rows[(found.method, found.path)] = EndpointStatusRead(
            method=found.method, path=found.path, last_seen=found.last_seen
        )
    for mapping in await repo.list_mappings():
        key = (mapping.method, mapping.path)
        row = rows.get(key) or EndpointStatusRead(
            method=mapping.method, path=mapping.path
        )
        row.mapping = mapping.to_entry()
        rows[key] = row
    return sorted(rows.values(), key=lambda r: (r.path, r.method))


@router.put("/mapping", response_model=EndpointEntry)
async def put_mapping(
    body: EndpointMappingWrite, repo: EndpointRepository
) -> EndpointEntry:
    mapping = await repo.upsert_mapping(EndpointEntry(**body.model_dump()))
    return mapping.to_entry()


@router.delete("/mapping", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(
    repo: EndpointRepository,
    method: str = Query(),
    path: str = Query(),
) -> None:
    if not await repo.delete_mapping(method, path):
        raise NotFoundError(f"No mapping for {method} {path}")
