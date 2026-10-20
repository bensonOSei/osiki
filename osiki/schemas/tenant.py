from pydantic import BaseModel, ConfigDict, Field

from osiki.models.base import AttributeValue


class TenantUpsert(BaseModel):
    name: str
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    name: str
    attributes: dict[str, AttributeValue]
    created_at: float
    updated_at: float


class TenantSummaryRead(TenantRead):
    """A tenant with its member count, for the developer dashboard's list."""

    member_count: int
