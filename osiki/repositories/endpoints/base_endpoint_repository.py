from abc import ABC, abstractmethod

from osiki.decision.models import EndpointEntry
from osiki.models.endpoint import DiscoveredEndpoint, EndpointMapping


class BaseEndpointRepository(ABC):
    @abstractmethod
    async def record_discovered(
        self, endpoints: list[tuple[str, str]], now: float
    ) -> int:
        """Upsert ``(method, path)`` pairs, setting ``last_seen``.

        Does not bump the config version: discovery never changes the snapshot.
        Returns the number of distinct endpoints recorded.
        """

    @abstractmethod
    async def list_discovered(self) -> list[DiscoveredEndpoint]: ...

    @abstractmethod
    async def upsert_mapping(self, entry: EndpointEntry) -> EndpointMapping:
        """Create or replace a mapping and bump the config version."""

    @abstractmethod
    async def delete_mapping(self, method: str, path: str) -> bool:
        """Delete a mapping; bump the config version only when one existed."""

    @abstractmethod
    async def list_mappings(self) -> list[EndpointMapping]: ...
