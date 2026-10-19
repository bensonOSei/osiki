from types import TracebackType
from typing import Any

import pytest
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.errors import OperationFailure, PyMongoError

from osiki.services import unit_of_work
from osiki.services.unit_of_work import (
    MongoUnitOfWork,
    NullUnitOfWork,
    get_unit_of_work,
)


def labelled(label: str) -> OperationFailure:
    return OperationFailure("conflict", 112, {"errorLabels": [label]})


TRANSIENT = "TransientTransactionError"
UNKNOWN = "UnknownTransactionCommitResult"


class Script:
    """An operation that raises the queued errors, one per call, then returns."""

    def __init__(self, *errors: BaseException) -> None:
        self.errors = list(errors)
        self.sessions: list[AsyncClientSession | None] = []

    async def __call__(self, session: AsyncClientSession | None) -> str:
        self.sessions.append(session)
        if self.errors:
            raise self.errors.pop(0)
        return "done"


def uow(client: Any) -> MongoUnitOfWork:
    return MongoUnitOfWork(client, enabled=True, backoff=0)


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
    """Also scripts ``run``: each queued commit error is raised by one commit."""

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.in_transaction = False
        self.commit_errors: list[BaseException] = []

    async def __aenter__(self) -> "FakeSession":
        self._events.append("session-start")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._events.append("session-end")

    async def start_transaction(self) -> FakeTransaction:
        self.in_transaction = True
        return FakeTransaction(self._events)

    async def commit_transaction(self) -> None:
        self.in_transaction = False
        if self.commit_errors:
            self._events.append("commit-failed")
            raise self.commit_errors.pop(0)
        self._events.append("commit")

    async def abort_transaction(self) -> None:
        self.in_transaction = False
        self._events.append("abort")


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


async def test_run_without_transactions_runs_once_with_no_session():
    client = FakeClient()
    op = Script()
    assert await MongoUnitOfWork(client, enabled=False).run(op) == "done"  # type: ignore[arg-type]
    assert op.sessions == [None]
    assert client.events == []


async def test_null_uow_run_runs_once_with_no_session():
    op = Script()
    assert await NullUnitOfWork().run(op) == "done"
    assert op.sessions == [None]


async def test_run_commits_a_clean_operation():
    client = FakeClient()
    op = Script()
    assert await uow(client).run(op) == "done"
    assert op.sessions == [client.session]
    assert client.events == ["session-start", "commit", "session-end"]


async def test_run_reruns_the_whole_operation_after_a_transient_error():
    client = FakeClient()
    op = Script(labelled(TRANSIENT))
    assert await uow(client).run(op) == "done"
    assert len(op.sessions) == 2
    assert client.events == ["session-start", "abort", "commit", "session-end"]


async def test_run_gives_up_after_three_attempts():
    client = FakeClient()
    op = Script(labelled(TRANSIENT), labelled(TRANSIENT), labelled(TRANSIENT))
    with pytest.raises(OperationFailure):
        await uow(client).run(op)
    assert len(op.sessions) == 3
    assert "commit" not in client.events


@pytest.mark.parametrize(
    "error", [RuntimeError("boom"), labelled("SomethingElse"), PyMongoError("x")]
)
async def test_run_aborts_and_raises_other_errors_at_once(error: BaseException):
    client = FakeClient()
    op = Script(error)
    with pytest.raises(type(error)):
        await uow(client).run(op)
    assert len(op.sessions) == 1
    assert client.events == ["session-start", "abort", "session-end"]


async def test_run_retries_only_the_commit_when_its_result_is_unknown():
    client = FakeClient()
    client.session.commit_errors = [labelled(UNKNOWN), labelled(UNKNOWN)]
    op = Script()
    assert await uow(client).run(op) == "done"
    # The operation ran once: it may already have committed.
    assert len(op.sessions) == 1
    assert client.events == [
        "session-start",
        "commit-failed",
        "commit-failed",
        "commit",
        "session-end",
    ]


async def test_run_raises_when_the_commit_result_stays_unknown():
    client = FakeClient()
    client.session.commit_errors = [labelled(UNKNOWN)] * 3
    with pytest.raises(OperationFailure):
        await uow(client).run(Script())
    assert client.events.count("commit-failed") == 3


async def test_run_reruns_the_operation_when_the_commit_is_transient():
    client = FakeClient()
    client.session.commit_errors = [labelled(TRANSIENT)]
    op = Script()
    assert await uow(client).run(op) == "done"
    assert len(op.sessions) == 2
    # The failed commit ended the transaction: there is nothing to abort.
    assert client.events == ["session-start", "commit-failed", "commit", "session-end"]


async def test_run_backs_off_between_attempts(monkeypatch: pytest.MonkeyPatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(unit_of_work.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(unit_of_work.random, "uniform", lambda a, b: 1.0)
    op = Script(labelled(TRANSIENT), labelled(TRANSIENT))
    await MongoUnitOfWork(FakeClient(), enabled=True, backoff=0.1).run(op)  # type: ignore[arg-type]
    assert sleeps == [0.1, 0.2]
