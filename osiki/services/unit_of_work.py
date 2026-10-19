import asyncio
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.errors import PyMongoError

from osiki.configs.database import get_client
from osiki.configs.settings import get_settings

TRANSIENT_TRANSACTION_ERROR = "TransientTransactionError"
UNKNOWN_COMMIT_RESULT = "UnknownTransactionCommitResult"
MAX_ATTEMPTS = 3

type Operation[T] = Callable[[AsyncClientSession | None], Awaitable[T]]


class UnitOfWork(ABC):
    """One atomic operation: every write made with the yielded session commits
    together, or none does."""

    @abstractmethod
    def transaction(self) -> AbstractAsyncContextManager[AsyncClientSession | None]:
        """Open a transaction. Yields the session to pass to repository writes,
        or ``None`` when transactions are off. Commits on a clean exit and
        aborts if the body raises."""

    async def run[T](self, operation: Operation[T]) -> T:
        """Run ``operation`` (reads, checks and writes) as one transaction.

        Without real transactions there is nothing to retry: it runs once.
        """
        async with self.transaction() as session:
            return await operation(session)


class MongoUnitOfWork(UnitOfWork):
    def __init__(
        self, client: AsyncMongoClient[Any], enabled: bool, backoff: float = 0.1
    ) -> None:
        self._client = client
        self._enabled = enabled
        self._backoff = backoff

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncClientSession | None]:
        if not self._enabled:
            yield None
            return
        async with self._client.start_session() as session:
            async with await session.start_transaction():
                yield session

    async def run[T](self, operation: Operation[T]) -> T:
        """Run ``operation`` in a transaction, up to ``MAX_ATTEMPTS`` times.

        A ``TransientTransactionError`` (a write conflict with a concurrent
        transaction, say) aborts and re-runs the WHOLE operation, checks
        included, so the loser re-evaluates them against the winner's commit.
        A write conflict fails fast rather than waiting, so attempts back off
        (``backoff``, then doubling, jittered) to give the winner time to
        commit. ``UnknownTransactionCommitResult`` retries only the commit: the
        operation may already have committed, and re-running it would apply it
        twice. Any other error aborts and propagates.
        """
        if not self._enabled:
            return await operation(None)
        async with self._client.start_session() as session:
            attempt = 1
            while True:
                await session.start_transaction()
                try:
                    result = await operation(session)
                    await _commit(session)
                    return result
                except BaseException as exc:
                    if session.in_transaction:
                        await session.abort_transaction()
                    if not _transient(exc) or attempt >= MAX_ATTEMPTS:
                        raise
                await asyncio.sleep(
                    self._backoff * 2 ** (attempt - 1) * random.uniform(0.5, 1.5)
                )
                attempt += 1


def _transient(exc: BaseException) -> bool:
    return isinstance(exc, PyMongoError) and exc.has_error_label(
        TRANSIENT_TRANSACTION_ERROR
    )


async def _commit(session: AsyncClientSession) -> None:
    attempt = 1
    while True:
        try:
            await session.commit_transaction()
            return
        except PyMongoError as exc:
            if not exc.has_error_label(UNKNOWN_COMMIT_RESULT) or (
                attempt >= MAX_ATTEMPTS
            ):
                raise
            attempt += 1


class NullUnitOfWork(UnitOfWork):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncClientSession | None]:
        yield None


def get_unit_of_work() -> UnitOfWork:
    return MongoUnitOfWork(get_client(), get_settings().mongodb_transactions)
