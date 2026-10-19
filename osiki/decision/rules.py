"""Record rule AST: validation, deny-safe evaluation and residual filters.

This module is pure (standard library only) and is vendored into the SDKs, so
its semantics are the contract every port must reproduce exactly.

Grammar (canonical JSON, stored and shipped as-is)::

    Rule     := {"and": [Rule, ...1+]} | {"or": [Rule, ...1+]} | {"not": Rule}
              | Compare
    Compare  := {"op": "eq"|"ne"|"lt"|"lte"|"gt"|"gte"|"in",
                 "left": Operand, "right": Operand}
    Operand  := {"ref": "<root>.<name>"} | {"value": Scalar | [Scalar, ...]}
    root     := "record" | "user" | "tenant"
    name     := [A-Za-z_][A-Za-z0-9_]{0,63}   (exactly one segment)
    Scalar   := string | number | boolean | null

A list literal is only valid as the right operand of ``in``.

References:
    ``record.<name>`` reads the record's top-level field. ``user.<name>`` and
    ``tenant.<name>`` read a key of the ``user`` / ``tenant`` mapping. Callers
    build those mappings as ``{"id": external_id, **attributes}`` with ``"id"``
    winning, so ``user.id`` and ``tenant.id`` are always the external ids and an
    attribute literally named ``id`` is shadowed.

Evaluation is three-valued (TRUE / FALSE / UNKNOWN) and deny-safe:
    * A ref that is missing (absent key, absent record or tenant) or ``None``
      makes its Compare UNKNOWN. A ``null`` literal behaves the same way.
    * Values fall into type classes: "boolean", "number" (int and float,
      compared numerically, NaN excluded) and "string". Anything else (lists
      outside the right side of ``in``, mappings, NaN, other objects) is
      uncomparable. Comparing across classes or with an uncomparable value is
      UNKNOWN, so ``True`` never equals ``1`` and ``"1"`` never equals ``1``.
    * Callers must pass JSON-native values in records and in the user and
      tenant mappings. ``datetime``, ``ObjectId``, ``Decimal`` and similar
      objects are uncomparable, so any Compare that touches them always denies.
    * Ordering ops are defined for numbers and strings (code point order);
      ordering booleans is UNKNOWN.
    * ``x in [v1, ..., vn]`` is the Kleene OR of ``x eq vi``: TRUE if some
      element equals ``x``, FALSE if every element is comparable and none
      equals, UNKNOWN otherwise. A right side that is not a list is UNKNOWN.
    * ``and`` / ``or`` / ``not`` follow Kleene logic (``not UNKNOWN`` is
      UNKNOWN). The top-level result is ``True`` only for TRUE.

``evaluate`` and ``residualize`` expect a rule that passed ``validate_rule``.

Residual filters:
    ``residualize`` substitutes the ``user`` / ``tenant`` refs, folds constants,
    pushes ``not`` down to the leaves and returns ``True`` (all records),
    ``False`` (none) or a tree of ``{"and": [...]}``, ``{"or": [...]}`` and
    ``{"field", "op", "value", "type"}`` leaves, where ``op`` is one of
    eq/ne/lt/lte/gt/gte/in/nin and ``type`` is "string", "number" or "boolean":
    the type class of ``value`` (for ``in`` / ``nin``, the single class shared
    by every list element).

    Translator contract: a leaf matches a record only when the field is
    present, non-null, of the leaf's ``type`` class (a boolean is never a
    number, NaN is never a number) and satisfies ``op`` / ``value``. So ``ne``
    and ``nin`` mean "present, of this type, and ...", never "missing or ...".
    Under that contract a record matches the tree exactly when ``evaluate``
    would return ``True``.
"""

import math
import operator
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

MAX_DEPTH = 16
MAX_NODES = 256

type FilterNode = dict[str, Any]

_TYPE_CLASSES = ("string", "number", "boolean")
_REF_PATTERN = re.compile(r"(record|user|tenant)\.[A-Za-z_][A-Za-z0-9_]{0,63}")
_LOGICAL_KEYS = ("and", "or")
_COMPARE_KEYS = {"op", "left", "right"}
_ORDERING_OPS = {"lt", "lte", "gt", "gte"}
_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
}
_VALID_OPS = {*_OPS, "in"}
_NEGATED_OP = {
    "eq": "ne",
    "ne": "eq",
    "lt": "gte",
    "gte": "lt",
    "lte": "gt",
    "gt": "lte",
}
_SWAPPED_SIDES_OP = {
    "eq": "eq",
    "ne": "ne",
    "lt": "gt",
    "gt": "lt",
    "lte": "gte",
    "gte": "lte",
}


class RuleError(ValueError):
    """A rule failed validation at ``path`` (JSONPath-like, e.g. ``$.and[1]``)."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


@dataclass(frozen=True)
class RuleContext:
    """Inputs for ``evaluate``. ``user`` / ``tenant`` carry ``"id"`` and attributes."""

    record: Mapping[str, Any] | None
    user: Mapping[str, Any]
    tenant: Mapping[str, Any] | None


class Tri(Enum):
    """Three-valued truth used internally by evaluation and residualization."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate_rule(rule: Any) -> None:
    """Raise ``RuleError`` unless ``rule`` is a well-formed rule AST."""
    _validate_node(rule, "$", 1, [0])


def _validate_node(node: Any, at: str, depth: int, node_count: list[int]) -> None:
    if depth > MAX_DEPTH:
        raise RuleError(at, f"rule depth exceeds {MAX_DEPTH}")
    node_count[0] += 1
    if node_count[0] > MAX_NODES:
        raise RuleError(at, f"rule has more than {MAX_NODES} nodes")
    if not isinstance(node, Mapping):
        raise RuleError(at, "rule must be an object")

    keys = set(node)
    if len(keys) == 1 and (key := next(iter(keys))) in _LOGICAL_KEYS:
        children = node[key]
        if not isinstance(children, list) or not children:
            raise RuleError(f"{at}.{key}", f"'{key}' takes a non-empty list of rules")
        for index, child in enumerate(children):
            _validate_node(child, f"{at}.{key}[{index}]", depth + 1, node_count)
    elif keys == {"not"}:
        _validate_node(node["not"], f"{at}.not", depth + 1, node_count)
    elif keys == _COMPARE_KEYS:
        _validate_compare(node, at)
    else:
        raise RuleError(at, f"unrecognised rule keys {sorted(map(str, keys))}")


def _validate_compare(node: Mapping[str, Any], at: str) -> None:
    op = node["op"]
    if not isinstance(op, str) or op not in _VALID_OPS:
        raise RuleError(f"{at}.op", f"unknown operator {op!r}")
    left = _validate_operand(node["left"], f"{at}.left")
    right = _validate_operand(node["right"], f"{at}.right")

    if "value" in left and "value" in right:
        raise RuleError(at, "a comparison needs at least one ref")
    if _is_record_ref(left) and _is_record_ref(right):
        raise RuleError(at, "cannot compare two record fields")
    if op == "in":
        if _is_record_ref(right):
            raise RuleError(at, "'in' cannot take a record ref on the right")
        if "value" in right and not isinstance(right["value"], list):
            raise RuleError(at, "'in' needs a list value on the right")
        if isinstance(left.get("value"), list):
            raise RuleError(at, "'in' cannot take a list value on the left")
    elif isinstance(left.get("value"), list) or isinstance(right.get("value"), list):
        raise RuleError(at, f"'{op}' cannot take a list value; only 'in' can")


def _validate_operand(operand: Any, at: str) -> Mapping[str, Any]:
    if not isinstance(operand, Mapping) or set(operand) not in ({"ref"}, {"value"}):
        raise RuleError(at, "operand must be exactly {'ref': ...} or {'value': ...}")
    if "ref" in operand:
        ref = operand["ref"]
        if not isinstance(ref, str) or not _REF_PATTERN.fullmatch(ref):
            raise RuleError(f"{at}.ref", f"invalid ref {ref!r}")
        return operand

    value = operand["value"]
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_scalar(item, f"{at}.value[{index}]")
    else:
        _validate_scalar(value, f"{at}.value")
    return operand


def _validate_scalar(value: Any, at: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise RuleError(at, "value must be a string, finite number, boolean or null")


def _is_record_ref(operand: Mapping[str, Any]) -> bool:
    return str(operand.get("ref", "")).startswith("record.")


# --------------------------------------------------------------------------
# Three-valued evaluation
# --------------------------------------------------------------------------


def evaluate(rule: Mapping[str, Any], ctx: RuleContext) -> bool:
    """Return ``True`` only when the validated ``rule`` is TRUE for ``ctx``."""
    return _evaluate(rule, ctx) is Tri.TRUE


def _evaluate(node: Mapping[str, Any], ctx: RuleContext) -> Tri:
    if "and" in node:
        return _kleene_and(_evaluate(child, ctx) for child in node["and"])
    if "or" in node:
        return _kleene_or(_evaluate(child, ctx) for child in node["or"])
    if "not" in node:
        return _kleene_not(_evaluate(node["not"], ctx))
    return _compare(
        node["op"], _resolve(node["left"], ctx), _resolve(node["right"], ctx)
    )


def _kleene_and(values: Iterable[Tri]) -> Tri:
    result = Tri.TRUE
    for value in values:
        if value is Tri.FALSE:
            return Tri.FALSE
        if value is Tri.UNKNOWN:
            result = Tri.UNKNOWN
    return result


def _kleene_or(values: Iterable[Tri]) -> Tri:
    result = Tri.FALSE
    for value in values:
        if value is Tri.TRUE:
            return Tri.TRUE
        if value is Tri.UNKNOWN:
            result = Tri.UNKNOWN
    return result


def _kleene_not(value: Tri) -> Tri:
    if value is Tri.UNKNOWN:
        return Tri.UNKNOWN
    return Tri.FALSE if value is Tri.TRUE else Tri.TRUE


def _resolve(operand: Mapping[str, Any], ctx: RuleContext) -> Any:
    """Return the operand's value; ``None`` stands for missing or null."""
    if "value" in operand:
        return operand["value"]
    root, name = operand["ref"].split(".", 1)
    source = {"record": ctx.record, "user": ctx.user, "tenant": ctx.tenant}[root]
    return None if source is None else source.get(name)


def _type_class(value: Any) -> str | None:
    """Return the comparison class of ``value``, or ``None`` if uncomparable."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) or (isinstance(value, float) and not math.isnan(value)):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def _compare(op: str, left: Any, right: Any) -> Tri:
    if op == "in":
        return _member(left, right)
    left_class = _type_class(left)
    if left_class is None or left_class != _type_class(right):
        return Tri.UNKNOWN
    if op in _ORDERING_OPS and left_class == "boolean":
        return Tri.UNKNOWN
    return Tri.TRUE if _OPS[op](left, right) else Tri.FALSE


def _member(item: Any, items: Any) -> Tri:
    if _type_class(item) is None or not isinstance(items, list):
        return Tri.UNKNOWN
    return _kleene_or(_compare("eq", item, element) for element in items)


# --------------------------------------------------------------------------
# Residual filters
# --------------------------------------------------------------------------


def residualize(
    rule: Mapping[str, Any],
    user: Mapping[str, Any],
    tenant: Mapping[str, Any] | None,
) -> FilterNode | bool:
    """Reduce a validated rule to a record filter for ``user`` in ``tenant``.

    Returns ``True`` (every record), ``False`` (no record) or a filter tree with
    no ``not`` nodes; see the module docstring for the leaf contract.
    """
    ctx = RuleContext(record=None, user=user, tenant=tenant)
    result = _residual(rule, ctx, negate=False)
    if isinstance(result, Tri):
        return result is Tri.TRUE
    return result


def _residual(
    node: Mapping[str, Any], ctx: RuleContext, negate: bool
) -> FilterNode | Tri:
    if "not" in node:
        return _residual(node["not"], ctx, not negate)
    for key in _LOGICAL_KEYS:
        if key in node:
            parts = [_residual(child, ctx, negate) for child in node[key]]
            is_and = (key == "and") != negate  # De Morgan under negation
            return _fold_and(parts) if is_and else _fold_or(parts)
    return _residual_compare(node, ctx, negate)


def _fold_and(parts: list[FilterNode | Tri]) -> FilterNode | Tri:
    filters = [part for part in parts if not isinstance(part, Tri)]
    constant = _kleene_and(part for part in parts if isinstance(part, Tri))
    if constant is not Tri.TRUE or not filters:
        return constant
    return filters[0] if len(filters) == 1 else {"and": filters}


def _fold_or(parts: list[FilterNode | Tri]) -> FilterNode | Tri:
    filters = [part for part in parts if not isinstance(part, Tri)]
    constant = _kleene_or(part for part in parts if isinstance(part, Tri))
    if constant is Tri.TRUE or not filters:
        return constant
    return filters[0] if len(filters) == 1 else {"or": filters}


def _residual_compare(
    node: Mapping[str, Any], ctx: RuleContext, negate: bool
) -> FilterNode | Tri:
    op, left, right = node["op"], node["left"], node["right"]
    if _is_record_ref(left):
        field_ref, other = left, right
    elif _is_record_ref(right):
        field_ref, other, op = right, left, _SWAPPED_SIDES_OP[op]
    else:
        result = _compare(op, _resolve(left, ctx), _resolve(right, ctx))
        return _kleene_not(result) if negate else result

    field = field_ref["ref"].split(".", 1)[1]
    value = _resolve(other, ctx)
    if op == "in":
        return _membership_leaf(field, value, negate)

    value_class = _type_class(value)
    if value_class is None or (op in _ORDERING_OPS and value_class == "boolean"):
        return Tri.UNKNOWN
    op = _NEGATED_OP[op] if negate else op
    return {"field": field, "op": op, "value": value, "type": value_class}


def _membership_leaf(field: str, items: Any, negate: bool) -> FilterNode | Tri:
    if not isinstance(items, list):
        return Tri.UNKNOWN
    if negate:
        return _not_in_leaf(field, items)
    by_class: dict[str, list[Any]] = {}
    for item in items:
        item_class = _type_class(item)
        if item_class is not None:  # null / uncomparable elements never match
            by_class.setdefault(item_class, []).append(item)
    leaves: list[FilterNode | Tri] = [
        {"field": field, "op": "in", "value": values, "type": item_class}
        for item_class, values in by_class.items()
    ]
    return _fold_or(leaves)


def _not_in_leaf(field: str, items: list[Any]) -> FilterNode | Tri:
    classes = {_type_class(item) for item in items}
    if not classes:
        # NOT IN [] holds for every comparable value, whatever its class.
        return _fold_or(
            [
                {"field": field, "op": "nin", "value": [], "type": item_class}
                for item_class in _TYPE_CLASSES
            ]
        )
    # NOT IN is TRUE only when every element is comparable with the field
    # value, so a list mixing type classes (or holding nulls) never matches.
    if None in classes or len(classes) > 1:
        return Tri.UNKNOWN
    (item_class,) = classes
    return {"field": field, "op": "nin", "value": list(items), "type": item_class}
