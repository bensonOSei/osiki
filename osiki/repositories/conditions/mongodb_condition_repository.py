import time

from beanie import PydanticObjectId
from loguru import logger

from osiki.models.condition import Condition
from osiki.repositories.conditions.base_condition_repository import (
    BaseConditionRepository,
)
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)


class MongoDBConditionRepository(BaseConditionRepository):
    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        self.environment_id = environment_id
        self._state = state

    async def create(self, condition: Condition) -> Condition:
        condition.environment_id = self.environment_id
        await condition.insert()
        await self._state.bump_config_version()
        logger.info(
            "Condition created", condition_id=str(condition.id), key=condition.key
        )
        return condition

    async def get_by_id(self, condition_id: str) -> Condition | None:
        return await Condition.find_one(
            {
                "_id": PydanticObjectId(condition_id),
                "environment_id": self.environment_id,
            }
        )

    async def get_by_key(self, key: str) -> Condition | None:
        # Includes inactive rows: the unique (environment_id, key) index does too.
        return await Condition.find_one(
            Condition.environment_id == self.environment_id,
            Condition.key == key,
        )

    async def get_by_ids(self, ids: list[str]) -> list[Condition]:
        object_ids = [PydanticObjectId(i) for i in ids]
        return await Condition.find(
            Condition.environment_id == self.environment_id,
            {"_id": {"$in": object_ids}, "is_active": True},
        ).to_list()

    async def get_all(self) -> list[Condition]:
        # Includes inactive rows so a grant's condition key can still be named.
        return await Condition.find(
            Condition.environment_id == self.environment_id
        ).to_list()

    async def update(self, condition: Condition) -> Condition:
        condition.updated_at = time.time()
        await condition.save()
        await self._state.bump_config_version()
        logger.info("Condition updated", condition_id=str(condition.id))
        return condition

    async def deactivate(self, condition_id: str) -> bool:
        condition = await self.get_by_id(condition_id)
        if not condition:
            logger.warning(
                "Attempted to deactivate non-existent condition",
                condition_id=condition_id,
            )
            return False
        condition.is_active = False
        condition.updated_at = time.time()
        await condition.save()
        await self._state.bump_config_version()
        logger.info("Condition deactivated", condition_id=condition_id)
        return True

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Condition]:
        return (
            await Condition.find(
                Condition.environment_id == self.environment_id,
                Condition.is_active == True,
            )
            .sort("created_at")
            .skip(skip)
            .limit(limit)
            .to_list()
        )
