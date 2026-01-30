from pydantic import BaseModel, ConfigDict


class ScopeSchema(BaseModel):
    model_config = ConfigDict(extra="allow", from_attributes=True)

    tenant_id: str | None = None
    region: str | None = None
    branch_id: str | None = None
    department: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in self.model_dump().items() if v is not None}
