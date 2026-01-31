import time

from beanie import PydanticObjectId
from loguru import logger

from osiki.models.role import Role
from osiki.repositories.roles.base_role_repository import BaseRoleRepository


class MongoDBRoleRepository(BaseRoleRepository):
    async def create(self, role: Role) -> Role:
        await role.insert()
        logger.debug("Role created", role_id=str(role.id), name=role.name)
        return role

    async def get_by_id(self, role_id: str) -> Role | None:
        role = await Role.get(PydanticObjectId(role_id))
        if not role:
            logger.debug("Role not found", role_id=role_id)
        return role

    async def get_by_name(self, name: str) -> Role | None:
        return await Role.find_one(Role.name == name, Role.is_active == True)

    async def get_by_ids(self, role_ids: list[str]) -> list[Role]:
        object_ids = [PydanticObjectId(rid) for rid in role_ids]
        return await Role.find(
            {"_id": {"$in": object_ids}, "is_active": True}
        ).to_list()

    async def get_children(self, parent_role_id: str) -> list[Role]:
        return await Role.find(
            Role.parent_role_id == PydanticObjectId(parent_role_id),
            Role.is_active == True,
        ).to_list()

    async def update(self, role: Role) -> Role:
        role.updated_at = time.time()
        await role.save()
        logger.debug("Role updated", role_id=str(role.id))
        return role

    async def deactivate(self, role_id: str) -> bool:
        role = await self.get_by_id(role_id)
        if not role:
            logger.warning("Attempted to deactivate non-existent role", role_id=role_id)
            return False
        if role.is_system:
            logger.warning("Attempted to deactivate system role", role_id=role_id)
            return False
        role.is_active = False
        role.updated_at = time.time()
        await role.save()
        logger.info("Role deactivated", role_id=role_id)
        return True

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Role]:
        return await Role.find(Role.is_active == True).skip(skip).limit(limit).to_list()

    async def add_permission(self, role_id: str, permission_id: str) -> bool:
        role = await self.get_by_id(role_id)
        if not role:
            logger.warning(
                "Attempted to add permission to non-existent role", role_id=role_id
            )
            return False
        perm_oid = PydanticObjectId(permission_id)
        if perm_oid not in role.permission_ids:
            role.permission_ids.append(perm_oid)
            role.updated_at = time.time()
            await role.save()
            logger.info(
                "Permission added to role", role_id=role_id, permission_id=permission_id
            )
        return True

    async def remove_permission(self, role_id: str, permission_id: str) -> bool:
        role = await self.get_by_id(role_id)
        if not role:
            logger.warning(
                "Attempted to remove permission from non-existent role", role_id=role_id
            )
            return False
        perm_oid = PydanticObjectId(permission_id)
        if perm_oid in role.permission_ids:
            role.permission_ids.remove(perm_oid)
            role.updated_at = time.time()
            await role.save()
            logger.info(
                "Permission removed from role",
                role_id=role_id,
                permission_id=permission_id,
            )
        return True
