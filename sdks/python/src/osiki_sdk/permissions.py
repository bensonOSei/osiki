"""Declare an app's permissions in code."""

from dataclasses import dataclass

from osiki_sdk.client import EngineError


@dataclass(frozen=True)
class PermissionSpec:
    """One permission an app needs. ``None`` fields are left as they are."""

    resource: str
    action: str
    description: str | None = None
    assignable: bool | None = None

    @property
    def key(self) -> str:
        return f"{self.resource}:{self.action}"


@dataclass
class EnsureResult:
    """Permission strings (``resource:action``), each list sorted."""

    created: list[str]
    updated: list[str]
    unchanged: list[str]


def is_deleted_conflict(exc: EngineError) -> bool:
    """Whether a create 409 says the key belongs to a deleted permission."""
    body = exc.body
    details = body.get("details") if isinstance(body, dict) else None
    return (
        exc.status == 409
        and isinstance(details, dict)
        and details.get("reason") == "deleted"
    )


class PermissionDeleted(EngineError):  # noqa: N818
    """The permission was deleted earlier, so the engine will not recreate it."""

    def __init__(self, permission: str, status: int = 409, body: object = None) -> None:
        super().__init__(status, body)
        self.permission = permission
        self.args = (
            f"permission {permission!r} was deleted and cannot be recreated "
            "by ensure()",
        )
