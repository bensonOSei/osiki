import pytest

from osiki.configs.database import get_client
from osiki.services.unit_of_work import MongoUnitOfWork
from tests.mocks import make_audit_log, make_role, make_user, make_user_role
from tests.realmongo.conftest import RealMongoEnv

pytestmark = pytest.mark.realmongo


async def test_failure_rolls_back_role_and_audit(realmongo_env: RealMongoEnv):
    uow = MongoUnitOfWork(get_client(), enabled=True)
    with pytest.raises(RuntimeError):
        async with uow.transaction() as s:
            await realmongo_env.roles.create(make_role(name="X"), session=s)
            await realmongo_env.audit.create(make_audit_log(), session=s)
            raise RuntimeError("boom")
    assert await realmongo_env.roles.get_by_name("X") is None
    assert await realmongo_env.audit.list(None, 0, 10) == []


async def test_failure_rolls_back_the_version_bump(realmongo_env: RealMongoEnv):
    uow = MongoUnitOfWork(get_client(), enabled=True)
    with pytest.raises(RuntimeError):
        async with uow.transaction() as s:
            await realmongo_env.roles.create(make_role(name="X"), session=s)
            assert s is not None
            # Inside the transaction the bump is visible to the session only.
            assert await realmongo_env.state.bump_config_version(session=s) == 2
            raise RuntimeError("boom")
    assert await realmongo_env.state.get_config_version() == 0


async def test_clean_exit_commits_everything(realmongo_env: RealMongoEnv):
    uow = MongoUnitOfWork(get_client(), enabled=True)
    async with uow.transaction() as s:
        await realmongo_env.roles.create(make_role(name="Y"), session=s)
        await realmongo_env.audit.create(make_audit_log(), session=s)
        # Uncommitted writes are invisible outside the transaction.
        assert await realmongo_env.roles.get_by_name("Y") is None
    assert await realmongo_env.roles.get_by_name("Y") is not None
    assert len(await realmongo_env.audit.list(None, 0, 10)) == 1
    assert await realmongo_env.state.get_config_version() == 1


async def test_failure_rolls_back_assignment_writes(realmongo_env: RealMongoEnv):
    role = await realmongo_env.roles.create(make_role(name="R"))
    committed = await realmongo_env.users.upsert_by_external_id(
        "u-committed", None, None, None
    )
    assert committed.id is not None and role.id is not None
    assignments_before = await realmongo_env.state.get_assignments_version()

    uow = MongoUnitOfWork(get_client(), enabled=True)
    with pytest.raises(RuntimeError):
        async with uow.transaction() as s:
            fresh = await realmongo_env.users.upsert_by_external_id(
                "u-new", "New", None, None, session=s
            )
            await realmongo_env.members.add("t1", str(committed.id), session=s)
            assert await realmongo_env.members.is_member(
                "t1", str(committed.id), session=s
            )
            ur = await realmongo_env.user_roles.create(
                make_user_role(committed.id, role.id), session=s
            )
            assert fresh.id is not None
            found = await realmongo_env.user_roles.find_assignment(
                str(committed.id), str(role.id), session=s
            )
            assert found is not None
            assert (
                len(
                    await realmongo_env.user_roles.get_user_roles(
                        str(committed.id), session=s
                    )
                )
                == 1
            )
            await realmongo_env.user_roles.revoke(str(ur.id), session=s)
            raise RuntimeError("boom")

    assert await realmongo_env.users.get_by_external_id("u-new") is None
    assert not await realmongo_env.members.is_member("t1", str(committed.id))
    assert await realmongo_env.user_roles.get_user_roles(str(committed.id)) == []
    assert await realmongo_env.state.get_assignments_version() == assignments_before


async def test_session_reaches_update_deactivate_and_remove(
    realmongo_env: RealMongoEnv,
):
    role = await realmongo_env.roles.create(make_role(name="D"))
    user = await realmongo_env.users.create(make_user("u-1"))
    await realmongo_env.members.add("t1", str(user.id))
    uow = MongoUnitOfWork(get_client(), enabled=True)
    with pytest.raises(RuntimeError):
        async with uow.transaction() as s:
            assert role.id is not None
            fetched = await realmongo_env.roles.get_by_id(str(role.id), session=s)
            assert fetched is not None
            fetched.description = "changed"
            await realmongo_env.roles.update(fetched, session=s)
            assert await realmongo_env.roles.deactivate(str(role.id), session=s)
            assert await realmongo_env.members.remove("t1", str(user.id), session=s)
            await realmongo_env.users.upsert_by_external_id(
                "u-1", "Renamed", None, None, session=s
            )
            raise RuntimeError("boom")
    after = await realmongo_env.roles.get_by_id(str(role.id))
    assert after is not None and after.is_active and after.description != "changed"
    assert await realmongo_env.members.is_member("t1", str(user.id))
    reloaded = await realmongo_env.users.get_by_external_id("u-1")
    assert reloaded is not None and reloaded.name != "Renamed"
