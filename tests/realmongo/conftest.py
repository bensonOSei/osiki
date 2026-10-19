"""Real-MongoDB harness: needs a replica set, since transactions require one.

Run through ``make test-realmongo`` (scripts/realmongo-test.sh), which starts
the server and exports OSIKI_TEST_MONGO_URL. These tests re-initialise Beanie
on the real server, so run them on their own, not alongside the mongomock suite.
"""

import os
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest

from osiki.configs import database
from osiki.configs.database import initialize_database
from osiki.configs.settings import get_settings
from osiki.repositories.audit_logs.mongodb_audit_log_repository import (
    MongoDBAuditLogRepository,
)
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.roles.mongodb_role_repository import MongoDBRoleRepository
from osiki.repositories.tenant_members.mongodb_tenant_member_repository import (
    MongoDBTenantMemberRepository,
)
from osiki.repositories.user_roles.mongodb_user_role_repository import (
    MongoDBUserRoleRepository,
)
from osiki.repositories.users.mongodb_user_repository import MongoDBUserRepository

ENVIRONMENT_ID = "default"


@dataclass
class RealMongoEnv:
    state: MongoDBEnvironmentStateRepository
    roles: MongoDBRoleRepository
    users: MongoDBUserRepository
    user_roles: MongoDBUserRoleRepository
    members: MongoDBTenantMemberRepository
    audit: MongoDBAuditLogRepository


@pytest.fixture
async def realmongo_env(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[RealMongoEnv]:
    url = os.environ.get("OSIKI_TEST_MONGO_URL")
    if not url:
        pytest.skip("OSIKI_TEST_MONGO_URL not set; run make test-realmongo")
    monkeypatch.setenv("MONGODB_TRANSACTIONS", "true")
    get_settings.cache_clear()
    db_name = f"osiki_realmongo_{uuid.uuid4().hex}"
    await initialize_database(url, db_name)
    client = database.get_client()
    state = MongoDBEnvironmentStateRepository(ENVIRONMENT_ID)
    try:
        yield RealMongoEnv(
            state=state,
            roles=MongoDBRoleRepository(ENVIRONMENT_ID, state),
            users=MongoDBUserRepository(ENVIRONMENT_ID, state),
            user_roles=MongoDBUserRoleRepository(ENVIRONMENT_ID, state),
            members=MongoDBTenantMemberRepository(ENVIRONMENT_ID, state),
            audit=MongoDBAuditLogRepository(ENVIRONMENT_ID),
        )
    finally:
        await client.drop_database(db_name)
        await client.close()
        database._client = None
        get_settings.cache_clear()
