"""The authorization decision: ``decide``, ``effective_grants`` and ``list_filter``.

Pure and deterministic: the same snapshot, bundle and request always give the
same result. SDKs port this module; ``conformance/`` pins its behaviour.

Algorithm (``decide``):
    1. A request scope naming a ``tenant_id`` the user is not a member of
       (absent from ``bundle.tenants``) is denied ``not_tenant_member``.
    2. Assignments apply when unexpired (``expires_at`` is ``None`` or
       ``> now``) and their scope matches (``scope_matches``).
    3. Each applying assignment contributes its role's grants, then each
       ancestor's via ``parent_id``. The walk stops silently at a missing role
       or a repeated id, so a corrupted hierarchy can only grant less.
    4. A grant matches when its permission is, in specificity order,
       ``res:act``, ``res:*``, ``*:act`` or ``*:*``. Matches are ordered by
       specificity, then ``direct`` before ``group``, then encounter order
       (assignment order, then role before ancestors, then grant order).
    5. The first unconditional match allows.
    6. Otherwise conditional matches need a record (``record_required``);
       their conditions are evaluated in that order, skipping keys missing
       from the snapshot, and the first TRUE allows. None TRUE denies
       ``condition_failed``.
    7. No match denies ``no_permission``.
"""

from collections.abc import Iterator, Mapping
from typing import Any

from .models import (
    Decision,
    DecisionRequest,
    DenialReason,
    EffectiveGrant,
    FilterResult,
    RoleEntry,
    Snapshot,
    UserBundle,
)
from .rules import FilterNode, RuleContext, evaluate, residualize
from .scope import scope_matches

_VIA_RANK = {"direct": 0, "group": 1}


def effective_grants(
    snapshot: Snapshot, bundle: UserBundle, scope: Mapping[str, str], now: float
) -> list[EffectiveGrant]:
    """Grants the user holds in ``scope`` at ``now``, in encounter order.

    Exact duplicates are dropped (the first is kept). Empty when ``scope``
    names a tenant the user is not a member of.
    """
    if not _is_member(bundle, scope):
        return []
    roles = {role.id: role for role in snapshot.roles}
    grants: list[EffectiveGrant] = []
    seen: set[EffectiveGrant] = set()
    for assignment in bundle.assignments:
        if assignment.expires_at is not None and assignment.expires_at <= now:
            continue
        if not scope_matches(assignment.scope, scope):
            continue
        for role in _walk(roles, assignment.role_id):
            for grant in role.grants:
                entry = EffectiveGrant(
                    permission=grant.permission,
                    condition=grant.condition,
                    via=assignment.via,
                )
                if entry not in seen:
                    seen.add(entry)
                    grants.append(entry)
    return grants


def decide(
    snapshot: Snapshot, bundle: UserBundle, request: DecisionRequest
) -> Decision:
    """Decide whether the user may perform ``request``; see the module docstring."""
    if not _is_member(bundle, request.scope):
        return _deny("not_tenant_member")
    matches = _matching(
        effective_grants(snapshot, bundle, request.scope, request.now),
        request.resource,
        request.action,
    )
    for grant in matches:
        if grant.condition is None:
            return _allow(grant)
    if not matches:
        return _deny("no_permission")
    if request.record is None:
        return _deny("record_required")

    user, tenant = _rule_subjects(bundle, request.scope)
    ctx = RuleContext(record=request.record, user=user, tenant=tenant)
    for grant in matches:
        rule = snapshot.conditions.get(grant.condition or "")
        if rule is not None and evaluate(rule, ctx):
            return _allow(grant)
    return _deny("condition_failed")


def list_filter(
    snapshot: Snapshot,
    bundle: UserBundle,
    resource: str,
    action: str,
    scope: Mapping[str, str],
    now: float,
) -> FilterResult:
    """The records ``bundle``'s user may ``action`` on ``resource`` in ``scope``.

    ``all`` when an unconditional grant matches or a condition holds for
    every record; otherwise the OR of the matching conditions' residual
    filters (each distinct condition key once, in match order), or ``none``.
    """
    if not _is_member(bundle, scope):
        return FilterResult(mode="none")
    matches = _matching(
        effective_grants(snapshot, bundle, scope, now), resource, action
    )
    if any(grant.condition is None for grant in matches):
        return FilterResult(mode="all")

    user, tenant = _rule_subjects(bundle, scope)
    filters: list[FilterNode] = []
    keys = dict.fromkeys(grant.condition for grant in matches if grant.condition)
    for key in keys:
        rule = snapshot.conditions.get(key)
        if rule is None:
            continue
        residual = residualize(rule, user, tenant)
        if residual is True:
            return FilterResult(mode="all")
        if residual is not False:
            filters.append(residual)
    if not filters:
        return FilterResult(mode="none")
    tree = filters[0] if len(filters) == 1 else {"or": filters}
    return FilterResult(mode="filter", filter=tree)


def _is_member(bundle: UserBundle, scope: Mapping[str, str]) -> bool:
    return "tenant_id" not in scope or scope["tenant_id"] in bundle.tenants


def _walk(roles: Mapping[str, RoleEntry], role_id: str) -> Iterator[RoleEntry]:
    visited: set[str] = set()
    current: str | None = role_id
    while current is not None and current not in visited:
        role = roles.get(current)
        if role is None:
            return
        visited.add(current)
        yield role
        current = role.parent_id


def _matching(
    grants: list[EffectiveGrant], resource: str, action: str
) -> list[EffectiveGrant]:
    """Matching grants by specificity, then direct before group (stable)."""
    candidates = [f"{resource}:{action}", f"{resource}:*", f"*:{action}", "*:*"]
    matches = [grant for grant in grants if grant.permission in candidates]
    return sorted(
        matches,
        key=lambda g: (candidates.index(g.permission), _VIA_RANK[g.via]),
    )


def _rule_subjects(
    bundle: UserBundle, scope: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The ``user`` / ``tenant`` rule mappings; ``"id"`` wins over attributes."""
    user = {**bundle.attributes, "id": bundle.user_id}
    tenant_id = scope.get("tenant_id")
    if tenant_id is None:
        return user, None
    return user, {**bundle.tenants[tenant_id], "id": tenant_id}


def _allow(grant: EffectiveGrant) -> Decision:
    return Decision(
        allowed=True,
        matched_permission=grant.permission,
        matched_via=grant.via,
        condition=grant.condition,
    )


def _deny(reason: DenialReason) -> Decision:
    return Decision(allowed=False, denial_reason=reason)
