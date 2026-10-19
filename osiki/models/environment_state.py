from beanie import Document
from pymongo import IndexModel


class EnvironmentState(Document):
    """Per-environment bookkeeping; ``config_version`` versions the snapshot.

    Every write to roles, permissions, conditions or constraints bumps
    ``config_version``, so a cached snapshot is stale when its version differs.
    """

    environment_id: str
    config_version: int = 0

    class Settings:
        name = "environment_states"
        indexes = [IndexModel([("environment_id", 1)], unique=True)]
