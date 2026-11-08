"""Request and response bodies of the tenant team API.

Input names carry a ``max_length``; response names never do. A deleted tenant
role is stored as ``"<name> #deleted-<id>"``, longer than any name accepted, so
a response must not reuse an input schema.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from osiki.services.team.models import (
    EffectiveSource,
    GrantEntry,
    GrantRef,
    TeamCondition,
    TeamMember,
    TeamRole,
    TeamRoleRef,
    Violation,
    ViolationKind,
)

RoleName = Annotated[str, Field(min_length=1, max_length=120)]
RoleKind = Literal["template", "tenant", "project"]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- inputs ------------------------------------------------------------------


class GrantRefIn(_Input):
    permission_id: str
    condition_id: str | None = None

    def to_ref(self) -> GrantRef:
        return GrantRef(
            permission_id=self.permission_id, condition_id=self.condition_id
        )


class TeamRoleCreate(_Input):
    name: RoleName
    grants: list[GrantRefIn]
    copied_from: str | None = None


class TeamRoleUpdate(_Input):
    name: RoleName | None = None
    grants: list[GrantRefIn] | None = None
    # The ``updated_at`` the editor read; a different stored value is a 409.
    expected_updated_at: float | None = None


class TeamMemberAdd(_Input):
    user_id: str = Field(min_length=1)
    name: str | None = None
    email: str | None = None
    role_id: str


class TeamRoleReplace(_Input):
    from_role_id: str
    to_role_id: str


class CreateRoleArgs(TeamRoleCreate):
    pass


class UpdateRoleArgs(TeamRoleUpdate):
    role_id: str


class AssignRoleArgs(_Input):
    user_id: str
    role_id: str


class AddMemberArgs(TeamMemberAdd):
    pass


class RevokeRoleArgs(AssignRoleArgs):
    pass


class RemoveMemberArgs(_Input):
    user_id: str


class ReplaceRoleArgs(TeamRoleReplace):
    user_id: str


class _CreateRoleOp(_Input):
    op: Literal["create_role"]
    args: CreateRoleArgs


class _UpdateRoleOp(_Input):
    op: Literal["update_role"]
    args: UpdateRoleArgs


class _AssignRoleOp(_Input):
    op: Literal["assign_role"]
    args: AssignRoleArgs


class _AddMemberOp(_Input):
    op: Literal["add_member"]
    args: AddMemberArgs


class _RevokeRoleOp(_Input):
    op: Literal["revoke_role"]
    args: RevokeRoleArgs


class _RemoveMemberOp(_Input):
    op: Literal["remove_member"]
    args: RemoveMemberArgs


class _ReplaceRoleOp(_Input):
    op: Literal["replace_role"]
    args: ReplaceRoleArgs


ValidateRequest = Annotated[
    _CreateRoleOp
    | _UpdateRoleOp
    | _AssignRoleOp
    | _AddMemberOp
    | _RevokeRoleOp
    | _RemoveMemberOp
    | _ReplaceRoleOp,
    Field(discriminator="op"),
]


def service_args(args: _Input) -> dict[str, Any]:
    """The args as the service takes them: nested models stay models, and the
    grants become ``GrantRef``."""
    out: dict[str, Any] = {}
    for field in type(args).model_fields:
        value = getattr(args, field)
        if field == "grants" and value is not None:
            value = [grant.to_ref() for grant in value]
        out[field] = value
    return out


# -- responses ---------------------------------------------------------------


class GrantEntryRead(BaseModel):
    permission: str
    condition: str | None
    inherited_from: str | None = None

    @classmethod
    def from_entry(cls, entry: GrantEntry) -> "GrantEntryRead":
        return cls(
            permission=entry.permission,
            condition=entry.condition,
            inherited_from=entry.inherited_from,
        )


class TeamRoleRead(BaseModel):
    id: str
    name: str
    kind: RoleKind
    grants: list[GrantEntryRead]
    copied_from: str | None
    holders: int
    updated_at: float

    @classmethod
    def from_role(cls, role: TeamRole) -> "TeamRoleRead":
        return cls(
            id=role.id,
            name=role.name,
            kind=role.kind,
            grants=[GrantEntryRead.from_entry(g) for g in role.grants],
            copied_from=role.copied_from,
            holders=role.holders,
            updated_at=role.updated_at,
        )


class TeamRoleRefRead(BaseModel):
    id: str
    name: str
    kind: RoleKind

    @classmethod
    def from_ref(cls, ref: TeamRoleRef) -> "TeamRoleRefRead":
        return cls(id=ref.id, name=ref.name, kind=ref.kind)


class TeamMemberRead(BaseModel):
    user_id: str
    name: str | None
    email: str | None
    roles: list[TeamRoleRefRead]
    member_since: float | None = None

    @classmethod
    def from_member(cls, member: TeamMember) -> "TeamMemberRead":
        return cls(
            user_id=member.user_id,
            name=member.name,
            email=member.email,
            roles=[TeamRoleRefRead.from_ref(r) for r in member.roles],
            member_since=member.member_since,
        )


class TeamConditionRead(BaseModel):
    id: str
    key: str
    description: str | None

    @classmethod
    def from_condition(cls, condition: TeamCondition) -> "TeamConditionRead":
        return cls(**condition.model_dump())


class EffectiveSourceRead(BaseModel):
    permission: str
    condition: str | None
    role_id: str
    role_name: str
    via: Literal["direct", "group"]

    @classmethod
    def from_source(cls, source: EffectiveSource) -> "EffectiveSourceRead":
        return cls(**source.model_dump())


class ViolationRead(BaseModel):
    kind: ViolationKind
    message: str
    details: dict[str, str]

    @classmethod
    def from_violation(cls, violation: Violation) -> "ViolationRead":
        return cls(**violation.model_dump())


class ValidateResponse(BaseModel):
    violations: list[ViolationRead]
