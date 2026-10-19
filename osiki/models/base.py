import json
import time
from typing import Any

from pydantic import BaseModel, Field

AttributeValue = str | int | float | bool | None | list[str | int | float]


def attributes_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare attribute maps type-strictly, ignoring dict key order.

    Plain ``==`` treats ``True == 1`` and ``[1] == [1.0]``, but the rule engine
    never treats a boolean as a number, so such a change must still be saved.
    """
    return json.dumps(left, sort_keys=True, default=str) == json.dumps(
        right, sort_keys=True, default=str
    )


class TimestampMixin(BaseModel):
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class EnvironmentMixin(BaseModel):
    environment_id: str = "default"


class SoftDeleteMixin(BaseModel):
    is_active: bool = True


class MetadataMixin(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scope(BaseModel):
    model_config = {"extra": "allow"}

    tenant_id: str | None = None
    region: str | None = None
    branch_id: str | None = None
    department: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in self.model_dump().items() if v is not None}
