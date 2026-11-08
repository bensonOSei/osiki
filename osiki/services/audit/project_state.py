"""Audit snapshots of project-level roles and permissions."""

from collections.abc import Mapping
from typing import Any

from osiki.models.permission import Permission
from osiki.models.role import Role


def role_audit_state(
    role: Role, permissions: Mapping[str, str], conditions: Mapping[str, str]
) -> dict[str, Any]:
    """A role as ``{name, is_template, grants}``.

    ``permissions`` maps permission id to its ``resource:action`` string and
    ``conditions`` maps condition id to its key; a conditional grant renders as
    ``"<permission>?<condition key>"``.
    """
    grants: list[str] = []
    for grant in role.grants:
        text = permissions[str(grant.permission_id)]
        if grant.condition_id is not None:
            text = f"{text}?{conditions[str(grant.condition_id)]}"
        grants.append(text)
    return {"name": role.name, "is_template": role.is_template, "grants": grants}


def permission_audit_state(p: Permission) -> dict[str, Any]:
    return {
        "permission": p.permission_string,
        "description": p.description,
        "assignable": p.assignable,
        "is_active": p.is_active,
    }
