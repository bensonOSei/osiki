from enum import StrEnum

from beanie import Document, PydanticObjectId
from pydantic import BaseModel
from pymongo import IndexModel

from osiki.models.base import EnvironmentMixin, SoftDeleteMixin, TimestampMixin


class ConstraintType(StrEnum):
    MUTUAL_EXCLUSION = "mutual_exclusion"
    CARDINALITY = "cardinality"
    PREREQUISITE = "prerequisite"


class ScopeLevel(StrEnum):
    GLOBAL = "global"
    PER_TENANT = "per_tenant"
    PER_SCOPE = "per_scope"


class ConstraintConfig(BaseModel):
    role_ids: list[PydanticObjectId] | None = None
    role_id: PydanticObjectId | None = None
    max_assignments: int | None = None
    scope_level: ScopeLevel | None = None
    requires_role_id: PydanticObjectId | None = None


class Constraint(Document, EnvironmentMixin, TimestampMixin, SoftDeleteMixin):
    name: str
    description: str | None = None
    type: ConstraintType
    config: ConstraintConfig

    class Settings:
        name = "constraints"
        indexes = [
            IndexModel([("environment_id", 1), ("type", 1), ("is_active", 1)]),
            IndexModel([("environment_id", 1), ("config.role_ids", 1)]),
            IndexModel([("environment_id", 1), ("config.role_id", 1)]),
            IndexModel([("environment_id", 1), ("config.requires_role_id", 1)]),
        ]
