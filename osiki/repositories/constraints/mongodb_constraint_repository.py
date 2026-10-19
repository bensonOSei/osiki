import time

from beanie import PydanticObjectId
from loguru import logger

from osiki.models.constraint import Constraint, ConstraintType
from osiki.repositories.constraints.base_constraint_repository import (
    BaseConstraintRepository,
)
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)


class MongoDBConstraintRepository(BaseConstraintRepository):
    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        self.environment_id = environment_id
        self._state = state

    async def create(self, constraint: Constraint) -> Constraint:
        constraint.environment_id = self.environment_id
        await constraint.insert()
        await self._state.bump_config_version()
        logger.info(
            "Constraint created",
            constraint_id=str(constraint.id),
            name=constraint.name,
            type=constraint.type.value,
        )
        return constraint

    async def get_by_id(self, constraint_id: str) -> Constraint | None:
        constraint = await Constraint.find_one(
            {
                "_id": PydanticObjectId(constraint_id),
                "environment_id": self.environment_id,
            }
        )
        if not constraint:
            logger.debug("Constraint not found", constraint_id=constraint_id)
        return constraint

    async def get_active(self) -> list[Constraint]:
        return await Constraint.find(
            Constraint.environment_id == self.environment_id,
            Constraint.is_active == True,
        ).to_list()

    async def get_by_type(self, constraint_type: ConstraintType) -> list[Constraint]:
        return await Constraint.find(
            Constraint.environment_id == self.environment_id,
            Constraint.type == constraint_type,
            Constraint.is_active == True,
        ).to_list()

    async def get_by_role_id(self, role_id: str) -> list[Constraint]:
        role_oid = PydanticObjectId(role_id)
        return await Constraint.find(
            Constraint.environment_id == self.environment_id,
            Constraint.is_active == True,
            {
                "$or": [
                    {"config.role_ids": role_oid},
                    {"config.role_id": role_oid},
                    {"config.requires_role_id": role_oid},
                ]
            },
        ).to_list()

    async def update(self, constraint: Constraint) -> Constraint:
        constraint.updated_at = time.time()
        await constraint.save()
        await self._state.bump_config_version()
        logger.info("Constraint updated", constraint_id=str(constraint.id))
        return constraint

    async def deactivate(self, constraint_id: str) -> bool:
        constraint = await self.get_by_id(constraint_id)
        if not constraint:
            logger.warning(
                "Attempted to deactivate non-existent constraint",
                constraint_id=constraint_id,
            )
            return False
        constraint.is_active = False
        constraint.updated_at = time.time()
        await constraint.save()
        await self._state.bump_config_version()
        logger.info("Constraint deactivated", constraint_id=constraint_id)
        return True
