from pymongo import ReturnDocument

from osiki.decision.models import EnvironmentSettings
from osiki.models.environment_state import EnvironmentState
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)


class MongoDBEnvironmentStateRepository(BaseEnvironmentStateRepository):
    def __init__(self, environment_id: str) -> None:
        self.environment_id = environment_id

    async def get_config_version(self) -> int:
        state = await EnvironmentState.find_one(
            EnvironmentState.environment_id == self.environment_id
        )
        return state.config_version if state else 0

    async def bump_config_version(self) -> int:
        return await self._bump("config_version")

    async def get_assignments_version(self) -> int:
        state = await EnvironmentState.find_one(
            EnvironmentState.environment_id == self.environment_id
        )
        return state.assignments_version if state else 0

    async def bump_assignments_version(self) -> int:
        return await self._bump("assignments_version")

    async def get_settings(self) -> EnvironmentSettings:
        state = await EnvironmentState.find_one(
            EnvironmentState.environment_id == self.environment_id
        )
        if state is None:
            return EnvironmentSettings()
        return EnvironmentSettings(unmapped=state.unmapped_policy)

    async def _bump(self, field: str) -> int:
        # One atomic $inc with upsert: concurrent writers never lose a bump.
        doc = await EnvironmentState.get_pymongo_collection().find_one_and_update(
            {"environment_id": self.environment_id},
            {"$inc": {field: 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        # upsert + ReturnDocument.AFTER always yields the document.
        assert doc is not None
        version: int = doc[field]
        return version
