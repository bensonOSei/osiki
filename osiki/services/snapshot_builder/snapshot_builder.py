"""Render an environment's authorization config into a cached ``Snapshot``."""

from loguru import logger

from osiki.decision.models import (
    ConstraintEntry,
    GrantEntry,
    RoleEntry,
    Snapshot,
)
from osiki.models.role import Grant, Role
from osiki.repositories.conditions.base_condition_repository import (
    BaseConditionRepository,
)
from osiki.repositories.constraints.base_constraint_repository import (
    BaseConstraintRepository,
)
from osiki.repositories.endpoints.base_endpoint_repository import (
    BaseEndpointRepository,
)
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository

MISSING_CONDITION_PREFIX = "missing:"


class SnapshotCache:
    """The latest built snapshot per environment.

    One instance is shared by the whole process (see
    ``osiki.api.dependencies.get_snapshot_cache``); tests build their own.
    """

    def __init__(self) -> None:
        self._snapshots: dict[str, Snapshot] = {}

    def get(self, environment_id: str) -> Snapshot | None:
        return self._snapshots.get(environment_id)

    def put(self, snapshot: Snapshot) -> None:
        self._snapshots[snapshot.environment_id] = snapshot


class SnapshotBuilder:
    """Build (or reuse) the snapshot of one environment's config.

    The cached snapshot is reused while its ``version`` equals the stored
    config version. The version is read BEFORE the config, and writers bump it
    AFTER writing, so a snapshot can only be tagged with a version older than
    or equal to its content: a concurrent write always forces a rebuild and
    never leaves stale content behind a current version.

    Deny-safe rendering: inactive roles, permissions and conditions are left
    out. A grant whose permission is inactive or missing is dropped. A grant
    whose condition is inactive keeps that condition's key (absent from
    ``Snapshot.conditions``, so ``decide`` skips it and denies); a grant whose
    condition document is missing gets ``"missing:<condition_id>"``, which no
    real key can equal. A conditional grant is never rendered unconditional.
    """

    def __init__(
        self,
        environment_id: str,
        state_repo: BaseEnvironmentStateRepository,
        role_repo: BaseRoleRepository,
        permission_repo: BasePermissionRepository,
        condition_repo: BaseConditionRepository,
        constraint_repo: BaseConstraintRepository,
        endpoint_repo: BaseEndpointRepository,
        *,
        cache: SnapshotCache,
    ) -> None:
        self._environment_id = environment_id
        self._state_repo = state_repo
        self._role_repo = role_repo
        self._permission_repo = permission_repo
        self._condition_repo = condition_repo
        self._constraint_repo = constraint_repo
        self._endpoint_repo = endpoint_repo
        self._cache = cache

    async def build(self) -> Snapshot:
        version = await self._state_repo.get_config_version()
        cached = self._cache.get(self._environment_id)
        if cached is not None and cached.version == version:
            return cached
        snapshot = await self._render(version)
        self._cache.put(snapshot)
        logger.debug(
            "Snapshot built",
            environment_id=self._environment_id,
            version=version,
            roles=len(snapshot.roles),
        )
        return snapshot

    async def _render(self, version: int) -> Snapshot:
        # Tenant-owned roles never reach the snapshot: they are not project
        # config, and SDK consumers enforce only project roles.
        roles = [
            r
            for r in await self._role_repo.get_all_active()
            if r.is_active and r.tenant_id is None
        ]
        conditions = await self._condition_repo.get_all()
        permission_ids = list(
            dict.fromkeys(str(g.permission_id) for r in roles for g in r.grants)
        )
        permissions = {
            str(p.id): p.permission_string
            for p in await self._permission_repo.get_by_ids(permission_ids)
            if p.is_active
        }
        condition_keys = {str(c.id): c.key for c in conditions}
        constraints = await self._constraint_repo.get_active()
        settings = await self._state_repo.get_settings()
        mappings = sorted(
            await self._endpoint_repo.list_mappings(),
            key=lambda m: (m.path, m.method),
        )
        return Snapshot(
            environment_id=self._environment_id,
            version=version,
            roles=[_role_entry(r, permissions, condition_keys) for r in roles],
            conditions={c.key: c.expression for c in conditions if c.is_active},
            constraints=[
                ConstraintEntry(
                    id=str(c.id),
                    name=c.name,
                    type=c.type.value,
                    config=c.config.model_dump(mode="json", exclude_none=True),
                )
                for c in constraints
                if c.is_active
            ],
            endpoints=[m.to_entry() for m in mappings],
            settings=settings,
        )


def _role_entry(
    role: Role, permissions: dict[str, str], condition_keys: dict[str, str]
) -> RoleEntry:
    return RoleEntry(
        id=str(role.id),
        name=role.name,
        parent_id=str(role.parent_role_id) if role.parent_role_id else None,
        grants=[
            GrantEntry(
                permission=permissions[str(g.permission_id)],
                condition=_condition_key(g, condition_keys),
            )
            for g in role.grants
            if str(g.permission_id) in permissions
        ],
    )


def _condition_key(grant: Grant, condition_keys: dict[str, str]) -> str | None:
    if grant.condition_id is None:
        return None
    condition_id = str(grant.condition_id)
    return condition_keys.get(condition_id, f"{MISSING_CONDITION_PREFIX}{condition_id}")
