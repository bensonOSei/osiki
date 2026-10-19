"""Translate a residual filter tree into a SQLAlchemy WHERE clause."""

from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, false, or_, true

from osiki_sdk._decision import FilterResult

_NUMBERS = (int, float, Decimal)


def _class_matches(python_type: type, leaf_type: str) -> bool:
    if leaf_type == "string":
        return issubclass(python_type, str)
    if leaf_type == "boolean":
        return issubclass(python_type, bool)
    if leaf_type == "number":
        return issubclass(python_type, _NUMBERS) and not issubclass(python_type, bool)
    return False  # an unknown leaf type never matches


def _leaf(node: dict[str, Any], model: type[Any]) -> ColumnElement[bool]:
    column = getattr(model, str(node["field"]), None)
    if column is None:
        return false()
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        return false()
    if not _class_matches(python_type, node["type"]):
        return false()
    value = node["value"]
    op = node["op"]
    comparison: ColumnElement[bool]
    if op == "eq":
        comparison = column == value
    elif op == "ne":
        comparison = column != value
    elif op == "lt":
        comparison = column < value
    elif op == "lte":
        comparison = column <= value
    elif op == "gt":
        comparison = column > value
    elif op == "gte":
        comparison = column >= value
    elif op == "in":
        comparison = column.in_(value)
    elif op == "nin":
        comparison = column.not_in(value)
    else:
        return false()  # an unknown op never matches
    return and_(column.is_not(None), comparison)


def _node(node: dict[str, Any], model: type[Any]) -> ColumnElement[bool]:
    if "and" in node:
        return and_(true(), *[_node(child, model) for child in node["and"]])
    if "or" in node:
        return or_(false(), *[_node(child, model) for child in node["or"]])
    return _leaf(node, model)


def to_sqlalchemy(result: FilterResult, model: type[Any]) -> ColumnElement[bool]:
    """Return a WHERE clause for ``model``; unknown or mistyped fields never match."""
    if result.mode == "all":
        return true()
    if result.mode == "none" or result.filter is None:
        return false()
    return _node(result.filter, model)
