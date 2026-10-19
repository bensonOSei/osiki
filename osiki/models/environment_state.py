from typing import Literal

from beanie import Document
from pymongo import IndexModel


class EnvironmentState(Document):
    """Per-environment bookkeeping; ``config_version`` versions the snapshot.

    Every write to roles, permissions, conditions or constraints bumps
    ``config_version``, so a cached snapshot is stale when its version differs.
    Every write to assignments, memberships or users bumps
    ``assignments_version``, which SDKs poll to refresh user bundles.
    ``unmapped_policy`` is the environment's setting for unmapped endpoints.
    """

    environment_id: str
    config_version: int = 0
    assignments_version: int = 0
    unmapped_policy: Literal["deny", "allow"] = "deny"

    class Settings:
        name = "environment_states"
        indexes = [IndexModel([("environment_id", 1)], unique=True)]
