"""Render roles into ``RoleEntry`` documents, shared by the snapshot and bundle."""

from osiki.decision.models import GrantEntry, RoleEntry
from osiki.models.role import Grant, Role

MISSING_CONDITION_PREFIX = "missing:"


def role_entry(
    role: Role, permissions: dict[str, str], condition_keys: dict[str, str]
) -> RoleEntry:
    return RoleEntry(
        id=str(role.id),
        name=role.name,
        parent_id=str(role.parent_role_id) if role.parent_role_id else None,
        grants=[
            GrantEntry(
                permission=permissions[str(g.permission_id)],
                condition=condition_key(g, condition_keys),
            )
            for g in role.grants
            if str(g.permission_id) in permissions
        ],
    )


def condition_key(grant: Grant, condition_keys: dict[str, str]) -> str | None:
    if grant.condition_id is None:
        return None
    condition_id = str(grant.condition_id)
    return condition_keys.get(condition_id, f"{MISSING_CONDITION_PREFIX}{condition_id}")
