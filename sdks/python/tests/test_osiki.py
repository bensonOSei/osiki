import asyncio
import dataclasses
import logging
import statistics
import time
import uuid
from typing import Any

import httpx
import pytest
from conftest import CONFIG, FakeClient, ManualClock, make_osiki
from fastapi import FastAPI

import osiki_sdk
from osiki_sdk import (
    Decision,
    EngineError,
    EngineUnavailable,
    FilterResult,
    Osiki,
    OsikiConfig,
    OsikiUnavailable,
    to_record,
)
from osiki_sdk.client import EngineClient
from osiki_sdk.store import PolicyStore


def test_public_exports() -> None:
    assert set(osiki_sdk.__all__) >= {
        "Osiki",
        "OsikiConfig",
        "Decision",
        "FilterResult",
        "to_record",
        "OsikiUnavailable",
        "EngineError",
        "EngineUnavailable",
    }
    assert callable(to_record) and issubclass(EngineError, Exception)
    assert issubclass(EngineUnavailable, Exception)


async def test_config_kwargs_build_config() -> None:
    osiki = Osiki(base_url="http://engine", environment="dev", user_id=lambda r: None)
    assert osiki.config == OsikiConfig(base_url="http://engine", environment="dev")
    assert isinstance(osiki._client, EngineClient)
    assert isinstance(osiki._store, PolicyStore)
    assert osiki.started is False
    await osiki.aclose()


def test_config_and_kwargs_together_rejected() -> None:
    with pytest.raises(TypeError, match="not both"):
        Osiki(CONFIG, user_id=lambda r: None, environment="dev")


async def test_transport_is_used() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"environment_id": "e", "version": 1})

    osiki = Osiki(
        base_url="http://engine",
        user_id=lambda r: None,
        transport=httpx.MockTransport(handler),
    )
    await osiki._store.refresh_snapshot()
    assert seen == ["/api/v1/snapshot"]
    await osiki.aclose()


async def test_check_allows_via_cached_snapshot_and_bundle(
    osiki: Osiki, fake: FakeClient
) -> None:
    await osiki.start()
    first = await osiki.check("kofi", "invoices", "read")
    assert first.allowed is True and first.matched_permission == "invoices:read"
    calls = len(fake.calls)
    second = await osiki.check("kofi", "invoices", "read")
    assert second == first
    assert len(fake.calls) == calls


async def test_check_denies_without_permission(osiki: Osiki) -> None:
    await osiki._store.refresh_snapshot()
    decision = await osiki.check("kofi", "invoices", "delete")
    assert decision == Decision(allowed=False, denial_reason="no_permission")


async def test_check_passes_tenant_scope(osiki: Osiki) -> None:
    await osiki._store.refresh_snapshot()
    assert (await osiki.check("kofi", "invoices", "read", tenant="acme")).allowed
    other = await osiki.check("kofi", "invoices", "read", tenant="globex")
    assert other.denial_reason == "not_tenant_member"


async def test_check_unavailable_before_first_snapshot_raises(
    osiki: Osiki, fake: FakeClient
) -> None:
    fake.fail.add("get_snapshot")
    await osiki.start()
    assert osiki.started is True
    with pytest.raises(OsikiUnavailable):
        await osiki.check("kofi", "invoices", "read")
    with pytest.raises(OsikiUnavailable):
        await osiki.filter("kofi", "invoices", "read")
    assert fake.count("get_bundle") == 0


async def test_check_unknown_user_returns_unknown_user(osiki: Osiki) -> None:
    await osiki._store.refresh_snapshot()
    decision = await osiki.check("ghost", "invoices", "read")
    assert decision == Decision(allowed=False, denial_reason="unknown_user")


@dataclasses.dataclass
class Invoice:
    id: uuid.UUID
    team_id: str


async def test_check_converts_record_with_to_record(osiki: Osiki) -> None:
    await osiki._store.refresh_snapshot()
    no_record = await osiki.check("kofi", "invoices", "update")
    assert no_record.denial_reason == "record_required"
    own = Invoice(id=uuid.uuid4(), team_id="t1")
    allowed = await osiki.check("kofi", "invoices", "update", record=own)
    assert allowed.allowed is True and allowed.condition == "own_team"
    other = Invoice(id=uuid.uuid4(), team_id="t2")
    denied = await osiki.check("kofi", "invoices", "update", record=other)
    assert denied.denial_reason == "condition_failed"


async def test_filter_returns_typed_filter(osiki: Osiki) -> None:
    await osiki._store.refresh_snapshot()
    result = await osiki.filter("kofi", "invoices", "update", tenant="acme")
    assert result == FilterResult(
        mode="filter",
        filter={"field": "team_id", "op": "eq", "value": "t1", "type": "string"},
    )
    assert (await osiki.filter("kofi", "invoices", "read")).mode == "all"
    assert (await osiki.filter("kofi", "invoices", "delete")).mode == "none"
    assert (await osiki.filter("ghost", "invoices", "read")) == FilterResult(
        mode="none"
    )


async def test_sync_wrappers_call_client_and_invalidate_user(
    osiki: Osiki, fake: FakeClient
) -> None:
    async def fetches_after(action: Any) -> int:
        await osiki._store.get_bundle("kofi")
        before = fake.count("get_bundle")
        await action
        await osiki._store.get_bundle("kofi")
        return fake.count("get_bundle") - before

    assert (
        await fetches_after(
            osiki.users.upsert("kofi", name="Kofi", email="k@x.io", attributes={"a": 1})
        )
        == 1
    )
    assert await fetches_after(osiki.tenants.add_member("acme", "kofi")) == 1
    assert await fetches_after(osiki.tenants.remove_member("acme", "kofi")) == 1
    # Tenant attributes live in every member's bundle, so all bundles go.
    assert (
        await fetches_after(osiki.tenants.upsert("acme", name="Acme", attributes={}))
        == 1
    )
    assert await fetches_after(osiki.tenants.add_member("acme", "ama")) == 0
    sync_calls = [call for call in fake.calls if call[0] != "get_bundle"]
    assert sync_calls == [
        (
            "upsert_user",
            "kofi",
            {"name": "Kofi", "email": "k@x.io", "attributes": {"a": 1}},
        ),
        ("add_member", "acme", "kofi"),
        ("remove_member", "acme", "kofi"),
        ("upsert_tenant", "acme", {"name": "Acme", "attributes": {}}),
        ("add_member", "acme", "ama"),
    ]


async def test_remove_member_returns_client_result(osiki: Osiki) -> None:
    assert await osiki.tenants.remove_member("acme", "kofi") is True


async def test_failed_sync_still_raises(osiki: Osiki, fake: FakeClient) -> None:
    fake.fail.add("upsert_user")
    with pytest.raises(EngineUnavailable):
        await osiki.users.upsert("kofi")


def test_duplicate_loader_raises(fake: FakeClient, clock: ManualClock) -> None:
    osiki = make_osiki(fake, clock)

    @osiki.loader("invoice")
    async def load_invoice(record_id: str) -> Any:
        return {"id": record_id}

    assert osiki.get_loader("invoice") is load_invoice
    assert osiki.get_loader("order") is None
    with pytest.raises(ValueError, match="invoice"):

        @osiki.loader("invoice")
        async def again(record_id: str) -> Any:
            return None


async def test_start_is_idempotent_under_concurrency(
    osiki: Osiki, fake: FakeClient
) -> None:
    fake.snapshot_delay = True  # yield inside start so the calls interleave
    await asyncio.gather(*(osiki.start() for _ in range(50)))
    pollers = [t for t in asyncio.all_tasks() if t.get_name() == "osiki-poller"]
    assert len(pollers) == 1
    assert fake.count("get_snapshot") == 1
    assert osiki.started is True
    await osiki.start()
    assert len([t for t in asyncio.all_tasks() if t.get_name() == "osiki-poller"]) == 1


async def test_start_logs_failed_first_snapshot(
    osiki: Osiki, fake: FakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    fake.fail.add("get_snapshot")
    with caplog.at_level(logging.WARNING, logger="osiki_sdk.osiki"):
        await osiki.start()
    assert "first snapshot" in caplog.text
    assert osiki._store.available is False


async def test_poller_recovers_after_cold_start(osiki: Osiki, fake: FakeClient) -> None:
    fake.fail.add("get_snapshot")
    await osiki.start()
    fake.fail.clear()
    while not osiki._store.available:
        await asyncio.sleep(0)
    assert (await osiki.check("kofi", "invoices", "read")).allowed


async def test_aclose_stops_poller_and_closes_client(
    fake: FakeClient, clock: ManualClock
) -> None:
    osiki = make_osiki(fake, clock)
    await osiki.start()
    poller = osiki._poller
    assert poller is not None
    await osiki.aclose()
    assert poller.cancelled()
    assert osiki.started is False
    assert fake.closed is True
    await osiki.aclose()  # safe twice


async def test_start_after_aclose_raises(fake: FakeClient, clock: ManualClock) -> None:
    osiki = make_osiki(fake, clock)
    await osiki.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await osiki.start()


def _discover_app() -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.get("/invoices/{invoice_id}")
    async def get_invoice(invoice_id: str) -> None:
        return None

    @app.post("/invoices")
    async def create_invoice() -> None:
        return None

    return app


# max(poll_interval=0, 30) for CONFIG.
RETRY_WINDOW = 30.0


async def test_discover_idempotent_and_retries_after_failure(
    osiki: Osiki,
    fake: FakeClient,
    clock: ManualClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _discover_app()
    fake.fail.add("report_endpoints")
    with caplog.at_level(logging.WARNING, logger="osiki_sdk.osiki"):
        await osiki.discover(app)
    assert "endpoint discovery failed" in caplog.text
    fake.fail.clear()
    clock.now = RETRY_WINDOW
    await osiki.discover(app)  # retries after the window, and succeeds
    clock.now = 10 * RETRY_WINDOW
    await osiki.discover(app)  # recorded: no further call
    reports = [call for call in fake.calls if call[0] == "report_endpoints"]
    expected = [("GET", "/invoices/{invoice_id}"), ("POST", "/invoices")]
    assert reports == [("report_endpoints", expected)] * 2

    other = FastAPI()
    await asyncio.gather(*(osiki.discover(other) for _ in range(10)))
    assert fake.count("report_endpoints") == 3


async def test_discover_failure_backs_off_until_window(
    osiki: Osiki, fake: FakeClient, clock: ManualClock
) -> None:
    app = _discover_app()
    fake.fail.add("report_endpoints")
    await asyncio.gather(*(osiki.discover(app) for _ in range(10)))
    for _ in range(10):
        await osiki.discover(app)
    clock.now = RETRY_WINDOW - 0.1
    await osiki.discover(app)
    assert fake.count("report_endpoints") == 1

    clock.now = RETRY_WINDOW
    await osiki.discover(app)  # window over: retries, fails, backs off again
    await osiki.discover(app)
    assert fake.count("report_endpoints") == 2

    fake.fail.clear()
    clock.now = 2 * RETRY_WINDOW
    await osiki.discover(app)
    assert app in osiki._discovered
    clock.now = 100 * RETRY_WINDOW
    await osiki.discover(app)
    assert fake.count("report_endpoints") == 3


async def test_discover_window_follows_longer_poll_interval(
    fake: FakeClient, clock: ManualClock
) -> None:
    osiki = Osiki(
        dataclasses.replace(CONFIG, poll_interval=45.0), user_id=lambda r: None
    )
    await osiki._client.aclose()
    osiki._client = fake  # type: ignore[assignment]
    osiki._store = PolicyStore(fake, osiki.config, clock=clock)  # type: ignore
    app = _discover_app()
    fake.fail.add("report_endpoints")
    await osiki.discover(app)
    clock.now = 44.0
    await osiki.discover(app)
    assert fake.count("report_endpoints") == 1
    clock.now = 45.0
    await osiki.discover(app)
    assert fake.count("report_endpoints") == 2
    await osiki.aclose()


async def test_discover_in_flight_returns_without_waiting(
    osiki: Osiki, fake: FakeClient
) -> None:
    app = _discover_app()
    fake.report_gate = asyncio.Event()
    first = asyncio.create_task(osiki.discover(app))
    while fake.count("report_endpoints") == 0:
        await asyncio.sleep(0)
    # The report is blocked on the gate; a second caller must not wait on it.
    await asyncio.wait_for(osiki.discover(app), timeout=1.0)
    assert not first.done()
    fake.report_gate.set()
    await first
    assert app in osiki._discovered
    assert fake.count("report_endpoints") == 1


@pytest.mark.perf
async def test_check_latency_under_1ms(osiki: Osiki) -> None:
    await osiki._store.refresh_snapshot()
    await osiki.check("kofi", "invoices", "read")
    samples = []
    for _ in range(1000):
        started = time.perf_counter()
        await osiki.check("kofi", "invoices", "update", record={"team_id": "t1"})
        samples.append(time.perf_counter() - started)
    median_ms = statistics.median(samples) * 1000
    print(f"median warm check: {median_ms:.4f} ms")
    assert median_ms < 1.0
