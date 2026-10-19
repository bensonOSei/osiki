"""Pure ``decide`` / ``effective_grants`` tests over snapshots and bundles.

Covers exact and wildcard matching, inheritance, cycles, expiry and group via
(ported from the retired permission resolver's tests) plus the
conditional-grant semantics pinned in Task B4.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from osiki.decision.decide import decide, effective_grants
from osiki.decision.models import Decision, EffectiveGrant, GrantEntry, UserBundle
from tests.conftest import (
    make_assignment_entry,
    make_decision_request,
    make_role_entry,
    make_snapshot,
    make_user_bundle,
)

OWN_TEAM: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "record.team_id"},
    "right": {"ref": "user.team_id"},
}


def _allow(
    permission: str, via: str = "direct", condition: str | None = None
) -> Decision:
    return Decision.model_validate(
        {
            "allowed": True,
            "matched_permission": permission,
            "matched_via": via,
            "condition": condition,
            "denial_reason": None,
        }
    )


def _deny(reason: str) -> Decision:
    return Decision.model_validate(
        {
            "allowed": False,
            "matched_permission": None,
            "matched_via": None,
            "condition": None,
            "denial_reason": reason,
        }
    )


def _single_role(*grants: tuple[str, str | None], **assignment: Any) -> Any:
    snapshot = make_snapshot(
        roles=[make_role_entry("r", grants=list(grants))],
        conditions={"own_team": OWN_TEAM},
    )
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("r", **assignment)],
        attributes={"team_id": "t1"},
        tenants={"acme": {}},
    )
    return snapshot, bundle


# --- Exact and wildcard matching ---


def test_exact_permission_allows() -> None:
    snapshot, bundle = _single_role(("docs:read", None))

    result = decide(snapshot, bundle, make_decision_request("docs", "read"))

    assert result == _allow("docs:read")


def test_resource_wildcard_allows() -> None:
    snapshot, bundle = _single_role(("docs:*", None))

    result = decide(snapshot, bundle, make_decision_request("docs", "delete"))

    assert result == _allow("docs:*")


def test_action_wildcard_allows() -> None:
    snapshot, bundle = _single_role(("*:read", None))

    result = decide(snapshot, bundle, make_decision_request("files", "read"))

    assert result == _allow("*:read")


def test_full_wildcard_allows() -> None:
    snapshot, bundle = _single_role(("*:*", None))

    result = decide(snapshot, bundle, make_decision_request("anything", "anything"))

    assert result == _allow("*:*")


def test_no_assignments_denies_no_permission() -> None:
    result = decide(make_snapshot(), make_user_bundle(), make_decision_request())

    assert result == _deny("no_permission")


def test_role_without_grants_denies() -> None:
    snapshot, bundle = _single_role()

    assert decide(snapshot, bundle, make_decision_request()) == _deny("no_permission")


def test_non_matching_grants_deny() -> None:
    snapshot, bundle = _single_role(("docs:write", None), ("files:read", None))

    assert decide(snapshot, bundle, make_decision_request()) == _deny("no_permission")


def test_most_specific_match_wins() -> None:
    snapshot, bundle = _single_role(
        ("*:*", None), ("*:read", None), ("docs:*", None), ("docs:read", None)
    )

    assert decide(snapshot, bundle, make_decision_request()) == _allow("docs:read")


def test_resource_wildcard_beats_action_wildcard() -> None:
    snapshot, bundle = _single_role(("*:read", None), ("docs:*", None))

    assert decide(snapshot, bundle, make_decision_request()) == _allow("docs:*")


def test_multiple_grants_finds_match() -> None:
    snapshot, bundle = _single_role(
        ("docs:read", None), ("files:write", None), ("users:manage", None)
    )

    result = decide(snapshot, bundle, make_decision_request("users", "manage"))

    assert result == _allow("users:manage")


# --- Role hierarchy ---


def test_role_inherits_ancestor_grants() -> None:
    snapshot = make_snapshot(
        roles=[
            make_role_entry("child", grants=[("docs:write", None)], parent_id="mid"),
            make_role_entry("mid", parent_id="root"),
            make_role_entry("root", grants=[("docs:read", None)]),
        ]
    )
    bundle = make_user_bundle(assignments=[make_assignment_entry("child")])

    assert decide(snapshot, bundle, make_decision_request()) == _allow("docs:read")


def test_cycle_stops_walk_without_raising() -> None:
    snapshot = make_snapshot(
        roles=[
            make_role_entry("a", grants=[("docs:read", None)], parent_id="b"),
            make_role_entry("b", grants=[("files:read", None)], parent_id="a"),
        ]
    )
    bundle = make_user_bundle(assignments=[make_assignment_entry("a")])

    assert decide(snapshot, bundle, make_decision_request()) == _allow("docs:read")
    assert decide(snapshot, bundle, make_decision_request("files", "read")) == _allow(
        "files:read"
    )
    assert decide(snapshot, bundle, make_decision_request("wiki", "read")) == _deny(
        "no_permission"
    )


def test_self_parent_role_is_visited_once() -> None:
    snapshot = make_snapshot(
        roles=[make_role_entry("a", grants=[("docs:read", None)], parent_id="a")]
    )
    bundle = make_user_bundle(assignments=[make_assignment_entry("a")])

    assert effective_grants(snapshot, bundle, {}, 0) == [
        EffectiveGrant(permission="docs:read", condition=None, via="direct")
    ]


def test_missing_parent_stops_walk() -> None:
    snapshot = make_snapshot(
        roles=[make_role_entry("child", grants=[("docs:read", None)], parent_id="gone")]
    )
    bundle = make_user_bundle(assignments=[make_assignment_entry("child")])

    assert decide(snapshot, bundle, make_decision_request()) == _allow("docs:read")


def test_missing_assigned_role_denies() -> None:
    bundle = make_user_bundle(assignments=[make_assignment_entry("gone")])

    result = decide(make_snapshot(), bundle, make_decision_request())

    assert result == _deny("no_permission")


# --- Scope and expiry ---


def test_tenant_scoped_assignment_applies_in_its_tenant() -> None:
    snapshot, bundle = _single_role(("docs:read", None), scope={"tenant_id": "acme"})

    result = decide(
        snapshot, bundle, make_decision_request(scope={"tenant_id": "acme"})
    )

    assert result == _allow("docs:read")


def test_tenant_scoped_assignment_ignored_without_tenant() -> None:
    snapshot, bundle = _single_role(("docs:read", None), scope={"tenant_id": "acme"})

    result = decide(snapshot, bundle, make_decision_request(scope={}))

    assert result == _deny("no_permission")


def test_assignment_for_other_tenant_ignored() -> None:
    snapshot = make_snapshot(roles=[make_role_entry("r", grants=[("docs:read", None)])])
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("r", scope={"tenant_id": "t1"})],
        tenants={"t1": {}, "t2": {}},
    )

    result = decide(snapshot, bundle, make_decision_request(scope={"tenant_id": "t2"}))

    assert result == _deny("no_permission")


def test_scope_key_mismatch_ignored() -> None:
    snapshot, bundle = _single_role(
        ("docs:read", None), scope={"tenant_id": "acme", "region": "us-west"}
    )
    request = make_decision_request(scope={"tenant_id": "acme", "region": "us-east"})

    assert decide(snapshot, bundle, request) == _deny("no_permission")


def test_project_wide_assignment_applies_in_member_tenant() -> None:
    snapshot, bundle = _single_role(("docs:read", None))

    result = decide(
        snapshot, bundle, make_decision_request(scope={"tenant_id": "acme"})
    )

    assert result == _allow("docs:read")


def test_not_tenant_member() -> None:
    snapshot, bundle = _single_role(("docs:read", None))

    result = decide(
        snapshot, bundle, make_decision_request(scope={"tenant_id": "other"})
    )

    assert result == _deny("not_tenant_member")


def test_expired_assignment_ignored() -> None:
    snapshot, bundle = _single_role(("docs:read", None), expires_at=999)

    assert decide(snapshot, bundle, make_decision_request(now=1000)) == _deny(
        "no_permission"
    )


def test_assignment_expiring_exactly_now_is_expired() -> None:
    snapshot, bundle = _single_role(("docs:read", None), expires_at=1000)

    assert decide(snapshot, bundle, make_decision_request(now=1000)) == _deny(
        "no_permission"
    )


def test_assignment_expiring_later_applies() -> None:
    snapshot, bundle = _single_role(("docs:read", None), expires_at=1001)

    assert decide(snapshot, bundle, make_decision_request(now=1000)) == _allow(
        "docs:read"
    )


# --- Direct and group ---


def test_group_assignment_reports_via_group() -> None:
    snapshot, bundle = _single_role(("files:write", None), via="group")

    result = decide(snapshot, bundle, make_decision_request("files", "write"))

    assert result == _allow("files:write", via="group")


def test_direct_beats_group_at_equal_specificity() -> None:
    snapshot = make_snapshot(roles=[make_role_entry("r", grants=[("docs:read", None)])])
    bundle = make_user_bundle(
        assignments=[
            make_assignment_entry("r", via="group"),
            make_assignment_entry("r", via="direct"),
        ]
    )

    assert decide(snapshot, bundle, make_decision_request()) == _allow("docs:read")


def test_specificity_beats_direct() -> None:
    snapshot = make_snapshot(
        roles=[
            make_role_entry("wide", grants=[("docs:*", None)]),
            make_role_entry("exact", grants=[("docs:read", None)]),
        ]
    )
    bundle = make_user_bundle(
        assignments=[
            make_assignment_entry("wide", via="direct"),
            make_assignment_entry("exact", via="group"),
        ]
    )

    result = decide(snapshot, bundle, make_decision_request())

    assert result == _allow("docs:read", via="group")


# --- Conditional grants ---


def test_conditional_wildcard_applies_condition() -> None:
    snapshot, bundle = _single_role(("invoices:*", "own_team"))

    allowed = decide(
        snapshot,
        bundle,
        make_decision_request("invoices", "delete", record={"team_id": "t1"}),
    )
    no_record = decide(snapshot, bundle, make_decision_request("invoices", "delete"))

    assert allowed == _allow("invoices:*", condition="own_team")
    assert allowed.condition == "own_team"
    assert allowed.matched_permission == "invoices:*"
    assert no_record == _deny("record_required")


def test_conditional_grant_other_team_fails() -> None:
    snapshot, bundle = _single_role(("invoices:read", "own_team"))
    request = make_decision_request("invoices", "read", record={"team_id": "t2"})

    assert decide(snapshot, bundle, request) == _deny("condition_failed")


def test_unconditional_beats_conditional() -> None:
    snapshot = make_snapshot(
        roles=[
            make_role_entry("cond", grants=[("invoices:read", "own_team")]),
            make_role_entry("open", grants=[("invoices:read", None)]),
        ],
        conditions={"own_team": OWN_TEAM},
    )
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("cond"), make_assignment_entry("open")]
    )

    result = decide(snapshot, bundle, make_decision_request("invoices", "read"))

    assert result == _allow("invoices:read")


def test_less_specific_unconditional_beats_more_specific_conditional() -> None:
    snapshot, bundle = _single_role(("docs:read", "own_team"), ("docs:*", None))

    assert decide(snapshot, bundle, make_decision_request()) == _allow("docs:*")


def test_unknown_condition_key_skipped() -> None:
    snapshot, bundle = _single_role(("invoices:read", "deleted_key"))
    request = make_decision_request("invoices", "read", record={"team_id": "t1"})

    assert decide(snapshot, bundle, request) == _deny("condition_failed")


def test_conditions_evaluated_in_specificity_order() -> None:
    always: dict[str, Any] = {
        "op": "eq",
        "left": {"ref": "user.id"},
        "right": {"value": "user-1"},
    }
    snapshot = make_snapshot(
        roles=[
            make_role_entry("r", grants=[("*:*", "always"), ("invoices:*", "own_team")])
        ],
        conditions={"own_team": OWN_TEAM, "always": always},
    )
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("r")], attributes={"team_id": "t1"}
    )
    same_team = make_decision_request("invoices", "read", record={"team_id": "t1"})
    other_team = make_decision_request("invoices", "read", record={"team_id": "t2"})

    assert decide(snapshot, bundle, same_team) == _allow(
        "invoices:*", condition="own_team"
    )
    assert decide(snapshot, bundle, other_team) == _allow("*:*", condition="always")


def test_equal_specificity_conditions_follow_encounter_order() -> None:
    never: dict[str, Any] = {
        "op": "eq",
        "left": {"ref": "record.team_id"},
        "right": {"value": "nobody"},
    }
    snapshot = make_snapshot(
        roles=[
            make_role_entry("first", grants=[("invoices:read", "never")]),
            make_role_entry("second", grants=[("invoices:read", "own_team")]),
        ],
        conditions={"own_team": OWN_TEAM, "never": never},
    )
    bundle = make_user_bundle(
        assignments=[
            make_assignment_entry("first", via="group"),
            make_assignment_entry("second", via="group"),
        ],
        attributes={"team_id": "t1"},
    )
    request = make_decision_request("invoices", "read", record={"team_id": "t1"})

    assert decide(snapshot, bundle, request) == _allow(
        "invoices:read", via="group", condition="own_team"
    )


def test_user_id_cannot_be_spoofed_by_attribute() -> None:
    owner: dict[str, Any] = {
        "op": "eq",
        "left": {"ref": "record.owner_id"},
        "right": {"ref": "user.id"},
    }
    snapshot = make_snapshot(
        roles=[make_role_entry("r", grants=[("docs:read", "owner")])],
        conditions={"owner": owner},
    )
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("r")],
        user_id="real",
        attributes={"id": "spoof"},
    )

    spoofed = decide(
        snapshot, bundle, make_decision_request(record={"owner_id": "spoof"})
    )
    real = decide(snapshot, bundle, make_decision_request(record={"owner_id": "real"}))

    assert spoofed == _deny("condition_failed")
    assert real == _allow("docs:read", condition="owner")


def test_tenant_attributes_visible_to_rules() -> None:
    same_region: dict[str, Any] = {
        "and": [
            {
                "op": "eq",
                "left": {"ref": "record.region"},
                "right": {"ref": "tenant.region"},
            },
            {
                "op": "eq",
                "left": {"ref": "record.tenant_id"},
                "right": {"ref": "tenant.id"},
            },
        ]
    }
    snapshot = make_snapshot(
        roles=[make_role_entry("r", grants=[("docs:read", "same_region")])],
        conditions={"same_region": same_region},
    )
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("r")],
        tenants={"acme": {"region": "gh", "id": "spoof"}},
    )
    scope = {"tenant_id": "acme"}

    allowed = decide(
        snapshot,
        bundle,
        make_decision_request(
            scope=scope, record={"region": "gh", "tenant_id": "acme"}
        ),
    )
    wrong_region = decide(
        snapshot,
        bundle,
        make_decision_request(
            scope=scope, record={"region": "ug", "tenant_id": "acme"}
        ),
    )
    no_tenant = decide(
        snapshot,
        bundle,
        make_decision_request(record={"region": "gh", "tenant_id": "acme"}),
    )

    assert allowed == _allow("docs:read", condition="same_region")
    assert wrong_region == _deny("condition_failed")
    assert no_tenant == _deny("condition_failed")


# --- effective_grants ---


def test_effective_grants_lists_direct_and_group_in_encounter_order() -> None:
    snapshot = make_snapshot(
        roles=[
            make_role_entry(
                "reader", grants=[("docs:read", None), ("invoices:read", "own_team")]
            ),
            make_role_entry(
                "editor", grants=[("files:write", None)], parent_id="reader"
            ),
        ]
    )
    bundle = make_user_bundle(
        assignments=[
            make_assignment_entry("editor", via="group"),
            make_assignment_entry("reader", via="direct"),
            make_assignment_entry("editor", via="group"),
        ]
    )

    assert effective_grants(snapshot, bundle, {}, 0) == [
        EffectiveGrant(permission="files:write", condition=None, via="group"),
        EffectiveGrant(permission="docs:read", condition=None, via="group"),
        EffectiveGrant(permission="invoices:read", condition="own_team", via="group"),
        EffectiveGrant(permission="docs:read", condition=None, via="direct"),
        EffectiveGrant(permission="invoices:read", condition="own_team", via="direct"),
    ]


def test_effective_grants_filters_scope_and_expiry() -> None:
    snapshot = make_snapshot(
        roles=[
            make_role_entry("a", grants=[("docs:read", None)]),
            make_role_entry("b", grants=[("files:write", None)]),
            make_role_entry("c", grants=[("wiki:read", None)]),
        ]
    )
    bundle = make_user_bundle(
        assignments=[
            make_assignment_entry("a", scope={"tenant_id": "t1"}),
            make_assignment_entry("b", scope={"tenant_id": "t2"}),
            make_assignment_entry("c", expires_at=5),
        ],
        tenants={"t1": {}, "t2": {}},
    )

    assert effective_grants(snapshot, bundle, {"tenant_id": "t1"}, 10) == [
        EffectiveGrant(permission="docs:read", condition=None, via="direct")
    ]
    assert effective_grants(snapshot, bundle, {}, 0) == [
        EffectiveGrant(permission="wiki:read", condition=None, via="direct")
    ]


def test_effective_grants_empty_for_non_member_tenant() -> None:
    snapshot, bundle = _single_role(("docs:read", None))

    assert effective_grants(snapshot, bundle, {"tenant_id": "other"}, 0) == []


def test_direct_conditional_beats_group_conditional() -> None:
    always: dict[str, Any] = {
        "op": "eq",
        "left": {"ref": "user.id"},
        "right": {"value": "user-1"},
    }
    snapshot = make_snapshot(
        roles=[
            make_role_entry("first", grants=[("invoices:read", "always")]),
            make_role_entry("second", grants=[("invoices:read", "own_team")]),
        ],
        conditions={"own_team": OWN_TEAM, "always": always},
    )
    bundle = make_user_bundle(
        assignments=[
            make_assignment_entry("first", via="group"),
            make_assignment_entry("second", via="direct"),
        ],
        attributes={"team_id": "t1"},
    )
    request = make_decision_request("invoices", "read", record={"team_id": "t1"})

    assert decide(snapshot, bundle, request) == _allow(
        "invoices:read", condition="own_team"
    )


def test_grant_condition_key_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        GrantEntry(permission="docs:read", condition="")


# --- Tenant-owned roles shipped in the bundle ---


def test_bundle_role_grants_when_snapshot_lacks_it() -> None:
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("tr1")],
        roles=[make_role_entry("tr1", grants=[("docs:read", None)])],
    )

    assert decide(make_snapshot(), bundle, make_decision_request()) == _allow(
        "docs:read"
    )
    assert effective_grants(make_snapshot(), bundle, {}, 1000) == [
        EffectiveGrant(permission="docs:read", via="direct")
    ]


def test_snapshot_role_wins_over_bundle_role_with_same_id() -> None:
    snapshot = make_snapshot(roles=[make_role_entry("r1")])
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("r1")],
        roles=[make_role_entry("r1", grants=[("docs:read", None)])],
    )

    assert decide(snapshot, bundle, make_decision_request()) == _deny("no_permission")


def test_role_missing_from_snapshot_and_bundle_denies() -> None:
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("tr9")],
        roles=[make_role_entry("other", grants=[("docs:read", None)])],
    )

    assert decide(make_snapshot(), bundle, make_decision_request()) == _deny(
        "no_permission"
    )


def test_bundle_role_inherits_from_a_snapshot_parent() -> None:
    snapshot = make_snapshot(
        roles=[make_role_entry("base", grants=[("docs:read", None)])]
    )
    bundle = make_user_bundle(
        assignments=[make_assignment_entry("tr1")],
        roles=[make_role_entry("tr1", parent_id="base")],
    )

    assert decide(snapshot, bundle, make_decision_request()) == _allow("docs:read")


def test_bundle_without_roles_reads_as_empty() -> None:
    assert make_user_bundle().roles == []
    assert UserBundle.model_validate({"user_id": "u"}).roles == []
