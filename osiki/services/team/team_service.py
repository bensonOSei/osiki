"""The tenant-scoped team manager: business owners edit their own staff roles.

Every public method first requires the actor to manage the tenant, then applies
the write rules in a fixed order (see ``_check_grants`` and ``create_role``).
"""

import time
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from typing import Any, Literal

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.errors import DuplicateKeyError

from osiki.api.actor import Actor
from osiki.api.exceptions import ConflictError, NotFoundError
from osiki.decision.decide import effective_grants
from osiki.decision.models import EffectiveGrant, GrantEntry, RoleEntry, UserBundle
from osiki.decision.scope import scope_matches
from osiki.models.base import Scope
from osiki.models.permission import Permission
from osiki.models.role import Grant, Role
from osiki.models.user import User
from osiki.models.user_role import UserRole
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
from osiki.repositories.tenant_members.base_tenant_member_repository import (
    BaseTenantMemberRepository,
)
from osiki.repositories.tenant_team_locks.base_tenant_team_lock_repository import (
    BaseTenantTeamLockRepository,
)
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)
from osiki.repositories.users.base_user_repository import BaseUserRepository
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
    ConstraintViolated,
    EffectiveSource,
    EscalationRefused,
    GrantRef,
    LastManager,
    NotAssignable,
    NotManager,
    NotOffered,
    RoleInUse,
    TeamError,
    TeamMember,
    TeamRole,
    TeamRoleRef,
    Violation,
    ViolationKind,
)
from osiki.services.unit_of_work import Operation, UnitOfWork

_MANAGE = GrantEntry(permission="osiki.team:manage")
_MEMBER_PAGE = 100

DryRunOp = Literal[
    "create_role",
    "update_role",
    "assign_role",
    "add_member",
    "revoke_role",
    "remove_member",
]

# The refusals a dry run reports as violations rather than raising.
_VIOLATION_KINDS: dict[type[TeamError], ViolationKind] = {
    EscalationRefused: "escalation",
    NotAssignable: "not_assignable",
    NotOffered: "not_offered",
    ConstraintViolated: "constraint",
    LastManager: "last_manager",
}


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
        user_repo: BaseUserRepository,
        member_repo: BaseTenantMemberRepository,
        lock_repo: BaseTenantTeamLockRepository,
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
        self._user_repo = user_repo
        self._member_repo = member_repo
        self._lock_repo = lock_repo
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

    async def list_assignable_permissions(self) -> list[Permission]:
        """Permissions the role editor may offer: the ones a tenant role may hold."""
        await self.require_manager()
        found: list[Permission] = []
        skip = 0
        while page := await self._permission_repo.list_active(skip, _MEMBER_PAGE):
            found.extend(p for p in page if _assignable(p))
            skip += _MEMBER_PAGE
        return found

    async def _offered_templates(self) -> list[Role]:
        """Active project templates whose every grant is assignable or built-in."""
        offered: list[Role] = []
        for template in await self._role_repo.list_templates():
            permissions = [
                p
                for ancestor in await self._lineage(template)
                for p in await self._permissions_of(ancestor)
            ]
            if all(
                p is not None and (is_builtin(p) or (p.is_active and p.assignable))
                for p in permissions
            ):
                offered.append(template)
        return offered

    async def _lineage(self, role: Role) -> list[Role]:
        """The role then its ancestors; stops at a missing or inactive parent
        (the snapshot drops those too) or a cycle."""
        lineage = [role]
        seen = {role.id}
        parent_id = role.parent_role_id
        while parent_id is not None and parent_id not in seen:
            parent = await self._role_repo.get_by_id(str(parent_id))
            if parent is None or not parent.is_active:
                break
            lineage.append(parent)
            seen.add(parent_id)
            parent_id = parent.parent_role_id
        return lineage

    async def _permissions_of(self, role: Role) -> list[Permission | None]:
        return [
            await self._permission_repo.get_by_id(str(g.permission_id))
            for g in role.grants
        ]

    async def _render(
        self, roles: list[Role], *, include_inactive: bool = False
    ) -> list[TeamRole]:
        """Roles as the team sees them. Grants on inactive permissions are
        left out unless ``include_inactive``, which escalation checks use: a
        later reactivation would hand them out."""
        permission_ids = list(
            dict.fromkeys(str(g.permission_id) for r in roles for g in r.grants)
        )
        found = (
            await self._permission_repo.get_by_ids_any(permission_ids)
            if include_inactive
            else await self._permission_repo.get_by_ids(permission_ids)
        )
        permissions = {str(p.id): p.permission_string for p in found}
        conditions = {str(c.id): c.key for c in await self._condition_repo.get_all()}
        return [
            TeamRole(
                id=str(role.id),
                name=role.name,
                kind=_kind(role),
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

    async def _holders(
        self, role_id: str, session: AsyncClientSession | None = None
    ) -> int:
        """Live assignments of the role in this tenant, direct and via group.

        Expired assignments (``expires_at`` in the past) do not count.
        """
        now = time.time()
        direct = await self._user_role_repo.get_by_tenant(
            self._tenant_id, role_id, session=session
        )
        grouped = [
            gr
            for gr in await self._group_role_repo.get_groups_with_role(role_id)
            if gr.scope.tenant_id == self._tenant_id
        ]
        return sum(
            1 for a in [*direct, *grouped] if a.expires_at is None or a.expires_at > now
        )

    # -- role writes ---------------------------------------------------------

    async def _check_create_role(
        self,
        name: str,
        grants: list[GrantRef],
        copied_from: str | None,
        *,
        session: AsyncClientSession | None = None,
    ) -> tuple[Role, list[GrantEntry]]:
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
        return role, entries

    async def create_role(
        self, name: str, grants: list[GrantRef], copied_from: str | None
    ) -> TeamRole:
        async def operation(session: AsyncClientSession | None) -> Role:
            role, entries = await self._check_create_role(name, grants, copied_from)
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
            return role

        role = await self._uow.run(operation)
        return (await self._render([role]))[0]

    async def _check_update_role(
        self,
        role_id: str,
        name: str | None,
        grants: list[GrantRef] | None,
        *,
        session: AsyncClientSession | None = None,
    ) -> tuple[Role, dict[str, Any], bool]:
        """The role with every change applied (a copy), its audit state before,
        and whether anything changes."""
        held = await self._held_grants()
        role = await self._own_role(role_id)
        before = _audit_state(role.name, (await self._render([role]))[0].grants)
        if grants is None and (name is None or name == role.name):
            return role, before, False
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
        return role, before, True

    async def update_role(
        self, role_id: str, name: str | None, grants: list[GrantRef] | None
    ) -> TeamRole:
        async def operation(session: AsyncClientSession | None) -> TeamRole:
            role, before, changed = await self._check_update_role(role_id, name, grants)
            if not changed:
                return (await self._render([role]))[0]
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

        return await self._uow.run(operation)

    async def delete_role(self, role_id: str) -> None:
        async def operation(session: AsyncClientSession | None) -> None:
            await self.require_manager()
            role = await self._own_role(role_id)
            before = _audit_state(role.name, (await self._render([role]))[0].grants)
            if await self._holders(role_id, session) > 0:
                raise RoleInUse(role_id)
            # Free the name so the tenant can reuse it (the unique name index
            # also covers inactive roles).
            role.name = f"{role.name} #deleted-{role_id}"
            role.is_active = False
            await self._role_repo.update(role, session=session)
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

        await self._uow.run(operation)

    # -- members: reads --------------------------------------------------------

    async def list_members(self, skip: int = 0, limit: int = 100) -> list[TeamMember]:
        await self.require_manager()
        user_ids = await self._member_repo.members(self._tenant_id, skip, limit)
        assignments = await self._user_role_repo.get_by_tenant(self._tenant_id)
        return [await self._member(user_id, assignments) for user_id in user_ids]

    async def _member(
        self, user_id: str, assignments: list[UserRole] | None = None
    ) -> TeamMember:
        """A member with the live roles assigned to them directly in the tenant."""
        user = await self._user_repo.get_by_external_id(user_id)
        if user is None:
            return TeamMember(user_id=user_id, name=None, email=None, roles=[])
        if assignments is None:
            assignments = await self._user_role_repo.get_by_tenant(self._tenant_id)
        role_ids = list(
            dict.fromkeys(
                str(a.role_id)
                for a in assignments
                if a.user_id == user.id and _live(a, time.time())
            )
        )
        roles = await self._role_repo.get_by_ids(role_ids) if role_ids else []
        return TeamMember(
            user_id=user_id,
            name=user.name,
            email=user.email,
            roles=[
                TeamRoleRef(
                    id=str(r.id),
                    name=r.name,
                    kind=_kind(r),
                )
                for r in roles
            ],
        )

    async def effective(self, user_id: str) -> list[EffectiveSource]:
        """Each grant the member effectively holds in the tenant, per applying
        assignment, attributed to the role that carries it (a template's grants
        show the template; an inherited grant shows the ancestor)."""
        await self.require_manager()
        if not await self._member_repo.is_member(self._tenant_id, user_id):
            raise _member_not_found(user_id)
        bundle = await self._bundle_builder.build(user_id)
        if bundle is None or self._tenant_id not in bundle.tenants:
            return []
        snapshot = await self._snapshot_builder.build()
        roles = {
            **{r.id: r for r in bundle.roles},
            **{r.id: r for r in snapshot.roles},
        }
        scope = self._scope()
        now = time.time()
        sources: list[EffectiveSource] = []
        for assignment in bundle.assignments:
            if assignment.expires_at is not None and assignment.expires_at <= now:
                continue
            if not scope_matches(assignment.scope, scope):
                continue
            for role in _walk(roles, assignment.role_id):
                for grant in role.grants:
                    source = EffectiveSource(
                        permission=grant.permission,
                        condition=grant.condition,
                        role_id=role.id,
                        role_name=role.name,
                        via=assignment.via,
                    )
                    if source not in sources:
                        sources.append(source)
        return sources

    # -- members: writes -------------------------------------------------------

    async def add_member(
        self, user_id: str, *, name: str | None, email: str | None, role_id: str
    ) -> TeamMember:
        """Add ``user_id`` to the tenant with ``role_id``.

        Front-door contract: ``user_id`` must identify a user who consented to
        joining or authenticated, typically after accepting an invite. The
        engine returns that user's environment-wide name and email to the
        tenant's managers.
        """

        async def operation(session: AsyncClientSession | None) -> None:
            role, stale = await self._check_add_member(
                user_id, role_id, name=name, email=email, session=session
            )
            user = await self._existing_or_new_user(user_id, name, email, session)
            await self._member_repo.add(self._tenant_id, user_id, session=session)
            await self._assign(user, role, stale, session)
            await self._audit.record(
                self._actor,
                "member.add",
                "member",
                user_id,
                tenant_id=self._tenant_id,
                before=None,
                after=_member_state(user_id, [role.name]),
                session=session,
            )

        await self._team_write(operation)
        return await self._member(user_id)

    async def assign_role(self, user_id: str, role_id: str) -> TeamMember:
        async def operation(session: AsyncClientSession | None) -> None:
            user, role, stale = await self._check_assign_role(
                user_id, role_id, session=session
            )
            created = await self._assign(user, role, stale, session)
            await self._audit.record(
                self._actor,
                "assignment.create",
                "assignment",
                str(created.id),
                tenant_id=self._tenant_id,
                before=None,
                after=_assignment_state(user_id, role_id, role),
                session=session,
            )

        await self._team_write(operation)
        return await self._member(user_id)

    async def revoke_role(self, user_id: str, role_id: str) -> None:
        async def operation(session: AsyncClientSession | None) -> None:
            assignment, role = await self._check_revoke_role(
                user_id, role_id, session=session
            )
            await self._user_role_repo.revoke(str(assignment.id), session=session)
            await self._audit.record(
                self._actor,
                "assignment.revoke",
                "assignment",
                str(assignment.id),
                tenant_id=self._tenant_id,
                before=_assignment_state(user_id, role_id, role),
                after=None,
                session=session,
            )

        await self._team_write(operation)

    async def remove_member(self, user_id: str) -> None:
        async def operation(session: AsyncClientSession | None) -> None:
            assignments = await self._check_remove_member(user_id, session=session)
            for assignment in assignments:
                await self._user_role_repo.revoke(str(assignment.id), session=session)
            await self._member_repo.remove(self._tenant_id, user_id, session=session)
            roles = await self._role_repo.get_by_ids(
                list(dict.fromkeys(str(a.role_id) for a in assignments))
            )
            await self._audit.record(
                self._actor,
                "member.remove",
                "member",
                user_id,
                tenant_id=self._tenant_id,
                before=_member_state(user_id, [r.name for r in roles]),
                after=None,
                session=session,
            )

        await self._team_write(operation)

    async def _existing_or_new_user(
        self,
        user_id: str,
        name: str | None,
        email: str | None,
        session: AsyncClientSession | None,
    ) -> User:
        """The user, created with ``name`` and ``email`` only if missing.

        Users are environment-wide: one tenant's manager must never rewrite a
        profile another tenant may share, so an existing user is left as is.
        """
        user = await self._user_repo.get_by_external_id(user_id)
        if user is not None:
            return user
        try:
            return await self._user_repo.create(
                User(external_id=user_id, name=name, email=email), session=session
            )
        except DuplicateKeyError as exc:
            # A concurrent add created the same user first: use theirs.
            # Otherwise the email belongs to someone else.
            winner = await self._user_repo.get_by_external_id(user_id)
            if winner is None:
                raise _email_taken(email) from exc
            return winner

    async def _team_write(self, operation: Operation[None]) -> None:
        """Run a member write as one unit of work that first bumps the tenant's
        lock, so concurrent team writes in the tenant write-conflict and the
        loser re-runs every check (the last-manager guard included)."""
        # Refuse outsiders before creating anything for the tenant.
        await self.require_manager()
        await self._lock_repo.ensure(self._tenant_id)

        async def locked(session: AsyncClientSession | None) -> None:
            await self._lock_repo.bump(self._tenant_id, session=session)
            await operation(session)

        await self._uow.run(locked)

    async def _assign(
        self,
        user: User,
        role: Role,
        stale: UserRole | None,
        session: AsyncClientSession | None,
    ) -> UserRole:
        assert user.id is not None and role.id is not None
        if stale is not None:
            # An expired row still holds the unique (user, role, tenant) slot.
            await self._user_role_repo.revoke(str(stale.id), session=session)
        try:
            return await self._user_role_repo.create(
                UserRole(
                    user_id=user.id,
                    role_id=role.id,
                    scope=Scope(tenant_id=self._tenant_id),
                    assigned_by=f"{self._actor.type}:{self._actor.id}",
                ),
                session=session,
            )
        except DuplicateKeyError as exc:
            raise _already_assigned(user.external_id, str(role.id)) from exc

    # -- members: checks (shared by the writes and the dry run) -----------------

    async def _check_add_member(
        self,
        user_id: str,
        role_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
        session: AsyncClientSession | None = None,
    ) -> tuple[Role, UserRole | None]:
        """The user need not exist yet: the write upserts it."""
        held = await self._held_grants()
        user = await self._user_repo.get_by_external_id(user_id)
        # An existing user's profile is never changed, so their email is not
        # checked: only a user about to be created takes the given email.
        if user is None and email is not None:
            owner = await self._user_repo.get_by_email(email)
            if owner is not None and owner.external_id != user_id:
                raise _email_taken(email)
        return await self._check_assignment(held, role_id, user, session=session)

    async def _check_assign_role(
        self,
        user_id: str,
        role_id: str,
        *,
        session: AsyncClientSession | None = None,
    ) -> tuple[User, Role, UserRole | None]:
        held = await self._held_grants()
        user = await self._member_user(user_id, session)
        role, stale = await self._check_assignment(held, role_id, user, session=session)
        return user, role, stale

    async def _check_revoke_role(
        self,
        user_id: str,
        role_id: str,
        *,
        session: AsyncClientSession | None = None,
    ) -> tuple[UserRole, Role | None]:
        await self.require_manager()
        user = await self._member_user(user_id, session)
        assignment = (
            await self._user_role_repo.find_assignment(
                str(user.id), role_id, self._tenant_id, session=session
            )
            if PydanticObjectId.is_valid(role_id)
            else None
        )
        if assignment is None:
            raise NotFoundError(
                "Role assignment not found",
                details={"user_id": user_id, "role_id": role_id},
            )
        await self._ensure_manager_remains(without_assignment=(user_id, role_id))
        return assignment, await self._role_repo.get_by_id(role_id)

    async def _check_remove_member(
        self, user_id: str, *, session: AsyncClientSession | None = None
    ) -> list[UserRole]:
        """The member's assignments in this tenant, every one to revoke."""
        await self.require_manager()
        if not await self._member_repo.is_member(
            self._tenant_id, user_id, session=session
        ):
            raise _member_not_found(user_id)
        await self._ensure_manager_remains(without_member=user_id)
        user = await self._user_repo.get_by_external_id(user_id)
        if user is None:
            return []
        return [
            a
            for a in await self._user_role_repo.get_by_tenant(
                self._tenant_id, session=session
            )
            if a.user_id == user.id
        ]

    async def _check_assignment(
        self,
        held: list[EffectiveGrant],
        role_id: str,
        user: User | None,
        *,
        session: AsyncClientSession | None,
    ) -> tuple[Role, UserRole | None]:
        """The role to assign and any expired row holding its slot.

        Escalation covers every grant the role gives, built-ins included, so
        assigning Owner needs ``osiki.team:manage``: owners hand on management.
        ``user=None`` is a user who does not exist yet.
        """
        role = await self._assignable_role(role_id)
        self._ensure_escalation_free(held, await self._role_grants(role))
        stale: UserRole | None = None
        if user is not None:
            stale = await self._user_role_repo.find_assignment(
                str(user.id), role_id, self._tenant_id, session=session
            )
            if stale is not None and _live(stale, time.time()):
                raise _already_assigned(user.external_id, role_id)
        # A user who does not exist yet holds nothing: a fresh id stands in.
        result = await self._validator.validate(
            str(user.id) if user is not None else str(PydanticObjectId()),
            role_id,
            self._scope(),
            session=session,
        )
        if not result.valid:
            raise ConstraintViolated(result.constraint_name, result.reason)
        return role, stale

    async def _assignable_role(self, role_id: str) -> Role:
        """An active offered template or an active role of this tenant.

        Another tenant's role is not found: its existence must not leak.
        """
        role = (
            await self._role_repo.get_by_id(role_id)
            if PydanticObjectId.is_valid(role_id)
            else None
        )
        if (
            role is None
            or not role.is_active
            or (role.tenant_id is not None and role.tenant_id != self._tenant_id)
        ):
            raise NotFoundError("Role not found", details={"role_id": role_id})
        if role.tenant_id is None and role_id not in {
            str(t.id) for t in await self._offered_templates()
        }:
            raise NotOffered(role_id)
        return role

    async def _role_grants(self, role: Role) -> list[GrantEntry]:
        """Every grant assigning ``role`` gives, inherited ones included, and
        grants on inactive permissions too: reactivating one must not hand out
        what the assigner could not."""
        if role.tenant_id is not None:
            return (await self._render([role], include_inactive=True))[0].grants
        lineage = await self._lineage(role)
        dormant = [
            g
            for rendered in await self._render(lineage, include_inactive=True)
            for g in rendered.grants
        ]
        snapshot = await self._snapshot_builder.build()
        roles = {r.id: r for r in snapshot.roles}
        if str(role.id) not in roles:
            # Fail closed: never let escalation pass vacuously on a role the
            # snapshot lacks; render it and its ancestors from the repo.
            return dormant
        live = [g for r in _walk(roles, str(role.id)) for g in r.grants]
        return [*live, *(g for g in dormant if g not in live)]

    async def _member_user(
        self, user_id: str, session: AsyncClientSession | None
    ) -> User:
        user = await self._user_repo.get_by_external_id(user_id)
        if user is None or not await self._member_repo.is_member(
            self._tenant_id, user_id, session=session
        ):
            raise _member_not_found(user_id)
        return user

    async def _ensure_manager_remains(
        self,
        *,
        without_member: str | None = None,
        without_assignment: tuple[str, str] | None = None,
    ) -> None:
        """``LastManager`` unless some member would still effectively hold
        ``osiki.team:manage`` in the tenant after the change.

        The change is the removal of ``without_member`` or of the direct
        tenant-scoped assignment ``without_assignment`` (user id, role id).
        Effective means what decides access: direct or group, unexpired,
        scope matching the tenant, via the role and its ancestors.
        Run it after the tenant lock is taken, so a concurrent change
        has either committed (and is seen) or will conflict with this one.
        """
        snapshot = await self._snapshot_builder.build()
        scope = self._scope()
        now = time.time()
        skip = 0
        while True:
            page = await self._member_repo.members(self._tenant_id, skip, _MEMBER_PAGE)
            for member in page:
                if member == without_member:
                    continue
                bundle = await self._bundle_builder.build(member)
                if bundle is None:
                    continue
                if without_assignment is not None and without_assignment[0] == member:
                    bundle = _without_direct(bundle, without_assignment[1], scope)
                held = effective_grants(snapshot, bundle, scope, now)
                if any(covers(grant, _MANAGE) for grant in held):
                    return
            if len(page) < _MEMBER_PAGE:
                raise LastManager()
            skip += _MEMBER_PAGE

    # -- dry run ---------------------------------------------------------------

    async def validate(self, op: DryRunOp, **args: Any) -> list[Violation]:
        """Run ``op``'s checks without writing; its refusals become violations.

        Only the five rule refusals are reported; anything else (not a manager,
        not found, a taken name, bad input) raises as the real operation would.
        """
        checks: dict[DryRunOp, Callable[..., Awaitable[object]]] = {
            "create_role": self._check_create_role,
            "update_role": self._check_update_role,
            "assign_role": self._check_assign_role,
            "add_member": self._check_add_member,
            "revoke_role": self._check_revoke_role,
            "remove_member": self._check_remove_member,
        }
        try:
            await checks[op](**args)
        except tuple(_VIOLATION_KINDS) as exc:
            return [
                Violation(
                    kind=_VIOLATION_KINDS[type(exc)],
                    message=exc.message,
                    details=exc.details,
                )
            ]
        return []

    def _scope(self) -> dict[str, str]:
        return {"tenant_id": self._tenant_id}

    # -- rules ---------------------------------------------------------------

    async def _own_role(self, role_id: str) -> Role:
        role = (
            await self._role_repo.get_by_id(role_id)
            if PydanticObjectId.is_valid(role_id)
            else None
        )
        if role is None or role.tenant_id != self._tenant_id or not role.is_active:
            raise NotFoundError("Role not found", details={"role_id": role_id})
        # A copy: a refused write must not leak into the stored document.
        return role.model_copy(deep=True)

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


def _live(assignment: UserRole, now: float) -> bool:
    return assignment.expires_at is None or assignment.expires_at > now


def _kind(role: Role) -> Literal["template", "tenant", "project"]:
    if role.tenant_id is not None:
        return "tenant"
    return "template" if role.is_template else "project"


def _walk(roles: Mapping[str, RoleEntry], role_id: str) -> Iterator[RoleEntry]:
    """The role then its ancestors; stops at a missing role or a cycle."""
    visited: set[str] = set()
    current: str | None = role_id
    while current is not None and current not in visited:
        role = roles.get(current)
        if role is None:
            return
        visited.add(current)
        yield role
        current = role.parent_id


def _without_direct(
    bundle: UserBundle, role_id: str, scope: dict[str, str]
) -> UserBundle:
    """The bundle minus the direct assignment of ``role_id`` in ``scope``."""
    return bundle.model_copy(
        update={
            "assignments": [
                a
                for a in bundle.assignments
                if not (a.via == "direct" and a.role_id == role_id and a.scope == scope)
            ]
        }
    )


def _member_state(user_id: str, roles: list[str]) -> dict[str, Any]:
    return {"user_id": user_id, "roles": roles}


def _assignment_state(user_id: str, role_id: str, role: Role | None) -> dict[str, Any]:
    return {"user_id": user_id, "role_id": role_id, "role": role.name if role else None}


def _member_not_found(user_id: str) -> NotFoundError:
    return NotFoundError("Member not found", details={"user_id": user_id})


def _already_assigned(user_id: str, role_id: str) -> ConflictError:
    return ConflictError(
        "Role already assigned", details={"user_id": user_id, "role_id": role_id}
    )


def _email_taken(email: str | None) -> ConflictError:
    return ConflictError("Email already in use", details={"email": email or ""})
