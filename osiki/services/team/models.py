"""Team-manager value objects and the errors that map to HTTP."""

# The error names are the plan's public contract; they carry no Error suffix.
# ruff: noqa: N818

from typing import Literal

from pydantic import BaseModel, ConfigDict

from osiki.api.exceptions import AuthorizationError, ConflictError, OsikiError
from osiki.decision.models import GrantEntry


class GrantRef(BaseModel):
    """A grant by id: a permission, optionally narrowed by a condition."""

    model_config = ConfigDict(frozen=True)

    permission_id: str
    condition_id: str | None = None


class TeamRole(BaseModel):
    """A role as a tenant's team manager sees it."""

    id: str
    name: str
    kind: Literal["template", "tenant"]
    grants: list[GrantEntry]
    copied_from: str | None = None
    holders: int = 0


class TeamError(OsikiError):
    """A refusal by the team manager; subclasses pick the HTTP status."""


class NotManager(TeamError, AuthorizationError):
    """403: the actor may not manage this tenant's team."""

    def __init__(self) -> None:
        super().__init__(
            "Not allowed to manage this team", details={"reason": "not_manager"}
        )


class _TeamConflictError(TeamError, ConflictError):
    """409 with a machine-readable ``details["reason"]``."""


def _render(entries: list[GrantEntry]) -> str:
    return ", ".join(
        e.permission if e.condition is None else f"{e.permission}@{e.condition}"
        for e in entries
    )


class EscalationRefused(_TeamConflictError):
    def __init__(self, uncovered: list[GrantEntry]) -> None:
        self.uncovered = uncovered
        super().__init__(
            "Cannot grant permissions you do not hold",
            details={"reason": "escalation", "uncovered": _render(uncovered)},
        )


class NotAssignable(_TeamConflictError):
    def __init__(self, permissions: list[str]) -> None:
        self.permissions = permissions
        super().__init__(
            "Permissions cannot be given to tenant roles",
            details={"reason": "not_assignable", "permissions": ", ".join(permissions)},
        )


class NotOffered(_TeamConflictError):
    def __init__(self, role_id: str) -> None:
        super().__init__(
            "Role template is not offered",
            details={"reason": "not_offered", "role_id": role_id},
        )


class RoleInUse(_TeamConflictError):
    def __init__(self, role_id: str) -> None:
        super().__init__(
            "Role is still assigned",
            details={"reason": "role_in_use", "role_id": role_id},
        )


class LastManager(_TeamConflictError):
    def __init__(self) -> None:
        super().__init__(
            "A tenant must keep at least one team manager",
            details={"reason": "last_manager"},
        )
