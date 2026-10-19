"""Seeded property test: the residual filter matches exactly what evaluate allows.

The oracle below interprets a residual filter under the leaf contract in the
``osiki.decision.rules`` docstring, independently of the implementation.
"""

import math
import operator
import random
from collections.abc import Callable
from typing import Any

from osiki.decision.rules import (
    RuleContext,
    RuleError,
    evaluate,
    residualize,
    validate_rule,
)

SEED = 20261019
RULES = 3000
RECORDS_PER_RULE = 4

RUNTIME_VALUES: list[Any] = [
    None,
    0,
    1,
    1.0,
    2,
    -1.5,
    "a",
    "b",
    "1",
    True,
    False,
    float("nan"),
    [1, "a"],
    ["a", "b"],
    [1, 2],
    [],
    {"k": 1},
]
LITERALS: list[Any] = [None, 0, 1, 1.0, 2, "a", "b", "1", True, False]
OPS = ["eq", "ne", "lt", "lte", "gt", "gte", "in"]
FIELDS = ["x", "y"]
ATTRIBUTES = ["p", "q", "id"]

_LEAF_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
    "in": lambda field, items: field in items,
    "nin": lambda field, items: field not in items,
}


def _contract_type(value: Any) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) or (isinstance(value, float) and not math.isnan(value)):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def _matches(node: Any, record: dict[str, Any]) -> bool:
    if isinstance(node, bool):
        return node
    if "and" in node:
        return all(_matches(child, record) for child in node["and"])
    if "or" in node:
        return any(_matches(child, record) for child in node["or"])
    assert set(node) == {"field", "op", "value", "type"}
    field_value = record.get(node["field"])
    if _contract_type(field_value) != node["type"]:
        return False
    return _LEAF_OPS[node["op"]](field_value, node["value"])


def _operand(rng: random.Random, allow_list: bool) -> dict[str, Any]:
    roll = rng.random()
    if roll < 0.4:
        return {"ref": f"record.{rng.choice(FIELDS)}"}
    if roll < 0.6:
        return {"ref": f"{rng.choice(['user', 'tenant'])}.{rng.choice(ATTRIBUTES)}"}
    if allow_list and rng.random() < 0.5:
        return {"value": rng.sample(LITERALS, rng.randint(0, 3))}
    return {"value": rng.choice(LITERALS)}


def _rule(rng: random.Random, depth: int = 0) -> dict[str, Any]:
    roll = rng.random()
    if depth < 4 and roll < 0.15:
        return {"not": _rule(rng, depth + 1)}
    if depth < 4 and roll < 0.35:
        children = [_rule(rng, depth + 1) for _ in range(rng.randint(1, 3))]
        return {rng.choice(["and", "or"]): children}
    op = rng.choice(OPS)
    return {"op": op, "left": _operand(rng, False), "right": _operand(rng, op == "in")}


def _mapping(rng: random.Random, keys: list[str]) -> dict[str, Any]:
    return {key: rng.choice(RUNTIME_VALUES) for key in keys if rng.random() < 0.75}


def test_residual_filter_agrees_with_evaluate() -> None:
    rng = random.Random(SEED)
    checked = 0
    for _ in range(RULES):
        rule = _rule(rng)
        try:
            validate_rule(rule)
        except RuleError:
            continue
        user = _mapping(rng, ATTRIBUTES)
        tenant = _mapping(rng, ATTRIBUTES) if rng.random() < 0.8 else None
        residual = residualize(rule, user, tenant)
        for _ in range(RECORDS_PER_RULE):
            record = _mapping(rng, FIELDS)
            ctx = RuleContext(record=record, user=user, tenant=tenant)
            assert _matches(residual, record) == evaluate(rule, ctx), (
                rule,
                user,
                tenant,
                record,
                residual,
            )
            checked += 1

    assert checked > 5000
