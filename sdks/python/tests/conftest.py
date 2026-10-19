"""Shared fakes: an in-memory engine client and a manual clock."""

import asyncio
from typing import Any

import pytest

from osiki_sdk._decision.models import Snapshot, UserBundle
from osiki_sdk.client import EngineUnavailable
from osiki_sdk.config import OsikiConfig
from osiki_sdk.logs import DecisionLogBatcher
from osiki_sdk.osiki import Osiki
from osiki_sdk.store import PolicyStore

OWN_TEAM = {
    "op": "eq",
    "left": {"ref": "record.team_id"},
    "right": {"ref": "user.team_id"},
}


def make_snapshot(version: int = 1, **extra: Any) -> Snapshot:
    data: dict[str, Any] = {
        "environment_id": "default",
        "version": version,
        "roles": [
            {
                "id": "reader",
                "name": "reader",
                "grants": [
                    {"permission": "invoices:read"},
                    {"permission": "invoices:update", "condition": "own_team"},
                ],
            }
        ],
        "conditions": {"own_team": OWN_TEAM},
    }
    data.update(extra)
    return Snapshot.model_validate(data)


def make_bundle(
    user_id: str = "kofi", *, role: str = "reader", tenants: Any = None
) -> UserBundle:
    return UserBundle.model_validate(
        {
            "user_id": user_id,
            "attributes": {"team_id": "t1"},
            "tenants": tenants if tenants is not None else {"acme": {}},
            "assignments": [{"role_id": role, "scope": {}, "via": "direct"}],
        }
    )


class FakeClient:
    """The EngineClient method surface, backed by in-memory state."""

    def __init__(self) -> None:
        self.snapshot: Snapshot | None = make_snapshot()
        self.config_version = 1
        self.assignments_version = 1
        self.bundles: dict[str, UserBundle] = {"kofi": make_bundle()}
        self.calls: list[tuple[Any, ...]] = []
        self.fail: set[str] = set()
        self.snapshot_delay = False
        self.bundle_gate: asyncio.Event | None = None
        self.report_gate: asyncio.Event | None = None
        self.logs_gate: asyncio.Event | None = None
        self.closed = False

    def _call(self, name: str, *args: Any) -> None:
        self.calls.append((name, *args))
        if name in self.fail:
            raise EngineUnavailable(f"{name} failed")

    def count(self, name: str) -> int:
        return sum(1 for call in self.calls if call[0] == name)

    async def get_snapshot(
        self, etag: str | None
    ) -> tuple[Snapshot | None, str | None]:
        if self.snapshot_delay:
            await asyncio.sleep(0)
        self._call("get_snapshot", etag)
        assert self.snapshot is not None
        current = f'"{self.snapshot.version}"'
        if etag == current:
            return None, etag
        return self.snapshot, current

    async def get_versions(self) -> tuple[int, int]:
        self._call("get_versions")
        return self.config_version, self.assignments_version

    async def get_bundle(self, user_id: str) -> UserBundle | None:
        self._call("get_bundle", user_id)
        bundle = self.bundles.get(user_id)
        if self.bundle_gate is not None:
            await self.bundle_gate.wait()
        return bundle

    async def report_endpoints(self, endpoints: list[tuple[str, str]]) -> None:
        await asyncio.sleep(0)  # yield, so concurrent discovers interleave
        self._call("report_endpoints", endpoints)
        if self.report_gate is not None:
            await self.report_gate.wait()

    async def send_access_logs(self, entries: list[dict[str, Any]]) -> None:
        if self.logs_gate is not None:
            await self.logs_gate.wait()
        self._call("send_access_logs", list(entries))

    async def upsert_user(self, user_id: str, **kwargs: Any) -> None:
        self._call("upsert_user", user_id, kwargs)

    async def upsert_tenant(self, tenant_id: str, **kwargs: Any) -> None:
        self._call("upsert_tenant", tenant_id, kwargs)

    async def add_member(self, tenant_id: str, user_id: str) -> None:
        self._call("add_member", tenant_id, user_id)

    async def remove_member(self, tenant_id: str, user_id: str) -> bool:
        self._call("remove_member", tenant_id, user_id)
        return True

    async def aclose(self) -> None:
        self.closed = True


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


CONFIG = OsikiConfig(
    base_url="http://engine", poll_interval=0.0, bundle_ttl=60.0, bundle_cache_size=3
)


@pytest.fixture
def fake() -> FakeClient:
    return FakeClient()


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(fake: FakeClient, clock: ManualClock) -> PolicyStore:
    return PolicyStore(fake, CONFIG, clock=clock)  # type: ignore[arg-type]


def make_osiki(
    fake: FakeClient,
    clock: ManualClock,
    config: OsikiConfig = CONFIG,
    user_id: Any = lambda request: None,
    **kwargs: Any,
) -> Osiki:
    """An Osiki wired to ``fake``: swaps client, store and batcher (the test seam)."""
    osiki = Osiki(config, user_id=user_id, **kwargs)
    osiki._client = fake  # type: ignore[assignment]
    osiki._store = PolicyStore(fake, config, clock=clock)  # type: ignore[arg-type]
    osiki._batcher = DecisionLogBatcher(fake, config)  # type: ignore[arg-type]
    return osiki


@pytest.fixture
async def osiki(fake: FakeClient, clock: ManualClock) -> Any:
    instance = make_osiki(fake, clock)
    yield instance
    await instance.aclose()
