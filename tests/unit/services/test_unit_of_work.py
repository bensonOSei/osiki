from types import TracebackType
from typing import Any

import pytest

from osiki.services import unit_of_work
from osiki.services.unit_of_work import (
    MongoUnitOfWork,
    NullUnitOfWork,
    get_unit_of_work,
)


class FakeTransaction:
    """Mirrors pymongo's transaction context: commit on clean exit, abort on error."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def __aenter__(self) -> "FakeTransaction":
        self._events.append("txn-start")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._events.append("abort" if exc_type is not None else "commit")


class FakeSession:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def __aenter__(self) -> "FakeSession":
        self._events.append("session-start")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._events.append("session-end")

    async def start_transaction(self) -> FakeTransaction:
        return FakeTransaction(self._events)


class FakeClient:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.session = FakeSession(self.events)

    def start_session(self) -> FakeSession:
        return self.session


async def test_disabled_mongo_uow_yields_none():
    async with MongoUnitOfWork(client=object(), enabled=False).transaction() as s:  # type: ignore[arg-type]
        assert s is None


async def test_null_uow_yields_none():
    async with NullUnitOfWork().transaction() as s:
        assert s is None


async def test_disabled_mongo_uow_never_touches_the_client():
    client = FakeClient()
    async with MongoUnitOfWork(client, enabled=False).transaction():  # type: ignore[arg-type]
        pass
    assert client.events == []


async def test_enabled_mongo_uow_yields_session_and_commits_on_clean_exit():
    client = FakeClient()
    async with MongoUnitOfWork(client, enabled=True).transaction() as s:  # type: ignore[arg-type]
        assert s is client.session
        assert client.events == ["session-start", "txn-start"]
    assert client.events == ["session-start", "txn-start", "commit", "session-end"]


async def test_enabled_mongo_uow_aborts_and_reraises_on_exception():
    client = FakeClient()
    with pytest.raises(RuntimeError, match="boom"):
        async with MongoUnitOfWork(client, enabled=True).transaction():  # type: ignore[arg-type]
            raise RuntimeError("boom")
    assert client.events == ["session-start", "txn-start", "abort", "session-end"]
    assert "commit" not in client.events


@pytest.mark.parametrize("enabled", [True, False])
def test_get_unit_of_work_builds_from_client_and_settings(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    client = object()

    class Settings:
        mongodb_transactions = enabled

    monkeypatch.setattr(unit_of_work, "get_client", lambda: client)
    monkeypatch.setattr(unit_of_work, "get_settings", lambda: Settings())
    uow: Any = get_unit_of_work()
    assert isinstance(uow, MongoUnitOfWork)
    assert uow._client is client
    assert uow._enabled is enabled
