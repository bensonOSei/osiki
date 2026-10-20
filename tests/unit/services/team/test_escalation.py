import pytest

from osiki.decision.models import EffectiveGrant, GrantEntry
from osiki.services.team.escalation import covers, is_builtin_permission, uncovered


@pytest.mark.parametrize(
    "held,wanted,ok",
    [
        (("invoices:read", None), ("invoices:read", None), True),
        (("invoices:*", None), ("invoices:read", None), True),
        (("invoices:*", None), ("invoices:*", None), True),
        (("*:read", None), ("invoices:*", None), False),
        (("*:*", None), ("*:read", None), True),
        (("invoices:read", None), ("invoices:read", "own"), True),
        (("invoices:read", "own"), ("invoices:read", None), False),
        (("invoices:read", "own"), ("invoices:read", "own"), True),
        (("invoices:read", "own"), ("invoices:read", "branch"), False),
        (("invoices:read", None), ("invoices:write", None), False),
        (("*:read", None), ("invoices:read", None), True),
        (("orders:read", None), ("invoices:read", None), False),
        (("invoices:read", None), ("invoices:*", None), False),
    ],
)
def test_covers(
    held: tuple[str, str | None], wanted: tuple[str, str | None], ok: bool
) -> None:
    assert (
        covers(
            GrantEntry(permission=held[0], condition=held[1]),
            GrantEntry(permission=wanted[0], condition=wanted[1]),
        )
        is ok
    )


def test_covers_accepts_effective_grant() -> None:
    held = EffectiveGrant(permission="invoices:*", condition=None, via="group")
    assert covers(held, GrantEntry(permission="invoices:read")) is True


def test_uncovered_keeps_wanted_order_and_dedupes() -> None:
    held = [
        EffectiveGrant(permission="invoices:read", condition=None, via="direct"),
        EffectiveGrant(permission="orders:*", condition="own", via="group"),
    ]
    wanted = [
        GrantEntry(permission="refunds:write"),
        GrantEntry(permission="invoices:read", condition="own"),
        GrantEntry(permission="orders:read", condition="own"),
        GrantEntry(permission="orders:read", condition="branch"),
        GrantEntry(permission="refunds:write"),
        GrantEntry(permission="admin:*"),
        GrantEntry(permission="orders:read", condition="branch"),
    ]
    assert uncovered(held, wanted) == [
        GrantEntry(permission="refunds:write"),
        GrantEntry(permission="orders:read", condition="branch"),
        GrantEntry(permission="admin:*"),
    ]


def test_uncovered_empty_when_everything_held() -> None:
    held = [EffectiveGrant(permission="*:*", condition=None, via="direct")]
    assert uncovered(held, [GrantEntry(permission="a:b")]) == []


def test_uncovered_with_nothing_held_returns_all_wanted() -> None:
    wanted = [GrantEntry(permission="a:b")]
    assert uncovered([], wanted) == wanted


@pytest.mark.parametrize(
    "permission,expected",
    [
        ("osiki.team:manage", True),
        ("osiki.roles:read", True),
        ("invoices:read", False),
        ("osikix:read", False),
        ("*:read", False),
        ("invoices:osiki.read", False),
    ],
)
def test_is_builtin_permission(permission: str, expected: bool) -> None:
    assert is_builtin_permission(permission) is expected
