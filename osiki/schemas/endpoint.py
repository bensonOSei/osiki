import re

from pydantic import BaseModel, Field, field_validator, model_validator

from osiki.decision.models import EndpointEntry

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_PERMISSION = re.compile(r"^[^:]+:[^:]+$")
_RECORD_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class EndpointRef(BaseModel):
    method: str
    path: str


class DiscoveredEndpointsCreate(BaseModel):
    endpoints: list[EndpointRef] = Field(min_length=1, max_length=1000)


class DiscoveredEndpointsRecorded(BaseModel):
    recorded: int


class EndpointMappingWrite(EndpointEntry):
    """The body of ``PUT /endpoints/mapping``: an ``EndpointEntry`` that is checked.

    ``permission`` may be omitted for a public endpoint.
    """

    permission: str | None = None

    @field_validator("method")
    @classmethod
    def _method(cls, value: str) -> str:
        if value not in METHODS:
            raise ValueError(f"method must be one of {', '.join(METHODS)}")
        return value

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("path must start with '/'")
        return value

    @field_validator("permission")
    @classmethod
    def _permission(cls, value: str | None) -> str | None:
        if value is not None and not _PERMISSION.match(value):
            raise ValueError("permission must look like 'resource:action'")
        return value

    @field_validator("record_type")
    @classmethod
    def _record_type(cls, value: str | None) -> str | None:
        if value is not None and not _RECORD_TYPE.match(value):
            raise ValueError("record_type must match ^[a-z][a-z0-9_]{0,62}$")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "EndpointMappingWrite":
        if not self.public and self.permission is None:
            raise ValueError("a non-public endpoint requires a permission")
        if (self.record_type is None) != (self.record_id_param is None):
            raise ValueError("record_type and record_id_param must be set together")
        if self.record_id_param is not None and not re.search(
            r"\{" + re.escape(self.record_id_param) + r"(:[^}]*)?\}", self.path
        ):
            raise ValueError("record_id_param must appear in path as {name}")
        return self


class EndpointStatusRead(BaseModel):
    method: str
    path: str
    mapping: EndpointEntry | None = None
    last_seen: float | None = None
