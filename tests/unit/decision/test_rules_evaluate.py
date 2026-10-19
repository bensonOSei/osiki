from typing import Any

import pytest

from osiki.decision.rules import RuleContext, evaluate

OWN_TEAM: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "record.team_id"},
    "right": {"ref": "user.team_id"},
}
NEVER: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "record.team_id"},
    "right": {"value": "nobody"},
}
UNKNOWN_CMP: dict[str, Any] = {
    "op": "eq",
    "left": {"ref": "record.missing"},
    "right": {"value": 1},
}


def _cmp(op: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {"op": op, "left": left, "right": right}


def _rec(field: str, op: str, value: Any) -> dict[str, Any]:
    return _cmp(op, {"ref": f"record.{field}"}, {"value": value})


def _ctx(
    record: dict[str, Any] | None = None,
    user: dict[str, Any] | None = None,
    tenant: dict[str, Any] | None = None,
) -> RuleContext:
    return RuleContext(
        record=record,
        user=user if user is not None else {"id": "u1", "team_id": "t1"},
        tenant=tenant,
    )


def test_own_team_true() -> None:
    assert evaluate(OWN_TEAM, _ctx(record={"team_id": "t1"})) is True


def test_own_team_other_team_is_false() -> None:
    assert evaluate(OWN_TEAM, _ctx(record={"team_id": "t2"})) is False


def test_missing_record_field_is_false() -> None:
    assert evaluate(OWN_TEAM, _ctx(record={"name": "x"})) is False


def test_absent_record_is_false() -> None:
    assert evaluate(OWN_TEAM, _ctx(record=None)) is False


def test_missing_user_attribute_is_false() -> None:
    assert (
        evaluate(OWN_TEAM, _ctx(record={"team_id": "t1"}, user={"id": "u1"})) is False
    )


def test_not_over_missing_field_is_false() -> None:
    rule = {"not": OWN_TEAM}

    assert evaluate(rule, _ctx(record={"name": "x"})) is False


def test_not_over_false_is_true() -> None:
    assert evaluate({"not": OWN_TEAM}, _ctx(record={"team_id": "t2"})) is True


def test_ne_with_null_is_false() -> None:
    rule = _rec("status", "ne", "closed")

    assert evaluate(rule, _ctx(record={"status": None})) is False


def test_null_literal_never_matches() -> None:
    record = {"parent": None}

    assert evaluate(_rec("parent", "eq", None), _ctx(record=record)) is False
    assert evaluate(_rec("parent", "ne", None), _ctx(record=record)) is False


def test_bool_not_equal_one() -> None:
    record = {"flag": True}

    assert evaluate(_rec("flag", "eq", 1), _ctx(record=record)) is False
    assert evaluate(_rec("flag", "ne", 1), _ctx(record=record)) is False
    assert evaluate({"not": _rec("flag", "eq", 1)}, _ctx(record=record)) is False


def test_int_float_equal() -> None:
    assert evaluate(_rec("n", "eq", 1.0), _ctx(record={"n": 1})) is True


def test_in_list_literal() -> None:
    rule = _rec("status", "in", ["open", "draft"])

    assert evaluate(rule, _ctx(record={"status": "draft"})) is True
    assert evaluate(rule, _ctx(record={"status": "closed"})) is False


def test_or_true_with_unknown() -> None:
    rule = {"or": [OWN_TEAM, UNKNOWN_CMP]}

    assert evaluate(rule, _ctx(record={"team_id": "t1"})) is True


@pytest.mark.parametrize(
    ("op", "record_value", "literal", "expected"),
    [
        ("eq", "a", "a", True),
        ("eq", "a", "b", False),
        ("ne", "a", "b", True),
        ("ne", "a", "a", False),
        ("eq", True, True, True),
        ("ne", True, False, True),
        ("lt", 1, 2, True),
        ("lt", 2, 2, False),
        ("lte", 2, 2.0, True),
        ("gt", 3.5, 3, True),
        ("gte", 3, 4, False),
        ("lt", "apple", "banana", True),
        ("gt", "apple", "banana", False),
        # type mismatches are UNKNOWN, so both a Compare and its negation fail
        ("eq", "1", 1, False),
        ("ne", "1", 1, False),
        ("lt", "1", 2, False),
        ("gte", "1", 2, False),
        ("eq", 0, False, False),
        ("ne", 0, False, False),
        ("lt", False, True, False),
        ("gte", False, True, False),
        ("eq", ["a"], "a", False),
        ("ne", {"k": 1}, "a", False),
        ("ne", float("nan"), 1, False),
        ("lt", float("nan"), 1, False),
    ],
)
def test_compare_operators(
    op: str, record_value: Any, literal: Any, expected: bool
) -> None:
    rule = _rec("x", op, literal)

    assert evaluate(rule, _ctx(record={"x": record_value})) is expected


@pytest.mark.parametrize(
    ("record_value", "items", "expected"),
    [
        (1, [1, 2], True),
        (1.0, [1, 2], True),
        (3, [1, 2], False),
        (3, [], False),
        (True, [1], False),
        (1, [True], False),
        # an element that cannot be compared leaves a non-match UNKNOWN
        (3, [1, None], False),
        (3, [1, "a"], False),
        (1, [None, 1], True),
        (None, [1], False),
        (["a"], ["a"], False),
    ],
)
def test_in_semantics(record_value: Any, items: list[Any], expected: bool) -> None:
    rule = _rec("x", "in", items)

    assert evaluate(rule, _ctx(record={"x": record_value})) is expected


@pytest.mark.parametrize(
    ("record_value", "items", "expected"),
    [
        (3, [1, 2], True),
        (1, [1, 2], False),
        (3, [], True),
        (True, [1], False),
        (True, [False], True),
        (3, [1, None], False),
        (3, [1, "a"], False),
        (None, [1], False),
    ],
)
def test_not_in_semantics(record_value: Any, items: list[Any], expected: bool) -> None:
    rule = {"not": _rec("x", "in", items)}

    assert evaluate(rule, _ctx(record={"x": record_value})) is expected


def test_in_against_user_list_attribute() -> None:
    rule = _cmp("in", {"ref": "record.team_id"}, {"ref": "user.team_ids"})
    user = {"id": "u1", "team_ids": ["t1", "t2"]}

    assert evaluate(rule, _ctx(record={"team_id": "t2"}, user=user)) is True
    assert evaluate(rule, _ctx(record={"team_id": "t3"}, user=user)) is False


def test_in_against_non_list_attribute_is_unknown() -> None:
    rule = {"not": _cmp("in", {"ref": "record.team_id"}, {"ref": "user.team_ids"})}
    user = {"id": "u1", "team_ids": "t1"}

    assert evaluate(rule, _ctx(record={"team_id": "t2"}, user=user)) is False


def test_user_id_reads_the_id_key() -> None:
    rule = _cmp("eq", {"ref": "record.owner_id"}, {"ref": "user.id"})

    assert evaluate(rule, _ctx(record={"owner_id": "u1"})) is True


def test_tenant_ref_reads_tenant_mapping() -> None:
    rule = _cmp("eq", {"ref": "record.tenant_id"}, {"ref": "tenant.id"})

    assert evaluate(rule, _ctx(record={"tenant_id": "a"}, tenant={"id": "a"})) is True
    assert evaluate(rule, _ctx(record={"tenant_id": "a"}, tenant=None)) is False


def test_rule_without_record_refs() -> None:
    rule = _cmp("eq", {"ref": "user.region"}, {"ref": "tenant.region"})
    user = {"id": "u1", "region": "gh"}

    assert evaluate(rule, _ctx(user=user, tenant={"id": "a", "region": "gh"})) is True


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ({"and": [OWN_TEAM, OWN_TEAM]}, True),
        ({"and": [OWN_TEAM, NEVER]}, False),
        ({"and": [OWN_TEAM, UNKNOWN_CMP]}, False),
        ({"not": {"and": [OWN_TEAM, UNKNOWN_CMP]}}, False),
        ({"not": {"and": [NEVER, UNKNOWN_CMP]}}, True),
        ({"or": [NEVER, UNKNOWN_CMP]}, False),
        ({"not": {"or": [NEVER, UNKNOWN_CMP]}}, False),
        ({"not": {"or": [NEVER, NEVER]}}, True),
        ({"not": {"not": OWN_TEAM}}, True),
        ({"not": {"not": UNKNOWN_CMP}}, False),
    ],
)
def test_kleene_logic(rule: dict[str, Any], expected: bool) -> None:
    assert evaluate(rule, _ctx(record={"team_id": "t1"})) is expected
