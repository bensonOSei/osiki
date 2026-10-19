import asyncio
import logging

import pytest
from conftest import CONFIG, FakeClient, ManualClock, make_bundle, make_snapshot

from osiki_sdk.store import PolicyStore


async def test_unavailable_until_first_snapshot(store: PolicyStore) -> None:
    assert store.available is False
    assert store.snapshot is None
    await store.refresh_snapshot()
    assert store.available is True
    assert store.snapshot is not None and store.snapshot.version == 1


async def test_refresh_snapshot_is_etag_aware(
    store: PolicyStore, fake: FakeClient
) -> None:
    await store.refresh_snapshot()
    first = store.snapshot
    await store.refresh_snapshot()
    assert fake.calls == [("get_snapshot", None), ("get_snapshot", '"1"')]
    assert store.snapshot is first


async def test_bundle_cached_including_none(
    store: PolicyStore, fake: FakeClient
) -> None:
    assert (await store.get_bundle("kofi")) == make_bundle()
    assert await store.get_bundle("ghost") is None
    await store.get_bundle("kofi")
    await store.get_bundle("ghost")
    assert fake.count("get_bundle") == 2


async def test_bundle_ttl_expiry_refetches(
    store: PolicyStore, fake: FakeClient, clock: ManualClock
) -> None:
    await store.get_bundle("kofi")
    clock.now = CONFIG.bundle_ttl - 0.1
    await store.get_bundle("kofi")
    assert fake.count("get_bundle") == 1
    clock.now = CONFIG.bundle_ttl
    await store.get_bundle("kofi")
    assert fake.count("get_bundle") == 2


async def test_lru_evicts_oldest(store: PolicyStore, fake: FakeClient) -> None:
    # bundle_cache_size is 3.
    for user in ("a", "b", "c"):
        await store.get_bundle(user)
    await store.get_bundle("a")  # a is now most recently used; b is oldest
    await store.get_bundle("d")  # evicts b
    fake.calls.clear()
    for user in ("a", "c", "d"):
        await store.get_bundle(user)
    assert fake.calls == []
    await store.get_bundle("b")
    assert fake.calls == [("get_bundle", "b")]


async def test_invalidate_user_and_clear_bundles(
    store: PolicyStore, fake: FakeClient
) -> None:
    await store.get_bundle("kofi")
    await store.get_bundle("ama")
    store.invalidate_user("kofi")
    store.invalidate_user("nobody")
    await store.get_bundle("ama")
    await store.get_bundle("kofi")
    assert fake.count("get_bundle") == 3
    store.clear_bundles()
    await store.get_bundle("ama")
    await store.get_bundle("kofi")
    assert fake.count("get_bundle") == 5


async def test_fetch_racing_a_clear_is_not_cached(
    store: PolicyStore, fake: FakeClient
) -> None:
    fake.bundle_gate = asyncio.Event()
    pending = asyncio.create_task(store.get_bundle("kofi"))
    await asyncio.sleep(0)
    store.clear_bundles()  # e.g. a revocation landed while fetching
    fake.bundle_gate.set()
    assert await pending == make_bundle()
    await store.get_bundle("kofi")
    assert fake.count("get_bundle") == 2


async def test_first_poll_refreshes_and_clears(
    store: PolicyStore, fake: FakeClient
) -> None:
    await store.get_bundle("kofi")
    await store.poll_once()
    assert store.snapshot is not None
    await store.get_bundle("kofi")
    assert fake.count("get_bundle") == 2


async def test_assignments_version_change_clears_bundles(
    store: PolicyStore, fake: FakeClient
) -> None:
    await store.poll_once()
    await store.get_bundle("kofi")
    await store.poll_once()
    await store.get_bundle("kofi")
    assert fake.count("get_bundle") == 1
    fake.assignments_version = 2
    await store.poll_once()
    await store.get_bundle("kofi")
    assert fake.count("get_bundle") == 2
    assert fake.count("get_snapshot") == 1


async def test_config_version_change_refreshes_snapshot(
    store: PolicyStore, fake: FakeClient
) -> None:
    await store.poll_once()
    await store.get_bundle("kofi")
    await store.poll_once()
    assert fake.count("get_snapshot") == 1
    fake.snapshot = make_snapshot(version=2)
    fake.config_version = 2
    await store.poll_once()
    assert store.snapshot is not None and store.snapshot.version == 2
    await store.get_bundle("kofi")
    assert fake.count("get_bundle") == 1  # bundles survive a config change


async def test_failed_refresh_is_retried_on_next_poll(
    store: PolicyStore, fake: FakeClient
) -> None:
    await store.poll_once()
    fake.snapshot = make_snapshot(version=2)
    fake.config_version = 2
    fake.fail.add("get_snapshot")
    with pytest.raises(Exception, match="get_snapshot failed"):
        await store.poll_once()
    assert store.snapshot is not None and store.snapshot.version == 1
    fake.fail.clear()
    await store.poll_once()
    assert store.snapshot.version == 2


async def test_poll_error_keeps_last_snapshot(
    fake: FakeClient, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    store = PolicyStore(fake, CONFIG, clock=clock)  # type: ignore[arg-type]
    await store.refresh_snapshot()
    good = store.snapshot
    fake.fail.add("get_versions")
    with caplog.at_level(logging.WARNING, logger="osiki_sdk.store"):
        poller = asyncio.create_task(store.run_poller())
        while fake.count("get_versions") < 3:
            await asyncio.sleep(0)
        poller.cancel()
        await asyncio.wait({poller})
    assert store.snapshot is good
    assert store.available is True
    assert "osiki poll failed" in caplog.text
