import os
import uuid

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from scripts import migrate_m3

pytestmark = pytest.mark.realmongo


async def test_migrate_drops_the_old_index_and_is_repeatable() -> None:
    url = os.environ.get("OSIKI_TEST_MONGO_URL")
    if not url:
        pytest.skip("OSIKI_TEST_MONGO_URL not set; run make test-realmongo")
    name = f"osiki_realmongo_m3_{uuid.uuid4().hex}"
    client: AsyncMongoClient = AsyncMongoClient(url)  # type: ignore[type-arg]
    try:
        roles = client[name]["roles"]
        await roles.create_index([("environment_id", 1), ("name", 1)], unique=True)
        await roles.insert_one({"environment_id": "default", "name": "legacy"})

        assert await migrate_m3.migrate(url, name) is True
        assert await migrate_m3.migrate(url, name) is False

        names = set(await roles.index_information())
        assert "environment_id_1_name_1" not in names
        assert "environment_id_1_tenant_id_1_name_1" in names
        await roles.insert_one(
            {"environment_id": "default", "name": "legacy", "tenant_id": "acme"}
        )
        with pytest.raises(DuplicateKeyError):
            await roles.insert_one(
                {"environment_id": "default", "name": "legacy", "tenant_id": "acme"}
            )
        with pytest.raises(DuplicateKeyError):
            await roles.insert_one({"environment_id": "default", "name": "legacy"})
    finally:
        await client.drop_database(name)
        await client.close()
