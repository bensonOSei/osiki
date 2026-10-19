import time
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

from osiki.decision.models import EndpointEntry
from osiki.models.base import EnvironmentMixin, TimestampMixin


class DiscoveredEndpoint(Document, EnvironmentMixin):
    """A route an SDK reported; never part of the snapshot."""

    method: str
    path: str
    first_seen: float = Field(default_factory=time.time)
    last_seen: float = Field(default_factory=time.time)

    class Settings:
        name = "discovered_endpoints"
        indexes = [
            IndexModel(
                [("environment_id", 1), ("method", 1), ("path", 1)], unique=True
            ),
        ]


class EndpointMapping(Document, EnvironmentMixin, TimestampMixin):
    """A developer's mapping of one endpoint to a permission (or to public)."""

    method: str
    path: str
    permission: str | None = None
    record_type: str | None = None
    record_id_param: str | None = None
    public: bool = False
    on_unavailable: Literal["deny", "allow"] | None = None

    class Settings:
        name = "endpoint_mappings"
        indexes = [
            IndexModel(
                [("environment_id", 1), ("method", 1), ("path", 1)], unique=True
            ),
        ]

    def to_entry(self) -> EndpointEntry:
        """The snapshot's view of this mapping (the one place fields are copied)."""
        return EndpointEntry.model_validate(self, from_attributes=True)
