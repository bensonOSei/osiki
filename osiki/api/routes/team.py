"""The tenant team API: what a business owner's dashboard calls.

Every route first requires the actor to manage the tenant (403), and only then
checks the tenant exists (404). That order stops a tenant user from probing
which tenants exist.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from osiki.api.dependencies import (
    AuditLogRepository,
    TeamServiceDep,
    TenantMemberRepository,
    TenantRepository,
)
from osiki.api.exceptions import NotFoundError
from osiki.schemas.audit_log import AuditLogRead
from osiki.schemas.base import PaginatedResponse
from osiki.schemas.permission import PermissionRead
from osiki.schemas.team import (
    EffectiveSourceRead,
    GrantRefIn,
    TeamMemberAdd,
    TeamMemberRead,
    TeamRoleCreate,
    TeamRoleRead,
    TeamRoleUpdate,
    ValidateRequest,
    ValidateResponse,
    ViolationRead,
    service_args,
)
from osiki.services.team.models import GrantRef
from osiki.services.team.team_service import TeamService


async def managed_team(
    tenant_id: str, team: TeamServiceDep, tenant_repo: TenantRepository
) -> TeamService:
    await team.require_manager()
    if await tenant_repo.get_by_external_id(tenant_id) is None:
        raise NotFoundError("Tenant not found", details={"tenant_id": tenant_id})
    return team


Team = Annotated[TeamService, Depends(managed_team)]

router = APIRouter(prefix="/tenants/{tenant_id}/team", tags=["team"])


def _refs(grants: list[GrantRefIn] | None) -> list[GrantRef] | None:
    return None if grants is None else [g.to_ref() for g in grants]


# -- roles -------------------------------------------------------------------


@router.get("/roles")
async def list_roles(team: Team) -> list[TeamRoleRead]:
    return [TeamRoleRead.from_role(r) for r in await team.list_roles()]


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(data: TeamRoleCreate, team: Team) -> TeamRoleRead:
    role = await team.create_role(data.name, _refs(data.grants) or [], data.copied_from)
    return TeamRoleRead.from_role(role)


@router.patch("/roles/{role_id}")
async def update_role(role_id: str, data: TeamRoleUpdate, team: Team) -> TeamRoleRead:
    role = await team.update_role(role_id, data.name, _refs(data.grants))
    return TeamRoleRead.from_role(role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: str, team: Team) -> None:
    await team.delete_role(role_id)


# -- members -----------------------------------------------------------------


@router.get("/members")
async def list_members(
    tenant_id: str,
    team: Team,
    member_repo: TenantMemberRepository,
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[TeamMemberRead]:
    members = await team.list_members((page - 1) * page_size, page_size)
    items = [TeamMemberRead.from_member(m) for m in members]
    total = await member_repo.count(tenant_id)
    return PaginatedResponse.create(items, total, page, page_size)


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def add_member(data: TeamMemberAdd, team: Team) -> TeamMemberRead:
    member = await team.add_member(
        data.user_id, name=data.name, email=data.email, role_id=data.role_id
    )
    return TeamMemberRead.from_member(member)


@router.put("/members/{user_id}/roles/{role_id}")
async def assign_role(user_id: str, role_id: str, team: Team) -> TeamMemberRead:
    return TeamMemberRead.from_member(await team.assign_role(user_id, role_id))


@router.delete(
    "/members/{user_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_role(user_id: str, role_id: str, team: Team) -> None:
    await team.revoke_role(user_id, role_id)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: str, team: Team) -> None:
    await team.remove_member(user_id)


@router.get("/members/{user_id}/effective")
async def effective(user_id: str, team: Team) -> list[EffectiveSourceRead]:
    return [EffectiveSourceRead.from_source(s) for s in await team.effective(user_id)]


# -- dry run, editor data, audit ----------------------------------------------


@router.post("/validate")
async def validate(data: ValidateRequest, team: Team) -> ValidateResponse:
    """Report the rules the operation would break; writes nothing."""
    violations = await team.validate(data.op, **service_args(data.args))
    return ValidateResponse(
        violations=[ViolationRead.from_violation(v) for v in violations]
    )


@router.get("/permissions")
async def list_permissions(team: Team) -> list[PermissionRead]:
    return [
        PermissionRead.from_model(p) for p in await team.list_assignable_permissions()
    ]


@router.get("/audit-logs", dependencies=[Depends(managed_team)])
async def list_audit_logs(
    tenant_id: str,
    audit_repo: AuditLogRepository,
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[AuditLogRead]:
    logs = await audit_repo.list(tenant_id, (page - 1) * page_size, page_size)
    items = [AuditLogRead.from_model(log) for log in logs]
    return PaginatedResponse.create(
        items, await audit_repo.count(tenant_id), page, page_size
    )
