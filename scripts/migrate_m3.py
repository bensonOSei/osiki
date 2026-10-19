"""M3 data migration. Safe to run repeatedly.

Usage: python scripts/migrate_m3.py [--mongodb-url URL] [--database NAME]
Both default to the engine's settings (MONGODB_URL / MONGODB_DATABASE), so it
runs as-is inside the engine image.

Roles gained ``tenant_id``, so their unique name index changed from
``(environment_id, name)`` to ``(environment_id, tenant_id, name)``. Beanie
never drops indexes, so the old one must go or it would keep rejecting a tenant
role that shares a name with a project role. Existing roles have no
``tenant_id``; MongoDB indexes a missing field as null, which is exactly what a
project role carries, so no document changes are needed. After the drop,
Beanie creates the new indexes.

Run it before the new version takes traffic; old and new versions must not run
side by side against the same database.

``migrate_database`` works on any async database handle (pymongo's
``AsyncDatabase`` or mongomock-motor's), so the tests run it directly.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

# Run as `python scripts/migrate_m3.py`, only scripts/ is on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beanie import init_beanie  # noqa: E402
from pymongo import AsyncMongoClient  # noqa: E402

from osiki.configs.settings import get_settings  # noqa: E402
from osiki.models.role import Role  # noqa: E402

OLD_ROLE_NAME_INDEX = "environment_id_1_name_1"


async def drop_old_role_name_index(database: Any) -> bool:
    existing = await database["roles"].index_information()
    if OLD_ROLE_NAME_INDEX not in existing:
        return False
    await database["roles"].drop_index(OLD_ROLE_NAME_INDEX)
    print(f"roles: dropped index {OLD_ROLE_NAME_INDEX}")
    return True


async def migrate_database(database: Any) -> bool:
    """Drop the old index, then let Beanie create the new ones.

    Returns whether the old index was present.
    """
    dropped = await drop_old_role_name_index(database)
    await init_beanie(database=database, document_models=[Role])
    return dropped


async def migrate(url: str, database_name: str) -> bool:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(url)
    try:
        return await migrate_database(client.get_database(database_name))
    finally:
        await client.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the M3 data migration.")
    parser.add_argument("--mongodb-url", default=settings.mongodb_url)
    parser.add_argument("--database", default=settings.mongodb_database)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(migrate(args.mongodb_url, args.database))


if __name__ == "__main__":
    main()
