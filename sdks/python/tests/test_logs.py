import asyncio
import logging
from collections import deque
from collections.abc import Callable
from typing import Any

import pytest
from conftest import FakeClient

from osiki_sdk import logs
from osiki_sdk.config import OsikiConfig
from osiki_sdk.logs import DecisionLogBatcher

QUIET = OsikiConfig(base_url="http://engine", log_flush_interval=60.0)


def entry(n: int, *, allowed: bool = False) -> dict[str, Any]:
    return {"n": n, "allowed": allowed}


async def eventually(condition: Callable[[], bool]) -> None:
    for _ in range(500):
        if condition():
            return
        await asyncio.sleep(0.002)
    raise AssertionError("condition never became true")


def sent(fake: FakeClient) -> list[list[dict[str, Any]]]:
    return [call[1] for call in fake.calls if call[0] == "send_access_logs"]


async def test_denials_always_logged(
    fake: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = OsikiConfig(base_url="http://engine", log_success_sample_rate=0.0)
    batcher = DecisionLogBatcher(fake, config)  # type: ignore[arg-type]
    monkeypatch.setattr(logs.random, "random", lambda: 0.99)
    for n in range(5):
        batcher.record(entry(n))
    batcher.record(entry(99, allowed=True))
    await batcher.stop()
    assert sent(fake) == [[entry(n) for n in range(5)]]


async def test_successes_sampled(
    fake: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = OsikiConfig(base_url="http://engine", log_success_sample_rate=0.1)
    batcher = DecisionLogBatcher(fake, config)  # type: ignore[arg-type]
    draws = iter([0.05, 0.5, 0.0999, 0.1])
    monkeypatch.setattr(logs.random, "random", lambda: next(draws))
    for n in range(4):
        batcher.record(entry(n, allowed=True))
    await batcher.stop()
    assert sent(fake) == [[entry(0, allowed=True), entry(2, allowed=True)]]


async def test_flush_on_batch_size_and_interval(fake: FakeClient) -> None:
    by_size = OsikiConfig(
        base_url="http://engine", log_batch_size=3, log_flush_interval=60.0
    )
    batcher = DecisionLogBatcher(fake, by_size)  # type: ignore[arg-type]
    batcher.start()
    batcher.start()  # idempotent
    batcher.record(entry(1))
    batcher.record(entry(2))
    await asyncio.sleep(0.01)
    assert sent(fake) == []  # below the batch size, long interval: nothing yet
    batcher.record(entry(3))
    await eventually(lambda: len(sent(fake)) == 1)
    assert sent(fake) == [[entry(1), entry(2), entry(3)]]
    await batcher.stop()
    assert len(sent(fake)) == 1  # nothing pending: stop sends nothing

    fake.calls.clear()
    by_time = OsikiConfig(
        base_url="http://engine", log_batch_size=100, log_flush_interval=0.01
    )
    batcher = DecisionLogBatcher(fake, by_time)  # type: ignore[arg-type]
    batcher.start()
    batcher.record(entry(1))
    await eventually(lambda: len(sent(fake)) == 1)
    batcher.record(entry(2))
    await eventually(lambda: len(sent(fake)) == 2)
    assert sent(fake) == [[entry(1)], [entry(2)]]
    await batcher.stop()
    await batcher.stop()  # idempotent


async def test_record_is_non_blocking_while_a_send_is_slow(fake: FakeClient) -> None:
    config = OsikiConfig(
        base_url="http://engine", log_batch_size=1, log_flush_interval=60.0
    )
    batcher = DecisionLogBatcher(fake, config)  # type: ignore[arg-type]
    fake.logs_gate = asyncio.Event()
    batcher.start()
    batcher.record(entry(1))
    await asyncio.sleep(0.01)  # the flush loop is now blocked inside the send
    batcher.record(entry(2))  # returns at once
    fake.logs_gate.set()
    await batcher.stop()  # waits for the in-flight send, then flushes the rest
    assert sent(fake) == [[entry(1)], [entry(2)]]


async def test_flush_failure_dropped(
    fake: FakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    batcher = DecisionLogBatcher(fake, QUIET)  # type: ignore[arg-type]
    fake.fail.add("send_access_logs")
    batcher.record(entry(1))
    with caplog.at_level(logging.WARNING, logger="osiki_sdk.logs"):
        await batcher.stop()
    assert "dropped 1 decision log" in caplog.text
    fake.fail.clear()
    batcher.start()
    batcher.record(entry(2))
    await batcher.stop()
    assert sent(fake) == [[entry(1)], [entry(2)]]  # the failed batch is not retried


async def test_flush_loop_survives_send_failure(fake: FakeClient) -> None:
    config = OsikiConfig(
        base_url="http://engine", log_batch_size=1, log_flush_interval=60.0
    )
    batcher = DecisionLogBatcher(fake, config)  # type: ignore[arg-type]
    fake.fail.add("send_access_logs")
    batcher.start()
    batcher.record(entry(1))
    await eventually(lambda: len(sent(fake)) == 1)
    fake.fail.clear()
    batcher.record(entry(2))
    await eventually(lambda: len(sent(fake)) == 2)
    await batcher.stop()


async def test_queue_bounded(fake: FakeClient) -> None:
    batcher = DecisionLogBatcher(fake, QUIET)  # type: ignore[arg-type]
    for n in range(10_005):
        batcher.record(entry(n))
    await batcher.stop()
    [batch] = sent(fake)
    assert len(batch) == 10_000
    assert batch[0] == entry(5) and batch[-1] == entry(10_004)  # oldest dropped


async def test_record_after_stop_is_dropped_with_one_warning(
    fake: FakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    batcher = DecisionLogBatcher(fake, QUIET)  # type: ignore[arg-type]
    batcher.start()
    batcher.record(entry(1))
    await batcher.stop()
    assert sent(fake) == [[entry(1)]]
    with caplog.at_level(logging.WARNING, logger="osiki_sdk.logs"):
        for n in range(3):
            batcher.record(entry(n))
        await batcher.stop()  # a second stop: nothing queued, nothing sent
    assert batcher._queue == deque()
    assert sent(fake) == [[entry(1)]]
    warnings = [
        r.getMessage() for r in caplog.records if "after stop" in r.getMessage()
    ]
    assert len(warnings) == 1  # at the first drop; later drops only counted
    assert batcher.dropped_after_stop == 3
    # Restarting accepts entries again; a later stop warns afresh.
    batcher.start()
    batcher.record(entry(7))
    await batcher.stop()
    assert sent(fake)[-1] == [entry(7)]
    with caplog.at_level(logging.WARNING, logger="osiki_sdk.logs"):
        batcher.record(entry(8))
    warnings = [
        r.getMessage() for r in caplog.records if "after stop" in r.getMessage()
    ]
    assert len(warnings) == 2
    assert batcher.dropped_after_stop == 1


async def test_record_before_start_is_queued(fake: FakeClient) -> None:
    batcher = DecisionLogBatcher(fake, QUIET)  # type: ignore[arg-type]
    batcher.record(entry(1))
    batcher.start()
    await batcher.stop()
    assert sent(fake) == [[entry(1)]]
