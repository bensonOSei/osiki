from beanie import init_beanie
from loguru import logger
from pymongo import AsyncMongoClient

from osiki.models.access_log import AccessLog
from osiki.models.audit_log import AuditLog
from osiki.models.constraint import Constraint
from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.permission import Permission
from osiki.models.role import Role
from osiki.models.tenant import Tenant
from osiki.models.tenant_member import TenantMember
from osiki.models.user import User
from osiki.models.user_group import UserGroup
from osiki.models.user_role import UserRole


async def initialize_database(db_url: str, db_name: str = "osiki") -> None:
    logger.info("Initializing database connection", db_name=db_name)
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(db_url)
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
            AuditLog,
            AccessLog,
            Tenant,
            TenantMember,
        ],
    )
    logger.info("Database initialized successfully with 12 document models")
