from typing import Any

from beanie import init_beanie
from loguru import logger
from pymongo import AsyncMongoClient

from osiki.models.access_log import AccessLog
from osiki.models.audit_log import AuditLog
from osiki.models.condition import Condition
from osiki.models.constraint import Constraint
from osiki.models.endpoint import DiscoveredEndpoint, EndpointMapping
from osiki.models.environment_state import EnvironmentState
from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.permission import Permission
from osiki.models.role import Role
from osiki.models.tenant import Tenant
from osiki.models.tenant_member import TenantMember
from osiki.models.user import User
from osiki.models.user_group import UserGroup
from osiki.models.user_role import UserRole

_client: AsyncMongoClient[Any] | None = None


def get_client() -> AsyncMongoClient[Any]:
    """The process-wide Mongo client; only valid after ``initialize_database``."""
    if _client is None:
        raise RuntimeError("Database not initialized; call initialize_database first")
    return _client


async def initialize_database(db_url: str, db_name: str = "osiki") -> None:
    logger.info("Initializing database connection", db_name=db_name)
    global _client
    client: AsyncMongoClient[Any] = AsyncMongoClient(db_url)
    _client = client
    await init_beanie(
        database=client.get_database(db_name),
        document_models=[
            User,
            Group,
            Role,
            Permission,
            UserRole,
            UserGroup,
            GroupRole,
            Constraint,
            Condition,
            AuditLog,
            AccessLog,
            Tenant,
            TenantMember,
            EnvironmentState,
            DiscoveredEndpoint,
            EndpointMapping,
        ],
    )
    logger.info("Database initialized successfully with 16 document models")
