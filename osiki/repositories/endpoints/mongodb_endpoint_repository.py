import time

from loguru import logger

from osiki.decision.models import EndpointEntry
from osiki.models.endpoint import DiscoveredEndpoint, EndpointMapping
from osiki.repositories.endpoints.base_endpoint_repository import (
    BaseEndpointRepository,
)
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)


class MongoDBEndpointRepository(BaseEndpointRepository):
    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        self.environment_id = environment_id
        self._state = state

    async def record_discovered(
        self, endpoints: list[tuple[str, str]], now: float
    ) -> int:
        unique = list(dict.fromkeys(endpoints))
        collection = DiscoveredEndpoint.get_pymongo_collection()
        for method, path in unique:
            await collection.update_one(
                {
                    "environment_id": self.environment_id,
                    "method": method,
                    "path": path,
                },
                {"$set": {"last_seen": now}, "$setOnInsert": {"first_seen": now}},
                upsert=True,
            )
        return len(unique)

    async def list_discovered(self) -> list[DiscoveredEndpoint]:
        return await DiscoveredEndpoint.find(
            DiscoveredEndpoint.environment_id == self.environment_id
        ).to_list()

    async def upsert_mapping(self, entry: EndpointEntry) -> EndpointMapping:
        fields = entry.model_dump()
        mapping = await EndpointMapping.find_one(
            EndpointMapping.environment_id == self.environment_id,
            EndpointMapping.method == entry.method,
            EndpointMapping.path == entry.path,
        )
        if mapping is None:
            mapping = EndpointMapping(environment_id=self.environment_id, **fields)
            await mapping.insert()
        else:
            for name, value in fields.items():
                setattr(mapping, name, value)
            mapping.updated_at = time.time()
            await mapping.save()
        await self._state.bump_config_version()
        logger.debug("Endpoint mapped", method=entry.method, path=entry.path)
        return mapping

    async def delete_mapping(self, method: str, path: str) -> bool:
        mapping = await EndpointMapping.find_one(
            EndpointMapping.environment_id == self.environment_id,
            EndpointMapping.method == method,
            EndpointMapping.path == path,
        )
        if mapping is None:
            return False
        await mapping.delete()
        await self._state.bump_config_version()
        return True

    async def list_mappings(self) -> list[EndpointMapping]:
        return await EndpointMapping.find(
            EndpointMapping.environment_id == self.environment_id
        ).to_list()
