from osiki.repositories.tenants.base_tenant_repository import BaseTenantRepository
from osiki.repositories.tenants.mongodb_tenant_repository import (
    MongoDBTenantRepository,
)

__all__ = ["BaseTenantRepository", "MongoDBTenantRepository"]
