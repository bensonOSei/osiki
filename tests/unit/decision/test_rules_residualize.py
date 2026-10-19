from typing import Any

import pytest

from osiki.decision.rules import residualize

USER: dict[str, Any] = {"id": "u1", "team_id": "t1"}
OWN_TEAM: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "record.team_id"},
    "right": {"ref": "user.team_id"},
}
TRUE_CMP: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "user.id"},
    "right": {"value": "u1"},
}
FALSE_CMP: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "user.id"},
    "right": {"value": "someone-else"},
}
UNKNOWN_CMP: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "user.missing"},
    "right": {"value": 1},
}
AMOUNT_LT_100: dict[str, Any] = {
    "op": "lt",
    "left": {"ref": "record.amount"},
    "right": {"value": 100},
}


def _cmp(op: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {"op": op, "left": left, "right": right}


def _rec(field: str, op: str, value: Any) -> dict[str, Any]:
    return _cmp(op, {"ref": f"record.{field}"}, {"value": value})


def _leaf(field: str, op: str, value: Any) -> dict[str, Any]:
    return {"field": field, "op": op, "value": value}


def test_own_team_becomes_field_filter() -> None:
    assert residualize(OWN_TEAM, USER, None) == _leaf("team_id", "eq", "t1")


def test_missing_user_attr_is_false() -> None:
    assert residualize(OWN_TEAM, {"id": "u1"}, None) is False


def test_null_user_attr_is_false() -> None:
    assert residualize(OWN_TEAM, {"id": "u1", "team_id": None}, None) is False


def test_not_over_missing_user_attr_is_false() -> None:
    assert residualize({"not": OWN_TEAM}, {"id": "u1"}, None) is False


def test_not_pushed_down() -> None:
    rule = {"not": AMOUNT_LT_100}

    assert residualize(rule, USER, None) == _leaf("amount", "gte", 100)


@pytest.mark.parametrize(
    ("op", "negated"),
    [
        ("eq", "ne"),
        ("ne", "eq"),
        ("lt", "gte"),
        ("gte", "lt"),
        ("lte", "gt"),
        ("gt", "lte"),
    ],
)
def test_operator_negation(op: str, negated: str) -> None:
    rule = {"not": _rec("x", op, 5)}

    assert residualize(rule, USER, None) == _leaf("x", negated, 5)


def test_in_negates_to_nin() -> None:
    rule = {"not": _rec("status", "in", ["open", "draft"])}

    assert residualize(rule, USER, None) == _leaf("status", "nin", ["open", "draft"])


def test_record_on_right_flips_op() -> None:
    rule = _cmp("lt", {"value": 100}, {"ref": "record.amount"})

    assert residualize(rule, USER, None) == _leaf("amount", "gt", 100)


@pytest.mark.parametrize(
    ("op", "flipped"),
    [
        ("eq", "eq"),
        ("ne", "ne"),
        ("lt", "gt"),
        ("lte", "gte"),
        ("gt", "lt"),
        ("gte", "lte"),
    ],
)
def test_record_on_right_flip_table(op: str, flipped: str) -> None:
    rule = _cmp(op, {"ref": "user.team_id"}, {"ref": "record.x"})

    assert residualize(rule, USER, None) == _leaf("x", flipped, "t1")


def test_record_on_right_under_not() -> None:
    rule = {"not": _cmp("lt", {"value": 100}, {"ref": "record.amount"})}

    assert residualize(rule, USER, None) == _leaf("amount", "lte", 100)


def test_constant_true_folds() -> None:
    rule = {"or": [TRUE_CMP, AMOUNT_LT_100]}

    assert residualize(rule, USER, None) is True


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (TRUE_CMP, True),
        (FALSE_CMP, False),
        (UNKNOWN_CMP, False),
        ({"not": TRUE_CMP}, False),
        ({"not": FALSE_CMP}, True),
        ({"not": UNKNOWN_CMP}, False),
        ({"and": [TRUE_CMP, AMOUNT_LT_100]}, _leaf("amount", "lt", 100)),
        ({"and": [FALSE_CMP, AMOUNT_LT_100]}, False),
        ({"and": [UNKNOWN_CMP, AMOUNT_LT_100]}, False),
        ({"and": [TRUE_CMP, TRUE_CMP]}, True),
        ({"or": [FALSE_CMP, AMOUNT_LT_100]}, _leaf("amount", "lt", 100)),
        ({"or": [UNKNOWN_CMP, AMOUNT_LT_100]}, _leaf("amount", "lt", 100)),
        ({"or": [FALSE_CMP, FALSE_CMP]}, False),
        ({"or": [FALSE_CMP, UNKNOWN_CMP]}, False),
        ({"not": {"or": [FALSE_CMP, UNKNOWN_CMP]}}, False),
        ({"not": {"and": [FALSE_CMP, UNKNOWN_CMP]}}, True),
        ({"not": {"and": [TRUE_CMP, UNKNOWN_CMP]}}, False),
        ({"not": {"not": AMOUNT_LT_100}}, _leaf("amount", "lt", 100)),
    ],
)
def test_constant_folding(rule: dict[str, Any], expected: Any) -> None:
    assert residualize(rule, USER, None) == expected


def test_not_and_becomes_or_of_negations() -> None:
    rule = {"not": {"and": [OWN_TEAM, AMOUNT_LT_100]}}

    assert residualize(rule, USER, None) == {
        "or": [_leaf("team_id", "ne", "t1"), _leaf("amount", "gte", 100)]
    }


def test_not_or_becomes_and_of_negations() -> None:
    rule = {"not": {"or": [OWN_TEAM, AMOUNT_LT_100]}}

    assert residualize(rule, USER, None) == {
        "and": [_leaf("team_id", "ne", "t1"), _leaf("amount", "gte", 100)]
    }


def test_nested_tree_keeps_structure() -> None:
    rule = {
        "or": [
            {"and": [OWN_TEAM, AMOUNT_LT_100]},
            _rec("public", "eq", True),
        ]
    }

    assert residualize(rule, USER, None) == {
        "or": [
            {"and": [_leaf("team_id", "eq", "t1"), _leaf("amount", "lt", 100)]},
            _leaf("public", "eq", True),
        ]
    }


def test_tenant_refs_are_substituted() -> None:
    rule = _cmp("eq", {"ref": "record.tenant_id"}, {"ref": "tenant.id"})

    assert residualize(rule, USER, {"id": "acme"}) == _leaf("tenant_id", "eq", "acme")
    assert residualize(rule, USER, None) is False


def test_in_against_user_list_attribute() -> None:
    rule = _cmp("in", {"ref": "record.team_id"}, {"ref": "user.team_ids"})
    user = {"id": "u1", "team_ids": ["t1", "t2"]}

    assert residualize(rule, user, None) == _leaf("team_id", "in", ["t1", "t2"])


@pytest.mark.parametrize(
    ("op", "value"),
    [
        ("eq", ["t1"]),
        ("eq", {"k": 1}),
        ("eq", float("nan")),
        ("lt", True),
        ("lt", ["t1"]),
        ("in", "t1"),
    ],
)
def test_uncomparable_user_value_is_false(op: str, value: Any) -> None:
    rule = _cmp(op, {"ref": "record.x"}, {"ref": "user.v"})
    user = {"id": "u1", "v": value}

    assert residualize(rule, user, None) is False
    assert residualize({"not": rule}, user, None) is False


def test_in_drops_elements_that_can_never_match() -> None:
    rule = _rec("x", "in", [1, None, 2])

    assert residualize(rule, USER, None) == _leaf("x", "in", [1, 2])


def test_in_with_nothing_matchable_is_false() -> None:
    assert residualize(_rec("x", "in", [None]), USER, None) is False
    assert residualize(_rec("x", "in", []), USER, None) is False


def test_nin_empty_list_stays_a_leaf() -> None:
    rule = {"not": _rec("x", "in", [])}

    assert residualize(rule, USER, None) == _leaf("x", "nin", [])


@pytest.mark.parametrize("items", [[1, None], [1, "a"], [True, 1], [{"k": 1}]])
def test_nin_over_unmatchable_list_is_false(items: list[Any]) -> None:
    rule = {"not": _cmp("in", {"ref": "record.x"}, {"ref": "user.v"})}

    assert residualize(rule, {"id": "u1", "v": items}, None) is False


def test_in_over_mixed_list_keeps_comparable_elements() -> None:
    rule = _rec("x", "in", [1, "a", True])

    assert residualize(rule, USER, None) == _leaf("x", "in", [1, "a", True])


def test_null_literal_compare_is_false() -> None:
    assert residualize(_rec("x", "eq", None), USER, None) is False
    assert residualize({"not": _rec("x", "eq", None)}, USER, None) is False


def test_user_only_in_compare_folds() -> None:
    rule = _cmp("in", {"ref": "user.team_id"}, {"value": ["t1", "t9"]})

    assert residualize(rule, USER, None) is True
    assert residualize({"not": rule}, USER, None) is False
