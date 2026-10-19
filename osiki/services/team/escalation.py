"""Pure no-escalation rules: a manager may not grant what they do not hold.

Deliberately not under ``osiki/decision/``: that package is vendored to the SDK.
"""

from collections.abc import Sequence

from osiki.decision.models import EffectiveGrant, GrantEntry

_WILDCARD = "*"
_BUILTIN_PREFIX = "osiki."


def _split(permission: str) -> tuple[str, str]:
    resource, action = permission.split(":", 1)
    return resource, action


def _part_covers(held: str, wanted: str) -> bool:
    return held == _WILDCARD or held == wanted


def covers(held: EffectiveGrant | GrantEntry, wanted: GrantEntry) -> bool:
    """True when ``held`` lets its holder grant ``wanted``.

    ``*`` covers any value, but only within its own part. An unconditioned held
    grant covers any condition; a conditioned one covers only the same condition.
    """
    held_resource, held_action = _split(held.permission)
    wanted_resource, wanted_action = _split(wanted.permission)
    if not (
        _part_covers(held_resource, wanted_resource)
        and _part_covers(held_action, wanted_action)
    ):
        return False
    return held.condition is None or held.condition == wanted.condition


def uncovered(
    held: Sequence[EffectiveGrant], wanted: Sequence[GrantEntry]
) -> list[GrantEntry]:
    """The wanted grants no held grant covers, in wanted order, deduplicated."""
    missing: list[GrantEntry] = []
    for entry in wanted:
        if entry in missing:
            continue
        if not any(covers(grant, entry) for grant in held):
            missing.append(entry)
    return missing


def is_builtin_permission(permission: str) -> bool:
    """True for built-in ``osiki.…:…`` permissions."""
    return _split(permission)[0].startswith(_BUILTIN_PREFIX)
