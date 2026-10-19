import time

from beanie import PydanticObjectId

from osiki.decision.models import EnvironmentSettings
from osiki.models.access_log import AccessLog
from osiki.models.base import AttributeValue, EnvironmentMixin
from osiki.models.condition import Condition
from osiki.models.constraint import Constraint, ConstraintType
from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.permission import Permission
from osiki.models.role import Grant, Role
from osiki.models.tenant import Tenant
from osiki.models.tenant_member import TenantMember
from osiki.models.user import User
from osiki.models.user_group import UserGroup
from osiki.models.user_role import UserRole
from osiki.repositories.access_logs.base_access_log_repository import (
    BaseAccessLogRepository,
)
from osiki.repositories.conditions.base_condition_repository import (
    BaseConditionRepository,
)
from osiki.repositories.constraints.base_constraint_repository import (
    BaseConstraintRepository,
)
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)
from osiki.repositories.group_roles.base_group_role_repository import (
    BaseGroupRoleRepository,
)
from osiki.repositories.groups.base_group_repository import BaseGroupRepository
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository
from osiki.repositories.tenant_members.base_tenant_member_repository import (
    BaseTenantMemberRepository,
)
from osiki.repositories.tenants.base_tenant_repository import BaseTenantRepository
from osiki.repositories.user_groups.base_user_group_repository import (
    BaseUserGroupRepository,
)
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)
from osiki.repositories.users.base_user_repository import BaseUserRepository


class _EnvironmentBound[T: EnvironmentMixin]:
    """In-memory store whose reads and writes are scoped to one environment."""

    def __init__(self, environment_id: str) -> None:
        self.environment_id = environment_id
        self._data: dict[str, T] = {}

    def _scoped(self) -> list[T]:
        return [
            d for d in self._data.values() if d.environment_id == self.environment_id
        ]

    def _get(self, key: str) -> T | None:
        doc = self._data.get(key)
        if doc is None or doc.environment_id != self.environment_id:
            return None
        return doc

    def _store(self, key: str, doc: T) -> T:
        doc.environment_id = self.environment_id
        self._data[key] = doc
        return doc


class _ConfigBound[T: EnvironmentMixin](_EnvironmentBound[T]):
    """A config store that bumps the environment's config version on writes."""

    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        super().__init__(environment_id)
        self._state = state

    async def _bump(self) -> None:
        await self._state.bump_config_version()


class _AssignmentBound[T: EnvironmentMixin](_EnvironmentBound[T]):
    """A store whose writes bump the environment's assignments version."""

    def __init__(
        self, environment_id: str, state: BaseEnvironmentStateRepository
    ) -> None:
        super().__init__(environment_id)
        self._state = state

    async def _bump(self) -> None:
        await self._state.bump_assignments_version()


class MockEnvironmentStateRepository(BaseEnvironmentStateRepository):
    def __init__(self, environment_id: str) -> None:
        self.environment_id = environment_id
        self._version = 0
        self._assignments_version = 0
        self.settings = EnvironmentSettings()

    async def get_config_version(self) -> int:
        return self._version

    async def bump_config_version(self) -> int:
        self._version += 1
        return self._version

    async def get_assignments_version(self) -> int:
        return self._assignments_version

    async def bump_assignments_version(self) -> int:
        self._assignments_version += 1
        return self._assignments_version

    async def get_settings(self) -> EnvironmentSettings:
        return self.settings


def _grant(permission_id: str, condition_id: str | None) -> Grant:
    return Grant(
        permission_id=PydanticObjectId(permission_id),
        condition_id=PydanticObjectId(condition_id) if condition_id else None,
    )


class MockUserRoleRepository(_AssignmentBound[UserRole], BaseUserRoleRepository):
    async def create(self, user_role: UserRole) -> UserRole:
        if user_role.id is None:
            user_role.id = PydanticObjectId()
        self._store(str(user_role.id), user_role)
        await self._bump()
        return user_role

    async def get_by_id(self, user_role_id: str) -> UserRole | None:
        return self._get(user_role_id)

    async def get_user_roles(self, user_id: str) -> list[UserRole]:
        return [
            ur for ur in self._scoped() if str(ur.user_id) == user_id and ur.is_active
        ]

    async def get_users_with_role(self, role_id: str) -> list[UserRole]:
        return [
            ur for ur in self._scoped() if str(ur.role_id) == role_id and ur.is_active
        ]

    async def get_by_tenant(
        self, tenant_id: str, role_id: str | None = None
    ) -> list[UserRole]:
        result = []
        for ur in self._scoped():
            if ur.scope.tenant_id == tenant_id and ur.is_active:
                if role_id is None or str(ur.role_id) == role_id:
                    result.append(ur)
        return result

    async def find_assignment(
        self, user_id: str, role_id: str, tenant_id: str | None = None
    ) -> UserRole | None:
        for ur in self._scoped():
            if (
                str(ur.user_id) == user_id
                and str(ur.role_id) == role_id
                and ur.is_active
            ):
                if ur.scope.tenant_id == tenant_id:
                    return ur
        return None

    async def revoke(self, user_role_id: str) -> bool:
        if self._get(user_role_id) is not None:
            self._data[user_role_id].is_active = False
            await self._bump()
            return True
        return False

    async def get_expired(self, current_time: float) -> list[UserRole]:
        return [
            ur
            for ur in self._scoped()
            if ur.is_active
            and ur.expires_at is not None
            and ur.expires_at <= current_time
        ]


class MockUserGroupRepository(_AssignmentBound[UserGroup], BaseUserGroupRepository):
    async def create(self, user_group: UserGroup) -> UserGroup:
        if user_group.id is None:
            user_group.id = PydanticObjectId()
        self._store(str(user_group.id), user_group)
        await self._bump()
        return user_group

    async def get_by_id(self, user_group_id: str) -> UserGroup | None:
        return self._get(user_group_id)

    async def get_user_groups(self, user_id: str) -> list[UserGroup]:
        return [
            ug for ug in self._scoped() if str(ug.user_id) == user_id and ug.is_active
        ]

    async def get_group_members(self, group_id: str) -> list[UserGroup]:
        return [
            ug for ug in self._scoped() if str(ug.group_id) == group_id and ug.is_active
        ]

    async def find_membership(self, user_id: str, group_id: str) -> UserGroup | None:
        for ug in self._scoped():
            if (
                str(ug.user_id) == user_id
                and str(ug.group_id) == group_id
                and ug.is_active
            ):
                return ug
        return None

    async def remove(self, user_group_id: str) -> bool:
        if self._get(user_group_id) is not None:
            self._data[user_group_id].is_active = False
            await self._bump()
            return True
        return False


class MockGroupRoleRepository(_AssignmentBound[GroupRole], BaseGroupRoleRepository):
    async def create(self, group_role: GroupRole) -> GroupRole:
        if group_role.id is None:
            group_role.id = PydanticObjectId()
        self._store(str(group_role.id), group_role)
        await self._bump()
        return group_role

    async def get_by_id(self, group_role_id: str) -> GroupRole | None:
        return self._get(group_role_id)

    async def get_group_roles(self, group_id: str) -> list[GroupRole]:
        return [
            gr for gr in self._scoped() if str(gr.group_id) == group_id and gr.is_active
        ]

    async def get_roles_for_groups(self, group_ids: list[str]) -> list[GroupRole]:
        return [
            gr
            for gr in self._scoped()
            if str(gr.group_id) in group_ids and gr.is_active
        ]

    async def get_groups_with_role(self, role_id: str) -> list[GroupRole]:
        return [
            gr for gr in self._scoped() if str(gr.role_id) == role_id and gr.is_active
        ]

    async def find_assignment(
        self, group_id: str, role_id: str, tenant_id: str | None = None
    ) -> GroupRole | None:
        for gr in self._scoped():
            if (
                str(gr.group_id) == group_id
                and str(gr.role_id) == role_id
                and gr.is_active
            ):
                if gr.scope.tenant_id == tenant_id:
                    return gr
        return None

    async def revoke(self, group_role_id: str) -> bool:
        if self._get(group_role_id) is not None:
            self._data[group_role_id].is_active = False
            await self._bump()
            return True
        return False

    async def get_expired(self, current_time: float) -> list[GroupRole]:
        return [
            gr
            for gr in self._scoped()
            if gr.is_active
            and gr.expires_at is not None
            and gr.expires_at <= current_time
        ]


class MockRoleRepository(_ConfigBound[Role], BaseRoleRepository):
    async def create(self, role: Role) -> Role:
        if role.id is None:
            role.id = PydanticObjectId()
        self._store(str(role.id), role)
        await self._bump()
        return role

    async def get_by_id(self, role_id: str) -> Role | None:
        return self._get(role_id)

    async def get_by_name(self, name: str) -> Role | None:
        for role in self._scoped():
            if role.name == name and role.is_active:
                return role
        return None

    async def get_by_ids(self, role_ids: list[str]) -> list[Role]:
        return [
            r for rid in role_ids if (r := self._get(rid)) is not None and r.is_active
        ]

    async def get_all_active(self) -> list[Role]:
        return [r for r in self._scoped() if r.is_active]

    async def get_children(self, parent_role_id: str) -> list[Role]:
        return [
            role
            for role in self._scoped()
            if role.parent_role_id and str(role.parent_role_id) == parent_role_id
        ]

    async def update(self, role: Role) -> Role:
        role.updated_at = time.time()
        self._data[str(role.id)] = role
        await self._bump()
        return role

    async def deactivate(self, role_id: str) -> bool:
        role = self._get(role_id)
        if role is None or role.is_system:
            return False
        role.is_active = False
        await self._bump()
        return True

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Role]:
        active = [r for r in self._scoped() if r.is_active]
        return active[skip : skip + limit]

    async def add_permission(
        self, role_id: str, permission_id: str, condition_id: str | None = None
    ) -> bool:
        role = self._get(role_id)
        if role is None:
            return False
        grant = _grant(permission_id, condition_id)
        if grant not in role.grants:
            role.grants.append(grant)
        await self._bump()
        return True

    async def remove_permission(
        self, role_id: str, permission_id: str, condition_id: str | None = None
    ) -> bool:
        role = self._get(role_id)
        if role is None:
            return False
        grant = _grant(permission_id, condition_id)
        if grant in role.grants:
            role.grants.remove(grant)
        await self._bump()
        return True

    async def is_condition_in_use(self, condition_id: str) -> bool:
        return any(
            g.condition_id is not None and str(g.condition_id) == condition_id
            for role in self._scoped()
            if role.is_active
            for g in role.grants
        )


class MockPermissionRepository(_ConfigBound[Permission], BasePermissionRepository):
    async def create(self, permission: Permission) -> Permission:
        if permission.id is None:
            permission.id = PydanticObjectId()
        self._store(str(permission.id), permission)
        await self._bump()
        return permission

    async def get_by_id(self, permission_id: str) -> Permission | None:
        return self._get(permission_id)

    async def get_by_ids(self, permission_ids: list[str]) -> list[Permission]:
        return [
            p
            for pid in permission_ids
            if (p := self._get(pid)) is not None and p.is_active
        ]

    async def get_by_resource_action(
        self, resource: str, action: str
    ) -> Permission | None:
        for perm in self._scoped():
            if perm.resource == resource and perm.action == action and perm.is_active:
                return perm
        return None

    async def get_by_resource(self, resource: str) -> list[Permission]:
        return [p for p in self._scoped() if p.resource == resource and p.is_active]

    async def deactivate(self, permission_id: str) -> bool:
        if self._get(permission_id) is not None:
            self._data[permission_id].is_active = False
            await self._bump()
            return True
        return False

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Permission]:
        active = [p for p in self._scoped() if p.is_active]
        return active[skip : skip + limit]


class MockConstraintRepository(_ConfigBound[Constraint], BaseConstraintRepository):
    async def create(self, constraint: Constraint) -> Constraint:
        if constraint.id is None:
            constraint.id = PydanticObjectId()
        self._store(str(constraint.id), constraint)
        await self._bump()
        return constraint

    async def get_by_id(self, constraint_id: str) -> Constraint | None:
        return self._get(constraint_id)

    async def get_active(self) -> list[Constraint]:
        return [c for c in self._scoped() if c.is_active]

    async def get_by_type(self, constraint_type: ConstraintType) -> list[Constraint]:
        return [c for c in self._scoped() if c.type == constraint_type and c.is_active]

    async def get_by_role_id(self, role_id: str) -> list[Constraint]:
        result = []
        for c in self._scoped():
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
        await self._bump()
        return constraint

    async def deactivate(self, constraint_id: str) -> bool:
        if self._get(constraint_id) is not None:
            self._data[constraint_id].is_active = False
            await self._bump()
            return True
        return False


class MockUserRepository(_AssignmentBound[User], BaseUserRepository):
    async def create(self, user: User) -> User:
        if user.id is None:
            user.id = PydanticObjectId()
        self._store(str(user.id), user)
        await self._bump()
        return user

    async def get_by_id(self, user_id: str) -> User | None:
        return self._get(user_id)

    async def get_by_external_id(self, external_id: str) -> User | None:
        for user in self._scoped():
            if user.external_id == external_id and user.is_active:
                return user
        return None

    async def get_by_email(self, email: str) -> User | None:
        for user in self._scoped():
            if user.email == email and user.is_active:
                return user
        return None

    async def update(self, user: User) -> User:
        user.updated_at = time.time()
        self._data[str(user.id)] = user
        await self._bump()
        return user

    async def deactivate(self, user_id: str) -> bool:
        if self._get(user_id) is not None:
            self._data[user_id].is_active = False
            await self._bump()
            return True
        return False

    async def reactivate(self, user_id: str) -> bool:
        if self._get(user_id) is not None:
            self._data[user_id].is_active = True
            await self._bump()
            return True
        return False

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[User]:
        active = [u for u in self._scoped() if u.is_active]
        return active[skip : skip + limit]

    async def upsert_by_external_id(
        self,
        external_id: str,
        name: str | None,
        email: str | None,
        attributes: dict[str, AttributeValue] | None,
    ) -> User:
        for user in self._scoped():
            if user.external_id == external_id:
                if name is not None:
                    user.name = name
                if email is not None:
                    user.email = email
                if attributes is not None:
                    user.attributes = attributes
                user.updated_at = time.time()
                await self._bump()
                return user
        return await self.create(
            User(
                external_id=external_id,
                name=name,
                email=email,
                attributes=attributes or {},
            )
        )


class MockTenantRepository(_AssignmentBound[Tenant], BaseTenantRepository):
    async def upsert(
        self, external_id: str, name: str, attributes: dict[str, AttributeValue]
    ) -> Tenant:
        for tenant in self._scoped():
            if tenant.external_id == external_id:
                tenant.name = name
                tenant.attributes = attributes
                tenant.updated_at = time.time()
                await self._bump()
                return tenant
        tenant = Tenant(external_id=external_id, name=name, attributes=attributes)
        tenant.id = PydanticObjectId()
        self._store(str(tenant.id), tenant)
        await self._bump()
        return tenant

    async def get_by_external_id(self, external_id: str) -> Tenant | None:
        for tenant in self._scoped():
            if tenant.external_id == external_id and tenant.is_active:
                return tenant
        return None

    async def get_many(self, external_ids: list[str]) -> list[Tenant]:
        return [
            t for t in self._scoped() if t.external_id in external_ids and t.is_active
        ]


class MockTenantMemberRepository(
    _AssignmentBound[TenantMember], BaseTenantMemberRepository
):
    def _key(self, tenant_id: str, user_id: str) -> str:
        return f"{tenant_id}\x00{user_id}"

    async def add(self, tenant_id: str, user_id: str) -> None:
        key = self._key(tenant_id, user_id)
        if self._get(key) is None:
            self._store(key, TenantMember(tenant_id=tenant_id, user_id=user_id))
            await self._bump()

    async def remove(self, tenant_id: str, user_id: str) -> bool:
        key = self._key(tenant_id, user_id)
        if self._get(key) is None:
            return False
        del self._data[key]
        await self._bump()
        return True

    async def is_member(self, tenant_id: str, user_id: str) -> bool:
        return self._get(self._key(tenant_id, user_id)) is not None

    async def tenants_for_user(self, user_id: str) -> list[str]:
        return [m.tenant_id for m in self._scoped() if m.user_id == user_id]

    async def members(self, tenant_id: str, skip: int, limit: int) -> list[str]:
        found = [m.user_id for m in self._scoped() if m.tenant_id == tenant_id]
        return found[skip : skip + limit]


class MockGroupRepository(_AssignmentBound[Group], BaseGroupRepository):
    async def create(self, group: Group) -> Group:
        if group.id is None:
            group.id = PydanticObjectId()
        self._store(str(group.id), group)
        await self._bump()
        return group

    async def get_by_id(self, group_id: str) -> Group | None:
        return self._get(group_id)

    async def get_by_ids(self, group_ids: list[str]) -> list[Group]:
        return [
            g for gid in group_ids if (g := self._get(gid)) is not None and g.is_active
        ]

    async def get_by_name(self, name: str) -> Group | None:
        for group in self._scoped():
            if group.name == name and group.is_active:
                return group
        return None

    async def update(self, group: Group) -> Group:
        group.updated_at = time.time()
        self._data[str(group.id)] = group
        return group

    async def deactivate(self, group_id: str) -> bool:
        if self._get(group_id) is not None:
            self._data[group_id].is_active = False
            await self._bump()
            return True
        return False

    async def reactivate(self, group_id: str) -> bool:
        if self._get(group_id) is not None:
            self._data[group_id].is_active = True
            await self._bump()
            return True
        return False

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Group]:
        active = [g for g in self._scoped() if g.is_active]
        return active[skip : skip + limit]


class MockAccessLogRepository(_EnvironmentBound[AccessLog], BaseAccessLogRepository):
    async def create(self, access_log: AccessLog) -> AccessLog:
        if access_log.id is None:
            access_log.id = PydanticObjectId()
        return self._store(str(access_log.id), access_log)

    async def create_many(self, logs: list[AccessLog]) -> int:
        for log in logs:
            await self.create(log)
        return len(logs)

    async def get_by_user(
        self, user_id: str, skip: int = 0, limit: int = 100
    ) -> list[AccessLog]:
        return [al for al in self._scoped() if al.user_id == user_id][
            skip : skip + limit
        ]

    async def get_denials(self, skip: int = 0, limit: int = 100) -> list[AccessLog]:
        return [al for al in self._scoped() if not al.allowed][skip : skip + limit]

    async def get_by_resource(
        self, resource: str, action: str | None = None, skip: int = 0, limit: int = 100
    ) -> list[AccessLog]:
        result = []
        for al in self._scoped():
            if al.resource == resource:
                if action is None or al.action == action:
                    result.append(al)
        return result[skip : skip + limit]

    async def get_recent(self, skip: int = 0, limit: int = 100) -> list[AccessLog]:
        return list(self._scoped())[skip : skip + limit]


class MockConditionRepository(_ConfigBound[Condition], BaseConditionRepository):
    async def create(self, condition: Condition) -> Condition:
        if condition.id is None:
            condition.id = PydanticObjectId()
        self._store(str(condition.id), condition)
        await self._bump()
        return condition

    async def get_by_id(self, condition_id: str) -> Condition | None:
        return self._get(condition_id)

    async def get_by_key(self, key: str) -> Condition | None:
        for c in self._scoped():
            if c.key == key:
                return c
        return None

    async def get_by_ids(self, ids: list[str]) -> list[Condition]:
        return [c for i in ids if (c := self._get(i)) is not None and c.is_active]

    async def get_all(self) -> list[Condition]:
        return self._scoped()

    async def update(self, condition: Condition) -> Condition:
        condition.updated_at = time.time()
        self._data[str(condition.id)] = condition
        await self._bump()
        return condition

    async def deactivate(self, condition_id: str) -> bool:
        condition = self._get(condition_id)
        if condition is None:
            return False
        condition.is_active = False
        await self._bump()
        return True

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Condition]:
        active = [c for c in self._scoped() if c.is_active]
        return active[skip : skip + limit]
