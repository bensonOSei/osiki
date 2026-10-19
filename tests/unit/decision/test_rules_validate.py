from typing import Any

import pytest

from osiki.decision.rules import RuleError, validate_rule

OWN_TEAM: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "record.team_id"},
    "right": {"ref": "user.team_id"},
}


def _cmp(op: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {"op": op, "left": left, "right": right}


def _nest_not(rule: dict[str, Any], times: int) -> dict[str, Any]:
    for _ in range(times):
        rule = {"not": rule}
    return rule


def test_accepts_own_team() -> None:
    validate_rule(OWN_TEAM)


@pytest.mark.parametrize(
    "rule",
    [
        {"and": [OWN_TEAM, OWN_TEAM]},
        {"or": [OWN_TEAM]},
        {"not": OWN_TEAM},
        _cmp("in", {"ref": "record.status"}, {"value": ["open", "draft"]}),
        _cmp("in", {"ref": "record.team_id"}, {"ref": "user.team_ids"}),
        _cmp("in", {"value": "admin"}, {"ref": "user.roles"}),
        _cmp("in", {"ref": "record.x"}, {"value": []}),
        _cmp("lt", {"ref": "record.amount"}, {"value": 100}),
        _cmp("gte", {"value": 1.5}, {"ref": "record.amount"}),
        _cmp("eq", {"ref": "user.id"}, {"ref": "tenant.owner_id"}),
        _cmp("ne", {"ref": "record.deleted"}, {"value": True}),
        _cmp("eq", {"ref": "record.parent"}, {"value": None}),
        _cmp("eq", {"ref": "record._private"}, {"value": "x"}),
        _cmp("eq", {"ref": "record." + "a" * 64}, {"value": "x"}),
    ],
)
def test_accepts_well_formed_rules(rule: dict[str, Any]) -> None:
    validate_rule(rule)


def test_rejects_record_vs_record() -> None:
    rule = _cmp("eq", {"ref": "record.a"}, {"ref": "record.b"})

    with pytest.raises(RuleError) as exc_info:
        validate_rule(rule)

    assert exc_info.value.path == "$"


def test_rejects_two_segment_ref() -> None:
    rule = _cmp("eq", {"ref": "record.a.b"}, {"value": 1})

    with pytest.raises(RuleError) as exc_info:
        validate_rule(rule)

    assert exc_info.value.path == "$.left.ref"


def test_rejects_in_with_record_on_right() -> None:
    rule = _cmp("in", {"ref": "user.team_id"}, {"ref": "record.team_ids"})

    with pytest.raises(RuleError) as exc_info:
        validate_rule(rule)

    assert exc_info.value.path == "$"


def test_accepts_depth_16() -> None:
    validate_rule(_nest_not(OWN_TEAM, 15))


def test_rejects_depth_17() -> None:
    with pytest.raises(RuleError) as exc_info:
        validate_rule(_nest_not(OWN_TEAM, 16))

    assert "depth" in exc_info.value.message


def test_accepts_256_nodes() -> None:
    validate_rule({"and": [OWN_TEAM] * 255})


def test_rejects_257_nodes() -> None:
    with pytest.raises(RuleError) as exc_info:
        validate_rule({"and": [OWN_TEAM] * 256})

    assert "256" in exc_info.value.message


@pytest.mark.parametrize(
    ("rule", "expected_path"),
    [
        # malformed shapes and unknown keys
        ("eq", "$"),
        ({}, "$"),
        ({"and": [OWN_TEAM], "or": [OWN_TEAM]}, "$"),
        ({"and": [OWN_TEAM], "extra": 1}, "$"),
        ({"and": []}, "$.and"),
        ({"or": OWN_TEAM}, "$.or"),
        ({"and": [OWN_TEAM, "x"]}, "$.and[1]"),
        ({"not": [OWN_TEAM]}, "$.not"),
        ({**OWN_TEAM, "extra": 1}, "$"),
        ({"op": "eq", "left": {"ref": "record.a"}}, "$"),
        (_cmp("like", {"ref": "record.a"}, {"value": "x"}), "$.op"),
        (_cmp("eq", "record.a", {"value": "x"}), "$.left"),
        (_cmp("eq", {}, {"value": "x"}), "$.left"),
        (_cmp("eq", {"ref": "record.a", "value": 1}, {"value": "x"}), "$.left"),
        (_cmp("eq", {"ref": 1}, {"value": "x"}), "$.left.ref"),
        (_cmp("eq", {"ref": "org.a"}, {"value": "x"}), "$.left.ref"),
        (_cmp("eq", {"ref": "record"}, {"value": "x"}), "$.left.ref"),
        (_cmp("eq", {"ref": "record.1a"}, {"value": "x"}), "$.left.ref"),
        (_cmp("eq", {"ref": "record.a\n"}, {"value": "x"}), "$.left.ref"),
        (_cmp("eq", {"ref": "record." + "a" * 65}, {"value": "x"}), "$.left.ref"),
        (_cmp("eq", {"ref": "record.a"}, {"value": {"k": 1}}), "$.right.value"),
        (_cmp("in", {"ref": "record.a"}, {"value": [[1]]}), "$.right.value[0]"),
        (_cmp("in", {"ref": "record.a"}, {"value": [1, {"k": 1}]}), "$.right.value[1]"),
        (_cmp("eq", {"ref": "record.a"}, {"value": float("nan")}), "$.right.value"),
        (_cmp("eq", {"ref": "record.a"}, {"value": float("inf")}), "$.right.value"),
        # semantic rules on a Compare
        (_cmp("eq", {"value": 1}, {"value": 1}), "$"),
        (_cmp("in", {"ref": "record.a"}, {"value": "x"}), "$"),
        (_cmp("lt", {"ref": "record.a"}, {"value": [1, 2]}), "$"),
        (_cmp("gte", {"value": [1, 2]}, {"ref": "record.a"}), "$"),
        (_cmp("eq", {"ref": "record.a"}, {"value": [1, 2]}), "$"),
        (_cmp("in", {"value": [1]}, {"ref": "user.ids"}), "$"),
        # errors deep in the tree carry the full path
        (
            {"and": [OWN_TEAM, {"not": _cmp("eq", {}, {"value": 1})}]},
            "$.and[1].not.left",
        ),
    ],
)
def test_rejects_malformed_rules(rule: Any, expected_path: str) -> None:
    with pytest.raises(RuleError) as exc_info:
        validate_rule(rule)

    assert exc_info.value.path == expected_path


def test_rule_error_is_value_error_with_path_in_str() -> None:
    error = RuleError("$.and[1].left", "bad operand")

    assert isinstance(error, ValueError)
    assert error.path == "$.and[1].left"
    assert error.message == "bad operand"
    assert str(error) == "$.and[1].left: bad operand"
