"""Run scripts/migrate_m1.py against mongomock with pre-M1 shaped documents."""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from beanie import PydanticObjectId
from mongomock_motor import AsyncMongoMockClient

from osiki.models.access_log import AccessLog
from osiki.models.audit_log import AuditLog
from osiki.models.constraint import Constraint
from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.permission import Permission
from osiki.models.role import Role
from osiki.models.user import User
from osiki.models.user_group import UserGroup
from osiki.models.user_role import UserRole
from scripts import migrate_m1

MODELS = [
    User,
    Group,
    Role,
    Permission,
    UserRole,
    UserGroup,
    GroupRole,
    Constraint,
    AuditLog,
    AccessLog,
]


@pytest.fixture
async def database() -> AsyncGenerator[Any]:
    client = AsyncMongoMockClient()
    yield client.migrate_m1_test
    client.close()


async def _index_names(database: Any, collection: str) -> set[str]:
    return set(await database[collection].index_information())


def _current_index_names(model: Any) -> set[str]:
    return {index.document["name"] for index in model.Settings.indexes}


def test_legacy_indexes_never_name_a_current_index() -> None:
    for model in MODELS:
        collection = model.Settings.name
        legacy = set(migrate_m1.LEGACY_INDEXES.get(collection, []))
        assert legacy.isdisjoint(_current_index_names(model)), collection


def test_superseded_assignment_indexes_are_dropped() -> None:
    assert (
        "environment_id_1_user_id_1_role_id_1_scope.tenant_id_1_is_active_1"
        in migrate_m1.LEGACY_INDEXES["user_roles"]
    )
    assert (
        "environment_id_1_group_id_1_role_id_1_scope.tenant_id_1_is_active_1"
        in migrate_m1.LEGACY_INDEXES["group_roles"]
    )
    assert (
        "environment_id_1_user_id_1_group_id_1_is_active_1"
        in migrate_m1.LEGACY_INDEXES["user_groups"]
    )


async def _seed_base_schema(database: Any) -> dict[str, PydanticObjectId]:
    """Documents and indexes as the pre-M1 base schema wrote them."""
    ids = {name: PydanticObjectId() for name in ("p1", "p2", "p3", "u", "r")}
    await database.permissions.insert_many(
        [
            {"_id": ids["p1"], "resource": "docs", "action": "read"},
            {"_id": ids["p2"], "resource": "docs", "action": "write"},
            {"_id": ids["p3"], "resource": "docs", "action": "delete"},
        ]
    )
    await database.roles.insert_many(
        [
            # Base schema: permission_ids, no grants at all.
            {"name": "plain", "permission_ids": [ids["p1"], ids["p2"]]},
            # A grants list that is empty must not hide permission_ids.
            {"name": "empty", "grants": [], "permission_ids": [ids["p1"]]},
            {"name": "null", "grants": None, "permission_ids": [ids["p2"]]},
            # Both present: keep the grants and add what is missing.
            {
                "name": "both",
                "grants": [
                    {"permission_id": ids["p1"], "condition_id": None},
                    {"permission_id": ids["p2"], "condition_id": ids["r"]},
                ],
                "permission_ids": [ids["p1"], ids["p2"], ids["p3"]],
            },
            {"name": "none", "permission_ids": None},
            # Already migrated: untouched.
            {
                "name": "done",
                "environment_id": "staging",
                "grants": [{"permission_id": ids["p3"], "condition_id": None}],
            },
        ]
    )
    await database.users.insert_one({"_id": ids["u"], "external_id": "u1"})
    await database.user_roles.insert_many(
        [
            {"user_id": ids["u"], "role_id": ids["r"], "is_active": False},
            {"user_id": ids["u"], "role_id": ids["r"], "is_active": True},
        ]
    )

    await database.users.create_index("external_id", unique=True)
    await database.users.create_index("email", unique=True, sparse=True)
    await database.users.create_index([("is_active", 1), ("created_at", -1)])
    await database.roles.create_index("name", unique=True)
    await database.roles.create_index("permission_ids")
    await database.permissions.create_index(
        [("resource", 1), ("action", 1)], unique=True
    )
    await database.permissions.create_index("resource")
    await database.user_roles.create_index(
        [("user_id", 1), ("role_id", 1), ("scope.tenant_id", 1), ("is_active", 1)],
        unique=True,
        sparse=True,
    )
    await database.user_roles.create_index([("user_id", 1), ("is_active", 1)])
    await database.user_roles.create_index("expires_at", sparse=True)
    # The M1-era (A1) unique index that included is_active.
    await database.user_roles.create_index(
        [
            ("environment_id", 1),
            ("user_id", 1),
            ("role_id", 1),
            ("scope.tenant_id", 1),
            ("is_active", 1),
        ],
        unique=True,
        sparse=True,
    )
    await database.user_groups.create_index(
        [("user_id", 1), ("group_id", 1), ("is_active", 1)], unique=True, sparse=True
    )
    await database.constraints.create_index("config.role_ids")
    await database.audit_logs.create_index([("timestamp", -1)])
    await database.audit_logs.create_index("timestamp", expireAfterSeconds=63072000)
    await database.access_logs.create_index([("user_id", 1), ("timestamp", -1)])
    return ids


async def test_migrate_database_twice(database: Any) -> None:
    ids = await _seed_base_schema(database)

    first = await migrate_m1.migrate_database(database)
    second = await migrate_m1.migrate_database(database)

    assert first["roles"] == 5  # "done" already had an environment
    assert first["role_grants"] == 5
    assert second == {name: 0 for name in first}

    roles = {r["name"]: r async for r in database.roles.find({})}
    assert all("permission_ids" not in role for role in roles.values())
    assert {r["environment_id"] for r in roles.values()} == {"default", "staging"}

    def grants(name: str) -> list[tuple[Any, Any]]:
        return [(g["permission_id"], g["condition_id"]) for g in roles[name]["grants"]]

    assert grants("plain") == [(ids["p1"], None), (ids["p2"], None)]
    assert grants("empty") == [(ids["p1"], None)]
    assert grants("null") == [(ids["p2"], None)]
    # The conditional p2 grant could not stand in for the unconditional one.
    assert grants("both") == [
        (ids["p1"], None),
        (ids["p2"], ids["r"]),
        (ids["p2"], None),
        (ids["p3"], None),
    ]
    assert grants("none") == []
    assert grants("done") == [(ids["p3"], None)]

    user_roles = [ur async for ur in database.user_roles.find({})]
    assert {ur["environment_id"] for ur in user_roles} == {"default"}

    for collection, legacy in migrate_m1.LEGACY_INDEXES.items():
        assert (await _index_names(database, collection)).isdisjoint(legacy)
    # The TTL index keeps its name in the current model, so it stays.
    assert "timestamp_1" in await _index_names(database, "audit_logs")


async def test_migrate_database_on_empty_database(database: Any) -> None:
    counts = await migrate_m1.migrate_database(database)

    assert set(counts) == {*migrate_m1.COLLECTIONS, "role_grants"}
    assert all(count == 0 for count in counts.values())
