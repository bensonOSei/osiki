"""A PATCH carrying ``expected_updated_at`` writes only while the stored role
still has that value, so a concurrent edit is refused, never overwritten (D3)."""

import asyncio

import pytest

from osiki.api.actor import Actor
from osiki.models.role import Role
from osiki.services.team.models import StaleRole
from osiki.services.team.team_service import TeamService
from tests.realmongo.conftest import RealMongoEnv
from tests.realmongo.test_last_manager_race import service

pytestmark = pytest.mark.realmongo

DEVELOPER = Actor(type="developer", id="dev")


async def test_edit_landing_after_the_check_is_refused(
    realmongo_env: RealMongoEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = realmongo_env
    role = await service(env, DEVELOPER).create_role("Till", [], None)
    check = TeamService._check_update_role

    async def check_then_race(
        self: TeamService, *args: object, **kwargs: object
    ) -> tuple[Role, dict[str, object], bool]:
        result = await check(self, *args, **kwargs)  # type: ignore[arg-type]
        stored = await env.roles.get_by_id(role.id)
        assert stored is not None
        stored.name = "Cashier"
        await env.roles.update(stored)
        return result

    monkeypatch.setattr(TeamService, "_check_update_role", check_then_race)

    with pytest.raises(StaleRole):
        await service(env, DEVELOPER).update_role(
            role.id, "Waiter", None, role.updated_at
        )
    stored = await env.roles.get_by_id(role.id)
    assert stored is not None and stored.name == "Cashier"


async def test_two_patches_with_one_token_one_wins(
    realmongo_env: RealMongoEnv,
) -> None:
    env = realmongo_env
    role = await service(env, DEVELOPER).create_role("Till", [], None)

    results = await asyncio.gather(
        service(env, DEVELOPER).update_role(role.id, "Cashier", None, role.updated_at),
        service(env, DEVELOPER).update_role(role.id, "Waiter", None, role.updated_at),
        return_exceptions=True,
    )

    stale = [r for r in results if isinstance(r, StaleRole)]
    won = [r for r in results if not isinstance(r, BaseException)]
    assert len(stale) == 1 and len(won) == 1
    stored = await env.roles.get_by_id(role.id)
    assert stored is not None and stored.name == won[0].name
