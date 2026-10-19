"""Run scripts/migrate_m3.py against mongomock with M2-shaped role indexes."""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import DuplicateKeyError

from scripts import migrate_m3

NEW_UNIQUE = "environment_id_1_tenant_id_1_name_1"


@pytest.fixture
async def mongo_db_with_m2_indexes() -> AsyncGenerator[Any]:
    client = AsyncMongoMockClient()
    database = client.migrate_m3_test
    await database.roles.create_index([("environment_id", 1), ("name", 1)], unique=True)
    await database.roles.insert_one(
        {"environment_id": "default", "name": "legacy", "grants": []}
    )
    yield database
    client.close()


async def _index_names(database: Any) -> list[str]:
    return list(await database.roles.index_information())


async def test_migrate_m3_drops_old_name_index(mongo_db_with_m2_indexes: Any) -> None:
    assert "environment_id_1_name_1" in await _index_names(mongo_db_with_m2_indexes)

    dropped = await migrate_m3.migrate_database(mongo_db_with_m2_indexes)

    names = await _index_names(mongo_db_with_m2_indexes)
    assert dropped is True
    assert "environment_id_1_name_1" not in names
    assert NEW_UNIQUE in names


async def test_migrate_m3_is_idempotent(mongo_db_with_m2_indexes: Any) -> None:
    first = await migrate_m3.migrate_database(mongo_db_with_m2_indexes)
    after_first = await _index_names(mongo_db_with_m2_indexes)
    second = await migrate_m3.migrate_database(mongo_db_with_m2_indexes)

    assert (first, second) == (True, False)
    assert await _index_names(mongo_db_with_m2_indexes) == after_first


async def test_migrate_m3_on_a_fresh_database() -> None:
    client = AsyncMongoMockClient()
    try:
        assert await migrate_m3.migrate_database(client.fresh) is False
        assert NEW_UNIQUE in await client.fresh.roles.index_information()
    finally:
        client.close()


async def test_after_migration_a_tenant_role_may_share_a_project_role_name(
    mongo_db_with_m2_indexes: Any,
) -> None:
    roles = mongo_db_with_m2_indexes.roles
    with pytest.raises(DuplicateKeyError):
        await roles.insert_one(
            {"environment_id": "default", "name": "legacy", "tenant_id": None}
        )

    await migrate_m3.migrate_database(mongo_db_with_m2_indexes)

    await roles.insert_one(
        {"environment_id": "default", "name": "legacy", "tenant_id": "acme"}
    )
    with pytest.raises(DuplicateKeyError):
        await roles.insert_one(
            {"environment_id": "default", "name": "legacy", "tenant_id": "acme"}
        )
    # An M2 role has no tenant_id at all: the new index treats it as null.
    with pytest.raises(DuplicateKeyError):
        await roles.insert_one({"environment_id": "default", "name": "legacy"})


def test_arguments_default_from_settings() -> None:
    args = migrate_m3.parse_args([])
    settings = migrate_m3.get_settings()
    assert args.mongodb_url == settings.mongodb_url
    assert args.database == settings.mongodb_database


def test_arguments_can_be_overridden() -> None:
    args = migrate_m3.parse_args(["--mongodb-url", "mongodb://x/y", "--database", "z"])
    assert (args.mongodb_url, args.database) == ("mongodb://x/y", "z")
