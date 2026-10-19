"""M1 data migration. Safe to run repeatedly.

Usage: poetry run python scripts/migrate_m1.py
Reads MONGODB_URL and MONGODB_DATABASE from the environment.

Stop every instance of the old version before running it, and run it before
the new version takes traffic: old and new versions must never run side by
side against the same database.

``migrate_database`` works on any async database handle (pymongo's
``AsyncDatabase`` or mongomock-motor's), so the tests run it directly.
"""

import asyncio
import os
from typing import Any

from pymongo import AsyncMongoClient

DEFAULT_ENVIRONMENT = "default"

COLLECTIONS = [
    "users",
    "groups",
    "roles",
    "permissions",
    "user_roles",
    "user_groups",
    "group_roles",
    "constraints",
    "audit_logs",
    "access_logs",
]

# Indexes the current models no longer define, by the names MongoDB gave them.
# Beanie never drops indexes on its own, so without this they would linger:
# the unique ones would keep rejecting writes the new model allows.
#   * Pre-M1 base schema: single-environment indexes (no environment_id).
#   * M1 (A1): the assignment unique indexes that included is_active, which
#     made a second revoke of the same assignment fail. They are replaced by
#     unique indexes that only cover active rows.
# The TTL indexes (timestamp_1) on the log collections are unchanged and kept.
LEGACY_INDEXES: dict[str, list[str]] = {
    "users": ["external_id_1", "email_1", "is_active_1_created_at_-1"],
    "groups": ["name_1", "is_active_1_created_at_-1"],
    "roles": [
        "name_1",
        "parent_role_id_1",
        "permission_ids_1",
        "is_active_1_created_at_-1",
    ],
    "permissions": ["resource_1_action_1", "resource_1", "is_active_1"],
    "user_roles": [
        "user_id_1_role_id_1_scope.tenant_id_1_is_active_1",
        "user_id_1_is_active_1",
        "role_id_1_is_active_1",
        "scope.tenant_id_1_role_id_1_is_active_1",
        "expires_at_1",
        "environment_id_1_user_id_1_role_id_1_scope.tenant_id_1_is_active_1",
    ],
    "group_roles": [
        "group_id_1_role_id_1_scope.tenant_id_1_is_active_1",
        "group_id_1_is_active_1",
        "role_id_1_is_active_1",
        "environment_id_1_group_id_1_role_id_1_scope.tenant_id_1_is_active_1",
    ],
    "user_groups": [
        "user_id_1_group_id_1_is_active_1",
        "user_id_1_is_active_1",
        "group_id_1_is_active_1",
        "environment_id_1_user_id_1_group_id_1_is_active_1",
    ],
    "constraints": [
        "type_1_is_active_1",
        "config.role_ids_1",
        "config.role_id_1",
        "config.requires_role_id_1",
    ],
    "audit_logs": [
        "timestamp_-1",
        "actor_id_1_timestamp_-1",
        "target_type_1_target_id_1_timestamp_-1",
        "action_1_timestamp_-1",
    ],
    "access_logs": [
        "timestamp_-1",
        "user_id_1_timestamp_-1",
        "allowed_1_timestamp_-1",
        "resource_1_action_1_timestamp_-1",
    ],
}


def merge_grants(
    grants: list[dict[str, Any]] | None, permission_ids: list[Any] | None
) -> list[dict[str, Any]]:
    """Existing grants plus an unconditional grant per legacy permission id.

    A permission id already held by an unconditional grant is not repeated. A
    conditional grant for the same permission does not count: the legacy id
    granted it unconditionally, and dropping that would lose access.
    """
    merged = list(grants or [])
    unconditional = {
        g["permission_id"] for g in merged if g.get("condition_id") is None
    }
    for permission_id in permission_ids or []:
        if permission_id not in unconditional:
            merged.append({"permission_id": permission_id, "condition_id": None})
            unconditional.add(permission_id)
    return merged


async def migrate_role_grants(database: Any) -> int:
    """Fold every role's legacy ``permission_ids`` into ``grants``."""
    migrated = 0
    roles = database["roles"]
    async for role in roles.find({"permission_ids": {"$exists": True}}):
        await roles.update_one(
            {"_id": role["_id"]},
            {
                "$set": {
                    "grants": merge_grants(role.get("grants"), role["permission_ids"])
                },
                "$unset": {"permission_ids": ""},
            },
        )
        migrated += 1
    print(f"roles: converted {migrated} roles to grants")
    return migrated


async def drop_legacy_indexes(database: Any, name: str) -> None:
    existing = await database[name].index_information()
    for index_name in LEGACY_INDEXES.get(name, []):
        if index_name in existing:
            await database[name].drop_index(index_name)
            print(f"{name}: dropped index {index_name}")


async def migrate_database(database: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in COLLECTIONS:
        result = await database[name].update_many(
            {"environment_id": {"$exists": False}},
            {"$set": {"environment_id": DEFAULT_ENVIRONMENT}},
        )
        counts[name] = result.modified_count
        await drop_legacy_indexes(database, name)
        print(f"{name}: stamped {counts[name]} documents")
    counts["role_grants"] = await migrate_role_grants(database)
    return counts


async def migrate(url: str, database_name: str) -> dict[str, int]:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(url)
    try:
        return await migrate_database(client.get_database(database_name))
    finally:
        await client.close()


def main() -> None:
    url = os.environ.get("MONGODB_URL", "mongodb://localhost:27017/osiki")
    database_name = os.environ.get("MONGODB_DATABASE", "osiki")
    asyncio.run(migrate(url, database_name))


if __name__ == "__main__":
    main()
