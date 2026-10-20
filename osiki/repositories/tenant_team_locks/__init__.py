from osiki.repositories.tenant_team_locks.base_tenant_team_lock_repository import (
    BaseTenantTeamLockRepository,
)
from osiki.repositories.tenant_team_locks.mongodb_tenant_team_lock_repository import (
    MongoDBTenantTeamLockRepository,
)

__all__ = ["BaseTenantTeamLockRepository", "MongoDBTenantTeamLockRepository"]
