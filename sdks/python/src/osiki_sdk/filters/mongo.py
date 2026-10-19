"""Translate a residual filter tree into a MongoDB query document."""

from typing import Any

from osiki_sdk._decision import FilterResult

_TYPES = {"string": "string", "number": "number", "boolean": "bool"}
_OPS = {
    "eq": "$eq",
    "ne": "$ne",
    "lt": "$lt",
    "lte": "$lte",
    "gt": "$gt",
    "gte": "$gte",
    "in": "$in",
    "nin": "$nin",
}


def _node(node: dict[str, Any]) -> dict[str, Any]:
    if "and" in node:
        return {"$and": [_node(child) for child in node["and"]]}
    if "or" in node:
        return {"$or": [_node(child) for child in node["or"]]}
    field = str(node["field"])
    mongo_type = _TYPES.get(str(node.get("type")))
    mongo_op = _OPS.get(str(node.get("op")))
    if mongo_type is None or mongo_op is None:
        # An unknown type or op never matches (``$in: []`` matches nothing).
        return {field: {"$in": []}}
    # ``$type`` makes a missing, null or wrongly typed field match nothing, so
    # ``ne``/``nin`` never match them and a boolean is never a number. Mongo
    # looks inside arrays for ``$type`` and comparisons, but the leaf contract
    # makes a list-valued field uncomparable, so arrays are excluded outright.
    return {
        field: {
            "$not": {"$type": "array"},
            "$type": mongo_type,
            mongo_op: node["value"],
        }
    }


def to_mongo(result: FilterResult) -> dict[str, Any] | None:
    """Return a Mongo query, ``{}`` for everything, or ``None`` for nothing."""
    if result.mode == "all":
        return {}
    if result.mode == "none" or result.filter is None:
        return None
    return _node(result.filter)
