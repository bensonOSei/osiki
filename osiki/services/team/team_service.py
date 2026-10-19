"""The tenant-scoped team manager: business owners edit their own staff roles.

Every public method first requires the actor to manage the tenant, then applies
the write rules in a fixed order (see ``_check_grants`` and ``create_role``).
"""

import time
from collections.abc import Sequence
from typing import Any

from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from osiki.api.actor import Actor
from osiki.api.exceptions import ConflictError, NotFoundError
from osiki.decision.decide import effective_grants
from osiki.decision.models import EffectiveGrant, GrantEntry
from osiki.models.permission import Permission
from osiki.models.role import Grant, Role
from osiki.repositories.conditions.base_condition_repository import (
    BaseConditionRepository,
)
from osiki.repositories.group_roles.base_group_role_repository import (
    BaseGroupRoleRepository,
)
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)
from osiki.services.audit.audit_writer import AuditWriter
from osiki.services.builtins import is_builtin
from osiki.services.bundle_builder.bundle_builder import BundleBuilder
from osiki.services.constraint_validator.base_constraint_validator import (
    BaseConstraintValidator,
)
from osiki.services.roles.validation import validate_references
from osiki.services.snapshot_builder.snapshot_builder import SnapshotBuilder
from osiki.services.team.escalation import covers, uncovered
from osiki.services.team.models import (
    EscalationRefused,
    GrantRef,
    NotAssignable,
    NotManager,
    NotOffered,
    RoleInUse,
    TeamRole,
)
from osiki.services.unit_of_work import UnitOfWork

_MANAGE = GrantEntry(permission="osiki.team:manage")


def _audit_state(name: str, grants: Sequence[GrantEntry]) -> dict[str, Any]:
    return {
        "name": name,
        "permissions": [
            g.permission if g.condition is None else f"{g.permission}@{g.condition}"
            for g in grants
        ],
    }


class TeamService:
    def __init__(
        self,
        environment_id: str,
        tenant_id: str,
        actor: Actor,
        *,
        role_repo: BaseRoleRepository,
        permission_repo: BasePermissionRepository,
        condition_repo: BaseConditionRepository,
        user_role_repo: BaseUserRoleRepository,
        group_role_repo: BaseGroupRoleRepository,
        snapshot_builder: SnapshotBuilder,
        bundle_builder: BundleBuilder,
        validator: BaseConstraintValidator,
        uow: UnitOfWork,
        audit: AuditWriter,
    ) -> None:
        self._environment_id = environment_id
        self._tenant_id = tenant_id
        self._actor = actor
        self._role_repo = role_repo
        self._permission_repo = permission_repo
        self._condition_repo = condition_repo
        self._user_role_repo = user_role_repo
        self._group_role_repo = group_role_repo
        self._snapshot_builder = snapshot_builder
        self._bundle_builder = bundle_builder
        self._validator = validator
        self._uow = uow
        self._audit = audit

    # -- authorization -----------------------------------------------------

    async def _held_grants(self) -> list[EffectiveGrant]:
        """The actor's effective grants in this tenant; ``NotManager`` unless
        a tenant_user holds ``osiki.team:manage``. A developer always passes."""
        if self._actor.type == "developer":
            return []
        bundle = await self._bundle_builder.build(self._actor.id)
        if bundle is None:
            raise NotManager()
        held = effective_grants(
            await self._snapshot_builder.build(),
            bundle,
            {"tenant_id": self._tenant_id},
            time.time(),
        )
        if not any(covers(grant, _MANAGE) for grant in held):
            raise NotManager()
        return held

    async def require_manager(self) -> None:
        await self._held_grants()

    # -- reads ---------------------------------------------------------------

    async def list_roles(self) -> list[TeamRole]:
        await self.require_manager()
        offered = await self._offered_templates()
        own = await self._role_repo.list_tenant(self._tenant_id)
        return await self._render([*offered, *own])

    async def _offered_templates(self) -> list[Role]:
        """Active project templates whose every grant is assignable or built-in."""
        offered: list[Role] = []
        for template in await self._role_repo.list_templates():
            permissions = await self._permissions_of(template)
            if all(
                p is not None and (p.assignable or is_builtin(p)) for p in permissions
            ):
                offered.append(template)
        return offered

    async def _permissions_of(self, role: Role) -> list[Permission | None]:
        return [
            await self._permission_repo.get_by_id(str(g.permission_id))
            for g in role.grants
        ]

    async def _render(self, roles: list[Role]) -> list[TeamRole]:
        permission_ids = list(
            dict.fromkeys(str(g.permission_id) for r in roles for g in r.grants)
        )
        permissions = {
            str(p.id): p.permission_string
            for p in await self._permission_repo.get_by_ids(permission_ids)
        }
        conditions = {str(c.id): c.key for c in await self._condition_repo.get_all()}
        return [
            TeamRole(
                id=str(role.id),
                name=role.name,
                kind="template" if role.tenant_id is None else "tenant",
                grants=[
                    GrantEntry(
                        permission=permissions[str(g.permission_id)],
                        condition=(
                            conditions[str(g.condition_id)] if g.condition_id else None
                        ),
                    )
                    for g in role.grants
                    if str(g.permission_id) in permissions
                ],
                copied_from=str(role.copied_from) if role.copied_from else None,
                holders=await self._holders(str(role.id)),
            )
            for role in roles
        ]

    async def _holders(self, role_id: str) -> int:
        """Active assignments of the role in this tenant, direct and via group."""
        direct = await self._user_role_repo.get_by_tenant(self._tenant_id, role_id)
        grouped = [
            gr
            for gr in await self._group_role_repo.get_groups_with_role(role_id)
            if gr.scope.tenant_id == self._tenant_id
        ]
        return len(direct) + len(grouped)

    # -- writes --------------------------------------------------------------

    async def create_role(
        self, name: str, grants: list[GrantRef], copied_from: str | None
    ) -> TeamRole:
        held = await self._held_grants()
        entries, unique = await self._check_grants(grants)
        if copied_from is not None:
            offered = {str(t.id) for t in await self._offered_templates()}
            if copied_from not in offered:
                raise NotOffered(copied_from)
        self._ensure_escalation_free(held, entries)
        await self._ensure_name_free(name, None)
        role = Role(
            name=name,
            grants=_to_grants(unique),
            tenant_id=self._tenant_id,
            parent_role_id=None,
            copied_from=PydanticObjectId(copied_from) if copied_from else None,
        )
        async with self._uow.transaction() as session:
            try:
                role = await self._role_repo.create(role, session=session)
            except DuplicateKeyError as exc:
                raise _name_taken(name) from exc
            await self._audit.record(
                self._actor,
                "role.create",
                "role",
                str(role.id),
                tenant_id=self._tenant_id,
                before=None,
                after=_audit_state(name, entries),
                session=session,
            )
        return (await self._render([role]))[0]

    async def update_role(
        self, role_id: str, name: str | None, grants: list[GrantRef] | None
    ) -> TeamRole:
        held = await self._held_grants()
        role = await self._own_role(role_id)
        before = _audit_state(role.name, (await self._render([role]))[0].grants)
        new_grants: list[Grant] | None = None
        if grants is not None:
            entries, unique = await self._check_grants(grants)
            self._ensure_escalation_free(held, entries)
            new_grants = _to_grants(unique)
        if name is not None and name != role.name:
            await self._ensure_name_free(name, role_id)
        # Mutate only once every rule has passed.
        if new_grants is not None:
            role.grants = new_grants
        if name is not None:
            role.name = name
        async with self._uow.transaction() as session:
            try:
                role = await self._role_repo.update(role, session=session)
            except DuplicateKeyError as exc:
                raise _name_taken(role.name) from exc
            rendered = (await self._render([role]))[0]
            await self._audit.record(
                self._actor,
                "role.update",
                "role",
                role_id,
                tenant_id=self._tenant_id,
                before=before,
                after=_audit_state(rendered.name, rendered.grants),
                session=session,
            )
        return rendered

    async def delete_role(self, role_id: str) -> None:
        await self.require_manager()
        role = await self._own_role(role_id)
        if await self._holders(role_id) > 0:
            raise RoleInUse(role_id)
        before = _audit_state(role.name, (await self._render([role]))[0].grants)
        async with self._uow.transaction() as session:
            await self._role_repo.deactivate(role_id, session=session)
            await self._audit.record(
                self._actor,
                "role.delete",
                "role",
                role_id,
                tenant_id=self._tenant_id,
                before=before,
                after=None,
                session=session,
            )

    # -- rules ---------------------------------------------------------------

    async def _own_role(self, role_id: str) -> Role:
        role = (
            await self._role_repo.get_by_id(role_id)
            if PydanticObjectId.is_valid(role_id)
            else None
        )
        if role is None or role.tenant_id != self._tenant_id or not role.is_active:
            raise NotFoundError("Role not found", details={"role_id": role_id})
        return role

    async def _check_grants(
        self, grants: list[GrantRef]
    ) -> tuple[list[GrantEntry], list[GrantRef]]:
        """Rules 2 and 3, before anything reaches the escalation module.

        Returns the wanted grants (permission string plus condition key) and the
        deduplicated refs they came from.
        """
        unique = list(dict.fromkeys(grants))
        await validate_references(
            unique,
            None,
            self._role_repo,
            self._permission_repo,
            self._condition_repo,
        )
        entries: list[GrantEntry] = []
        refused: list[str] = []
        for ref in unique:
            permission = await self._permission_repo.get_by_id(ref.permission_id)
            assert permission is not None  # validate_references found it
            if not _assignable(permission):
                if permission.permission_string not in refused:
                    refused.append(permission.permission_string)
            condition_key = None
            if ref.condition_id is not None:
                condition = await self._condition_repo.get_by_id(ref.condition_id)
                assert condition is not None  # validate_references found it
                condition_key = condition.key
            entries.append(
                GrantEntry(
                    permission=permission.permission_string, condition=condition_key
                )
            )
        if refused:
            raise NotAssignable(refused)
        return entries, unique

    def _ensure_escalation_free(
        self, held: list[EffectiveGrant], entries: list[GrantEntry]
    ) -> None:
        if self._actor.type == "developer":
            return
        missing = uncovered(held, entries)
        if missing:
            raise EscalationRefused(missing)

    async def _ensure_name_free(self, name: str, own_id: str | None) -> None:
        existing = await self._role_repo.get_by_name(name, self._tenant_id)
        if existing is not None and str(existing.id) != own_id:
            raise _name_taken(name)


def _assignable(permission: Permission) -> bool:
    """Active, flagged assignable, not built-in, and not a ``*`` resource.

    A ``*`` resource (``*:*``, ``*:manage``) would match ``osiki.team:manage``
    at decision time, so it can never go into a tenant role.
    """
    return (
        permission.is_active
        and permission.assignable
        and not is_builtin(permission)
        and permission.resource != "*"
    )


def _name_taken(name: str) -> ConflictError:
    return ConflictError("Role with this name already exists", details={"name": name})


def _to_grants(refs: list[GrantRef]) -> list[Grant]:
    return [
        Grant(
            permission_id=PydanticObjectId(r.permission_id),
            condition_id=PydanticObjectId(r.condition_id) if r.condition_id else None,
        )
        for r in refs
    ]
