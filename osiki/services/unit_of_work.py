from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.client_session import AsyncClientSession

from osiki.configs.database import get_client
from osiki.configs.settings import get_settings


class UnitOfWork(ABC):
    """One atomic operation: every write made with the yielded session commits
    together, or none does."""

    @abstractmethod
    def transaction(self) -> AbstractAsyncContextManager[AsyncClientSession | None]:
        """Open a transaction. Yields the session to pass to repository writes,
        or ``None`` when transactions are off. Commits on a clean exit and
        aborts if the body raises."""


class MongoUnitOfWork(UnitOfWork):
    def __init__(self, client: AsyncMongoClient[Any], enabled: bool) -> None:
        self._client = client
        self._enabled = enabled

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncClientSession | None]:
        if not self._enabled:
            yield None
            return
        async with self._client.start_session() as session:
            async with await session.start_transaction():
                yield session


class NullUnitOfWork(UnitOfWork):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncClientSession | None]:
        yield None


def get_unit_of_work() -> UnitOfWork:
    return MongoUnitOfWork(get_client(), get_settings().mongodb_transactions)
