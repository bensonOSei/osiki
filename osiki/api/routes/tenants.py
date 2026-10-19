from fastapi import APIRouter, Query, status

from osiki.api.dependencies import (
    TenantMemberRepository,
    TenantRepository,
    UserRepository,
)
from osiki.api.exceptions import NotFoundError
from osiki.models.tenant import Tenant
from osiki.schemas.base import PaginatedResponse
from osiki.schemas.tenant import TenantRead, TenantUpsert

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _to_read(tenant: Tenant) -> TenantRead:
    return TenantRead(
        external_id=tenant.external_id,
        name=tenant.name,
        attributes=tenant.attributes,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )


@router.put("/{external_id}")
async def upsert_tenant(
    external_id: str,
    data: TenantUpsert,
    tenant_repo: TenantRepository,
) -> TenantRead:
    tenant = await tenant_repo.upsert(external_id, data.name, data.attributes)
    return _to_read(tenant)


@router.get("/{external_id}")
async def get_tenant(
    external_id: str,
    tenant_repo: TenantRepository,
) -> TenantRead:
    tenant = await tenant_repo.get_by_external_id(external_id)
    if not tenant:
        raise NotFoundError("Tenant not found", details={"tenant_id": external_id})
    return _to_read(tenant)


@router.put("/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_tenant_member(
    tenant_id: str,
    user_id: str,
    tenant_repo: TenantRepository,
    user_repo: UserRepository,
    member_repo: TenantMemberRepository,
) -> None:
    if not await tenant_repo.get_by_external_id(tenant_id):
        raise NotFoundError("Tenant not found", details={"tenant_id": tenant_id})
    if not await user_repo.get_by_external_id(user_id):
        raise NotFoundError("User not found", details={"user_id": user_id})
    await member_repo.add(tenant_id, user_id)


@router.delete("/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tenant_member(
    tenant_id: str,
    user_id: str,
    member_repo: TenantMemberRepository,
) -> None:
    if not await member_repo.remove(tenant_id, user_id):
        raise NotFoundError(
            "Tenant membership not found",
            details={"tenant_id": tenant_id, "user_id": user_id},
        )


@router.get("/{tenant_id}/members")
async def list_tenant_members(
    tenant_id: str,
    member_repo: TenantMemberRepository,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[str]:
    skip = (page - 1) * page_size
    items = await member_repo.members(tenant_id, skip, page_size)
    total = len(items) + skip
    return PaginatedResponse.create(items, total, page, page_size)
