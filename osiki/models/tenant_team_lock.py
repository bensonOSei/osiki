from beanie import Document
from pymongo import IndexModel

from osiki.models.base import EnvironmentMixin


class TenantTeamLock(Document, EnvironmentMixin):
    """A per-tenant counter every guarded team write increments first.

    Two transactions that both ``$inc`` it write-conflict, so concurrent team
    writes in one tenant serialise: the loser aborts, retries and re-evaluates
    its checks (the last-manager guard above all) against the winner's commit.
    """

    tenant_id: str
    version: int = 0

    class Settings:
        name = "tenant_team_locks"
        indexes = [IndexModel([("environment_id", 1), ("tenant_id", 1)], unique=True)]
