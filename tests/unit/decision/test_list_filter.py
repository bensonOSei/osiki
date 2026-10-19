from typing import Any

from osiki.decision.decide import list_filter
from osiki.decision.models import FilterResult
from tests.conftest import (
    make_assignment_entry,
    make_role_entry,
    make_snapshot,
    make_user_bundle,
)

OWN_TEAM: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "record.team_id"},
    "right": {"ref": "user.team_id"},
}
OWNER: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "record.owner_id"},
    "right": {"ref": "user.id"},
}
SAME_REGION: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "record.region"},
    "right": {"ref": "tenant.region"},
}
IS_USER_1: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "user.id"},
    "right": {"value": "user-1"},
}
CONDITIONS = {
    "own_team": OWN_TEAM,
    "owner": OWNER,
    "same_region": SAME_REGION,
    "is_user_1": IS_USER_1,
}


def _leaf(field: str, value: Any) -> dict[str, Any]:
    return {"field": field, "op": "eq", "value": value, "type": "string"}


def _filter(
    *grants: tuple[str, str | None],
    scope: dict[str, str] | None = None,
    attributes: dict[str, Any] | None = None,
    **assignment: Any,
) -> FilterResult:
    snapshot = make_snapshot(
        roles=[make_role_entry("r", grants=list(grants))], conditions=CONDITIONS
    )
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("r", **assignment)],
        attributes={"team_id": "t1"} if attributes is None else attributes,
        tenants={"acme": {"region": "gh"}},
    )
    return list_filter(snapshot, bundle, "invoices", "read", scope or {}, 1000)


def _all() -> FilterResult:
    return FilterResult(mode="all", filter=None)


def _none() -> FilterResult:
    return FilterResult(mode="none", filter=None)


def test_list_filter_all_none_filter() -> None:
    assert _filter(("invoices:read", None)) == _all()
    assert _filter(("docs:read", None)) == _none()
    assert _filter(("invoices:read", "own_team")) == FilterResult(
        mode="filter", filter=_leaf("team_id", "t1")
    )


def test_list_filter_all_mode() -> None:
    assert _filter(("invoices:*", None), ("invoices:read", "own_team")) == _all()


def test_list_filter_none_mode() -> None:
    assert _filter() == _none()


def test_list_filter_filter_mode() -> None:
    result = _filter(("invoices:read", "own_team"))

    assert result.mode == "filter"
    assert result.filter == _leaf("team_id", "t1")


def test_residual_true_gives_all() -> None:
    assert _filter(("invoices:read", "own_team"), ("*:*", "is_user_1")) == _all()


def test_all_residuals_false_gives_none() -> None:
    assert _filter(("invoices:read", "own_team"), attributes={}) == _none()


def test_unknown_condition_key_skipped() -> None:
    assert _filter(("invoices:read", "deleted_key")) == _none()


def test_multiple_residuals_or_in_specificity_order() -> None:
    result = _filter(
        ("*:read", "owner"),
        ("invoices:read", "own_team"),
        ("invoices:*", "own_team"),
    )

    assert result == FilterResult(
        mode="filter",
        filter={"or": [_leaf("team_id", "t1"), _leaf("owner_id", "user-1")]},
    )


def test_tenant_attributes_feed_residual() -> None:
    result = _filter(("invoices:read", "same_region"), scope={"tenant_id": "acme"})

    assert result == FilterResult(mode="filter", filter=_leaf("region", "gh"))


def test_not_tenant_member_gives_none() -> None:
    assert _filter(("invoices:read", None), scope={"tenant_id": "other"}) == _none()


def test_expired_assignment_gives_none() -> None:
    assert _filter(("invoices:read", None), expires_at=1000) == _none()
