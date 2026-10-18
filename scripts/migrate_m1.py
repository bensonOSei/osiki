"""M1 data migration. Safe to run repeatedly.

Usage: poetry run python scripts/migrate_m1.py
Reads MONGODB_URL and MONGODB_DATABASE from the environment.
"""

import asyncio
import os

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

# Single-environment unique indexes replaced by (environment_id, ...) compounds.
LEGACY_INDEXES: dict[str, list[str]] = {
    "roles": ["name_1"],
    "groups": ["name_1"],
    "users": ["external_id_1", "email_1"],
    "permissions": ["resource_1_action_1"],
}


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
        return counts
    finally:
        await client.close()


def main() -> None:
    url = os.environ.get("MONGODB_URL", "mongodb://localhost:27017/osiki")
    database_name = os.environ.get("MONGODB_DATABASE", "osiki")
    asyncio.run(migrate(url, database_name))


if __name__ == "__main__":
    main()
