import time

from beanie import PydanticObjectId

from osiki.models.access_log import AccessLog
from osiki.models.constraint import Constraint, ConstraintType
from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.permission import Permission
from osiki.models.role import Role
from osiki.models.user import User
from osiki.models.user_group import UserGroup
from osiki.models.user_role import UserRole
from osiki.repositories.access_logs.base_access_log_repository import (
    BaseAccessLogRepository,
)
from osiki.repositories.constraints.base_constraint_repository import (
    BaseConstraintRepository,
)
from osiki.repositories.group_roles.base_group_role_repository import (
    BaseGroupRoleRepository,
)
from osiki.repositories.groups.base_group_repository import BaseGroupRepository
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository
from osiki.repositories.user_groups.base_user_group_repository import (
    BaseUserGroupRepository,
)
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)
from osiki.repositories.users.base_user_repository import BaseUserRepository


class MockUserRoleRepository(BaseUserRoleRepository):
    def __init__(self) -> None:
        self._data: dict[str, UserRole] = {}

    async def create(self, user_role: UserRole) -> UserRole:
        if user_role.id is None:
            user_role.id = PydanticObjectId()
        self._data[str(user_role.id)] = user_role
        return user_role

    async def get_by_id(self, user_role_id: str) -> UserRole | None:
        return self._data.get(user_role_id)

    async def get_user_roles(self, user_id: str) -> list[UserRole]:
        return [
            ur
            for ur in self._data.values()
            if str(ur.user_id) == user_id and ur.is_active
        ]

    async def get_users_with_role(self, role_id: str) -> list[UserRole]:
        return [
            ur
            for ur in self._data.values()
            if str(ur.role_id) == role_id and ur.is_active
        ]

    async def get_by_tenant(
        self, tenant_id: str, role_id: str | None = None
    ) -> list[UserRole]:
        result = []
        for ur in self._data.values():
            if ur.scope.tenant_id == tenant_id and ur.is_active:
                if role_id is None or str(ur.role_id) == role_id:
                    result.append(ur)
        return result

    async def find_assignment(
        self, user_id: str, role_id: str, tenant_id: str | None = None
    ) -> UserRole | None:
        for ur in self._data.values():
            if (
                str(ur.user_id) == user_id
                and str(ur.role_id) == role_id
                and ur.is_active
            ):
                if tenant_id is None or ur.scope.tenant_id == tenant_id:
                    return ur
        return None

    async def revoke(self, user_role_id: str) -> bool:
        if user_role_id in self._data:
            self._data[user_role_id].is_active = False
            return True
        return False

    async def get_expired(self, current_time: float) -> list[UserRole]:
        return [
            ur
            for ur in self._data.values()
            if ur.is_active
            and ur.expires_at is not None
            and ur.expires_at <= current_time
        ]


class MockUserGroupRepository(BaseUserGroupRepository):
    def __init__(self) -> None:
        self._data: dict[str, UserGroup] = {}

    async def create(self, user_group: UserGroup) -> UserGroup:
        if user_group.id is None:
            user_group.id = PydanticObjectId()
        self._data[str(user_group.id)] = user_group
        return user_group

    async def get_by_id(self, user_group_id: str) -> UserGroup | None:
        return self._data.get(user_group_id)

    async def get_user_groups(self, user_id: str) -> list[UserGroup]:
        return [
            ug
            for ug in self._data.values()
            if str(ug.user_id) == user_id and ug.is_active
        ]

    async def get_group_members(self, group_id: str) -> list[UserGroup]:
        return [
            ug
            for ug in self._data.values()
            if str(ug.group_id) == group_id and ug.is_active
        ]

    async def find_membership(self, user_id: str, group_id: str) -> UserGroup | None:
        for ug in self._data.values():
            if (
                str(ug.user_id) == user_id
                and str(ug.group_id) == group_id
                and ug.is_active
            ):
                return ug
        return None

    async def remove(self, user_group_id: str) -> bool:
        if user_group_id in self._data:
            self._data[user_group_id].is_active = False
            return True
        return False


class MockGroupRoleRepository(BaseGroupRoleRepository):
    def __init__(self) -> None:
        self._data: dict[str, GroupRole] = {}

    async def create(self, group_role: GroupRole) -> GroupRole:
        if group_role.id is None:
            group_role.id = PydanticObjectId()
        self._data[str(group_role.id)] = group_role
        return group_role

    async def get_by_id(self, group_role_id: str) -> GroupRole | None:
        return self._data.get(group_role_id)

    async def get_group_roles(self, group_id: str) -> list[GroupRole]:
        return [
            gr
            for gr in self._data.values()
            if str(gr.group_id) == group_id and gr.is_active
        ]

    async def get_roles_for_groups(self, group_ids: list[str]) -> list[GroupRole]:
        return [
            gr
            for gr in self._data.values()
            if str(gr.group_id) in group_ids and gr.is_active
        ]

    async def get_groups_with_role(self, role_id: str) -> list[GroupRole]:
        return [
            gr
            for gr in self._data.values()
            if str(gr.role_id) == role_id and gr.is_active
        ]

    async def find_assignment(
        self, group_id: str, role_id: str, tenant_id: str | None = None
    ) -> GroupRole | None:
        for gr in self._data.values():
            if (
                str(gr.group_id) == group_id
                and str(gr.role_id) == role_id
                and gr.is_active
            ):
                if tenant_id is None or gr.scope.tenant_id == tenant_id:
                    return gr
        return None

    async def revoke(self, group_role_id: str) -> bool:
        if group_role_id in self._data:
            self._data[group_role_id].is_active = False
            return True
        return False

    async def get_expired(self, current_time: float) -> list[GroupRole]:
        return [
            gr
            for gr in self._data.values()
            if gr.is_active
            and gr.expires_at is not None
            and gr.expires_at <= current_time
        ]


class MockRoleRepository(BaseRoleRepository):
    def __init__(self) -> None:
        self._data: dict[str, Role] = {}

    async def create(self, role: Role) -> Role:
        if role.id is None:
            role.id = PydanticObjectId()
        self._data[str(role.id)] = role
        return role

    async def get_by_id(self, role_id: str) -> Role | None:
        return self._data.get(role_id)

    async def get_by_name(self, name: str) -> Role | None:
        for role in self._data.values():
            if role.name == name and role.is_active:
                return role
        return None

    async def get_by_ids(self, role_ids: list[str]) -> list[Role]:
        return [self._data[rid] for rid in role_ids if rid in self._data]

    async def get_children(self, parent_role_id: str) -> list[Role]:
        return [
            role
            for role in self._data.values()
            if role.parent_role_id and str(role.parent_role_id) == parent_role_id
        ]

    async def update(self, role: Role) -> Role:
        role.updated_at = time.time()
        self._data[str(role.id)] = role
        return role

    async def deactivate(self, role_id: str) -> bool:
        if role_id in self._data:
            self._data[role_id].is_active = False
            return True
        return False

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Role]:
        active = [r for r in self._data.values() if r.is_active]
        return active[skip : skip + limit]

    async def add_permission(self, role_id: str, permission_id: str) -> bool:
        if role_id in self._data:
            self._data[role_id].permission_ids.append(PydanticObjectId(permission_id))
            return True
        return False

    async def remove_permission(self, role_id: str, permission_id: str) -> bool:
        if role_id in self._data:
            pid = PydanticObjectId(permission_id)
            if pid in self._data[role_id].permission_ids:
                self._data[role_id].permission_ids.remove(pid)
                return True
        return False


class MockPermissionRepository(BasePermissionRepository):
    def __init__(self) -> None:
        self._data: dict[str, Permission] = {}

    async def create(self, permission: Permission) -> Permission:
        if permission.id is None:
            permission.id = PydanticObjectId()
        self._data[str(permission.id)] = permission
        return permission

    async def get_by_id(self, permission_id: str) -> Permission | None:
        return self._data.get(permission_id)

    async def get_by_ids(self, permission_ids: list[str]) -> list[Permission]:
        return [self._data[pid] for pid in permission_ids if pid in self._data]

    async def get_by_resource_action(
        self, resource: str, action: str
    ) -> Permission | None:
        for perm in self._data.values():
            if perm.resource == resource and perm.action == action and perm.is_active:
                return perm
        return None

    async def get_by_resource(self, resource: str) -> list[Permission]:
        return [
            p for p in self._data.values() if p.resource == resource and p.is_active
        ]

    async def deactivate(self, permission_id: str) -> bool:
        if permission_id in self._data:
            self._data[permission_id].is_active = False
            return True
        return False

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Permission]:
        active = [p for p in self._data.values() if p.is_active]
        return active[skip : skip + limit]


class MockConstraintRepository(BaseConstraintRepository):
    def __init__(self) -> None:
        self._data: dict[str, Constraint] = {}

    async def create(self, constraint: Constraint) -> Constraint:
        if constraint.id is None:
            constraint.id = PydanticObjectId()
        self._data[str(constraint.id)] = constraint
        return constraint

    async def get_by_id(self, constraint_id: str) -> Constraint | None:
        return self._data.get(constraint_id)

    async def get_active(self) -> list[Constraint]:
        return [c for c in self._data.values() if c.is_active]

    async def get_by_type(self, constraint_type: ConstraintType) -> list[Constraint]:
        return [
            c for c in self._data.values() if c.type == constraint_type and c.is_active
        ]

    async def get_by_role_id(self, role_id: str) -> list[Constraint]:
        result = []
        for c in self._data.values():
            if not c.is_active:
                continue
            if c.config.role_id and str(c.config.role_id) == role_id:
                result.append(c)
            elif c.config.role_ids:
                for rid in c.config.role_ids:
                    if str(rid) == role_id:
                        result.append(c)
                        break
        return result

    async def update(self, constraint: Constraint) -> Constraint:
        constraint.updated_at = time.time()
        self._data[str(constraint.id)] = constraint
        return constraint

    async def deactivate(self, constraint_id: str) -> bool:
        if constraint_id in self._data:
            self._data[constraint_id].is_active = False
            return True
        return False


class MockUserRepository(BaseUserRepository):
    def __init__(self) -> None:
        self._data: dict[str, User] = {}

    async def create(self, user: User) -> User:
        if user.id is None:
            user.id = PydanticObjectId()
        self._data[str(user.id)] = user
        return user

    async def get_by_id(self, user_id: str) -> User | None:
        return self._data.get(user_id)

    async def get_by_external_id(self, external_id: str) -> User | None:
        for user in self._data.values():
            if user.external_id == external_id and user.is_active:
                return user
        return None

    async def get_by_email(self, email: str) -> User | None:
        for user in self._data.values():
            if user.email == email and user.is_active:
                return user
        return None

    async def update(self, user: User) -> User:
        user.updated_at = time.time()
        self._data[str(user.id)] = user
        return user

    async def deactivate(self, user_id: str) -> bool:
        if user_id in self._data:
            self._data[user_id].is_active = False
            return True
        return False

    async def reactivate(self, user_id: str) -> bool:
        if user_id in self._data:
            self._data[user_id].is_active = True
            return True
        return False

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[User]:
        active = [u for u in self._data.values() if u.is_active]
        return active[skip : skip + limit]


class MockGroupRepository(BaseGroupRepository):
    def __init__(self) -> None:
        self._data: dict[str, Group] = {}

    async def create(self, group: Group) -> Group:
        if group.id is None:
            group.id = PydanticObjectId()
        self._data[str(group.id)] = group
        return group

    async def get_by_id(self, group_id: str) -> Group | None:
        return self._data.get(group_id)

    async def get_by_name(self, name: str) -> Group | None:
        for group in self._data.values():
            if group.name == name and group.is_active:
                return group
        return None

    async def update(self, group: Group) -> Group:
        group.updated_at = time.time()
        self._data[str(group.id)] = group
        return group

    async def deactivate(self, group_id: str) -> bool:
        if group_id in self._data:
            self._data[group_id].is_active = False
            return True
        return False

    async def reactivate(self, group_id: str) -> bool:
        if group_id in self._data:
            self._data[group_id].is_active = True
            return True
        return False

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Group]:
        active = [g for g in self._data.values() if g.is_active]
        return active[skip : skip + limit]


class MockAccessLogRepository(BaseAccessLogRepository):
    def __init__(self) -> None:
        self._data: dict[str, AccessLog] = {}

    async def create(self, access_log: AccessLog) -> AccessLog:
        if access_log.id is None:
            access_log.id = PydanticObjectId()
        self._data[str(access_log.id)] = access_log
        return access_log

    async def get_by_user(
        self, user_id: str, skip: int = 0, limit: int = 100
    ) -> list[AccessLog]:
        return [al for al in self._data.values() if al.user_id == user_id][
            skip : skip + limit
        ]

    async def get_denials(self, skip: int = 0, limit: int = 100) -> list[AccessLog]:
        return [al for al in self._data.values() if not al.allowed][skip : skip + limit]

    async def get_by_resource(
        self, resource: str, action: str | None = None, skip: int = 0, limit: int = 100
    ) -> list[AccessLog]:
        result = []
        for al in self._data.values():
            if al.resource == resource:
                if action is None or al.action == action:
                    result.append(al)
        return result[skip : skip + limit]

    async def get_recent(self, skip: int = 0, limit: int = 100) -> list[AccessLog]:
        return list(self._data.values())[skip : skip + limit]
