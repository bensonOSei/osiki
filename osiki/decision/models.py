"""Pure decision inputs and outputs: the snapshot, the user bundle and results.

These models are shipped as JSON to the SDKs, so every field is JSON-native.
They are frozen and ignore unknown fields, so an older SDK keeps reading a
snapshot that a newer server extended.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .rules import FilterNode

type Via = Literal["direct", "group"]
type DenialReason = Literal[
    "no_permission", "not_tenant_member", "condition_failed", "record_required"
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class GrantEntry(_Frozen):
    """A role's grant: ``"res:act"`` plus an optional condition key."""

    permission: str
    condition: str | None = None


class RoleEntry(_Frozen):
    id: str
    name: str
    parent_id: str | None = None
    grants: list[GrantEntry] = Field(default_factory=list)


class ConstraintEntry(_Frozen):
    id: str
    name: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class Snapshot(_Frozen):
    """An environment's authorization config at one ``version``.

    ``conditions`` maps a condition key to its validated rule AST.
    """

    environment_id: str
    version: int
    roles: list[RoleEntry] = Field(default_factory=list)
    conditions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    constraints: list[ConstraintEntry] = Field(default_factory=list)


class AssignmentEntry(_Frozen):
    """A role held by the user, directly or through a group."""

    role_id: str
    scope: dict[str, str] = Field(default_factory=dict)
    expires_at: float | None = None
    via: Via


class UserBundle(_Frozen):
    """One user's id, attributes, tenant memberships and assignments.

    ``tenants`` maps each tenant external id the user belongs to onto that
    tenant's attributes; membership is key presence.
    """

    user_id: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    tenants: dict[str, dict[str, Any]] = Field(default_factory=dict)
    assignments: list[AssignmentEntry] = Field(default_factory=list)


class DecisionRequest(_Frozen):
    resource: str
    action: str
    scope: dict[str, str] = Field(default_factory=dict)
    record: dict[str, Any] | None = None
    now: float


class Decision(_Frozen):
    allowed: bool
    matched_permission: str | None = None
    matched_via: Via | None = None
    condition: str | None = None
    denial_reason: DenialReason | None = None


class EffectiveGrant(_Frozen):
    permission: str
    condition: str | None = None
    via: Via


class FilterResult(_Frozen):
    """``all`` / ``none`` carry no filter; ``filter`` carries a residual tree."""

    mode: Literal["all", "none", "filter"]
    filter: FilterNode | None = None
