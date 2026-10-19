"""M1 data migration. Safe to run repeatedly.

Usage: poetry run python scripts/migrate_m1.py
Reads MONGODB_URL and MONGODB_DATABASE from the environment.
"""

import asyncio
import os

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

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

# Single-environment unique indexes replaced by (environment_id, ...) compounds.
LEGACY_INDEXES: dict[str, list[str]] = {
    "roles": ["name_1"],
    "groups": ["name_1"],
    "users": ["external_id_1", "email_1"],
    "permissions": ["resource_1_action_1"],
}


async def migrate_role_grants(database: AsyncDatabase[dict[str, object]]) -> int:
    """Convert role `permission_ids` into unconditional `grants`."""
    migrated = 0
    roles = database["roles"]
    query = {"permission_ids": {"$exists": True}, "grants": {"$exists": False}}
    async for role in roles.find(query):
        permission_ids = role["permission_ids"]
        assert isinstance(permission_ids, list)
        await roles.update_one(
            {"_id": role["_id"]},
            {
                "$set": {
                    "grants": [
                        {"permission_id": pid, "condition_id": None}
                        for pid in permission_ids
                    ]
                },
                "$unset": {"permission_ids": ""},
            },
        )
        migrated += 1
    print(f"roles: converted {migrated} roles to grants")
    return migrated


async def migrate(url: str, database_name: str) -> dict[str, int]:
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(url)
    try:
        database = client.get_database(database_name)
        counts: dict[str, int] = {}
        for name in COLLECTIONS:
            result = await database[name].update_many(
                {"environment_id": {"$exists": False}},
                {"$set": {"environment_id": DEFAULT_ENVIRONMENT}},
            )
            counts[name] = result.modified_count
            existing = {
                index["name"] async for index in await database[name].list_indexes()
            }
            for index_name in LEGACY_INDEXES.get(name, []):
                if index_name in existing:
                    await database[name].drop_index(index_name)
                    print(f"{name}: dropped index {index_name}")
            print(f"{name}: stamped {counts[name]} documents")
        counts["role_grants"] = await migrate_role_grants(database)
        return counts
    finally:
        await client.close()


def main() -> None:
    url = os.environ.get("MONGODB_URL", "mongodb://localhost:27017/osiki")
    database_name = os.environ.get("MONGODB_DATABASE", "osiki")
    asyncio.run(migrate(url, database_name))


if __name__ == "__main__":
    main()
