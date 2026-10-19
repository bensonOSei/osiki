"""``to_mongo``: exact documents and behaviour under mongomock."""

import itertools
import json
from pathlib import Path
from typing import Any

import mongomock
import pytest

from osiki_sdk._decision import FilterResult
from osiki_sdk.filters import to_mongo

FILTERS = sorted(
    (Path(__file__).resolve().parents[3] / "conformance" / "filters").glob("*.json")
)
MISSING = object()
ARRAY = {"$type": "array"}


def _filter(node: dict[str, Any]) -> FilterResult:
    return FilterResult(mode="filter", filter=node)


def _leaf(op: str, value: Any, type_: str) -> dict[str, Any]:
    return {"field": "f", "op": op, "value": value, "type": type_}


@pytest.mark.parametrize(
    ("op", "mongo_op"),
    [
        ("eq", "$eq"),
        ("ne", "$ne"),
        ("lt", "$lt"),
        ("lte", "$lte"),
        ("gt", "$gt"),
        ("gte", "$gte"),
    ],
)
@pytest.mark.parametrize(
    ("type_", "mongo_type", "value"),
    [("string", "string", "x"), ("number", "number", 5), ("boolean", "bool", True)],
)
def test_leaf_exact_dict(
    op: str, mongo_op: str, type_: str, mongo_type: str, value: Any
) -> None:
    assert to_mongo(_filter(_leaf(op, value, type_))) == {
        "f": {"$not": ARRAY, "$type": mongo_type, mongo_op: value}
    }


@pytest.mark.parametrize(("op", "mongo_op"), [("in", "$in"), ("nin", "$nin")])
def test_list_ops_exact_dict(op: str, mongo_op: str) -> None:
    assert to_mongo(_filter(_leaf(op, [1, 2], "number"))) == {
        "f": {"$not": ARRAY, "$type": "number", mongo_op: [1, 2]}
    }


def test_all_none_modes() -> None:
    assert to_mongo(FilterResult(mode="all")) == {}
    assert to_mongo(FilterResult(mode="none")) is None
    assert to_mongo(FilterResult(mode="filter", filter=None)) is None


def test_and_or_nesting() -> None:
    a, b = _leaf("eq", "x", "string"), _leaf("gt", 1, "number")
    assert to_mongo(_filter({"and": [a, {"or": [a, b]}]})) == {
        "$and": [
            {"f": {"$not": ARRAY, "$type": "string", "$eq": "x"}},
            {
                "$or": [
                    {"f": {"$not": ARRAY, "$type": "string", "$eq": "x"}},
                    {"f": {"$not": ARRAY, "$type": "number", "$gt": 1}},
                ]
            },
        ]
    }


# --- Review Focus 5: behaviour against the leaf contract -------------------

POOL: list[Any] = [
    *[MISSING, None, "a", "b", "t1", "1", 0, 1, 2, 100, 2.5, True, False],
    *[["a"], [1, "a"], [], [True], {"x": 1}],
]


def _cls(value: Any) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def _leaf_matches(leaf: dict[str, Any], doc: dict[str, Any]) -> bool:
    """Independent reference interpreter of the README leaf contract."""
    got = doc.get(leaf["field"], MISSING)
    if got is MISSING or got is None or _cls(got) != leaf["type"]:
        return False
    op, want = leaf["op"], leaf["value"]
    if op in ("in", "nin"):
        found = any(_cls(e) == leaf["type"] and e == got for e in want)
        return found if op == "in" else not found
    if op == "eq":
        return bool(got == want)
    if op == "ne":
        return bool(got != want)
    if leaf["type"] == "boolean":
        return False
    return {
        "lt": got < want,
        "lte": got <= want,
        "gt": got > want,
        "gte": got >= want,
    }[op]


def _node_matches(node: dict[str, Any], doc: dict[str, Any]) -> bool:
    if "and" in node:
        return all(_node_matches(n, doc) for n in node["and"])
    if "or" in node:
        return any(_node_matches(n, doc) for n in node["or"])
    return _leaf_matches(node, doc)


def _fields(node: dict[str, Any]) -> set[str]:
    if "and" in node or "or" in node:
        return {f for n in node.get("and", node.get("or")) for f in _fields(n)}
    return {node["field"]}


def _docs(fields: list[str]) -> list[dict[str, Any]]:
    docs = []
    for i, combo in enumerate(itertools.product(POOL, repeat=len(fields))):
        doc: dict[str, Any] = {"_id": i}
        doc.update({f: v for f, v in zip(fields, combo) if v is not MISSING})
        docs.append(doc)
    return docs


@pytest.mark.parametrize("fixture", FILTERS, ids=lambda p: p.stem)
def test_fixture_matches_reference_semantics(fixture: Path) -> None:
    expected = FilterResult.model_validate(json.loads(fixture.read_text())["expected"])
    query = to_mongo(expected)
    if expected.mode == "none":
        assert query is None
        return
    assert query is not None
    if expected.mode == "all":
        assert query == {}
        return
    assert expected.filter is not None
    docs = _docs(sorted(_fields(expected.filter)))
    coll = mongomock.MongoClient().db.c
    coll.insert_many(docs)
    got = {d["_id"] for d in coll.find(query)}
    want = {d["_id"] for d in docs if _node_matches(expected.filter, d)}
    assert got == want


def test_type_guard_cases_explicit() -> None:
    coll = mongomock.MongoClient().db.c
    coll.insert_many(
        [
            {"_id": 1, "f": 1},
            {"_id": 2, "f": True},
            {"_id": 3, "f": "1"},
            {"_id": 4, "f": None},
            {"_id": 5},
            {"_id": 6, "f": 1.0},
        ]
    )

    def ids(node: dict[str, Any]) -> set[int]:
        query = to_mongo(_filter(node))
        assert query is not None
        return {d["_id"] for d in coll.find(query)}

    assert ids(_leaf("eq", 1, "number")) == {1, 6}
    assert ids(_leaf("eq", True, "boolean")) == {2}
    assert ids(_leaf("eq", "1", "string")) == {3}
    assert ids(_leaf("ne", 5, "number")) == {1, 6}
    assert ids(_leaf("nin", [9], "number")) == {1, 6}


def test_array_and_embedded_fields_never_match() -> None:
    coll = mongomock.MongoClient().db.c
    coll.insert_many(
        [
            {"_id": 1, "f": ["x", "y"]},
            {"_id": 2, "f": ["y", 5]},
            {"_id": 3, "f": [1, True]},
            {"_id": 4, "f": []},
            {"_id": 5, "f": {"x": 1}},
            {"_id": 6, "f": "x"},
            {"_id": 7, "f": 1},
        ]
    )

    def ids(node: dict[str, Any]) -> set[int]:
        query = to_mongo(_filter(node))
        assert query is not None
        return {d["_id"] for d in coll.find(query)}

    assert ids(_leaf("eq", "x", "string")) == {6}
    assert ids(_leaf("ne", "z", "string")) == {6}
    assert ids(_leaf("nin", ["x"], "string")) == set()
    assert ids(_leaf("in", ["x", "y"], "string")) == {6}
    assert ids(_leaf("eq", 1, "number")) == {7}
    assert ids(_leaf("ne", 9, "number")) == {7}
    assert ids(_leaf("in", [1, 5], "number")) == {7}
    assert ids(_leaf("eq", True, "boolean")) == set()


@pytest.mark.parametrize(
    "node",
    [
        _leaf("regex", [1], "number"),
        _leaf("contains", 1, "number"),
        _leaf("eq", 1, "date"),
        _leaf("eq", "x", "text"),
    ],
)
def test_unknown_op_or_type_matches_nothing(node: dict[str, Any]) -> None:
    query = to_mongo(_filter(node))
    assert query == {"f": {"$in": []}}
    collection = mongomock.MongoClient().db.c
    collection.insert_many([{"f": 1}, {"f": "x"}, {"f": [1]}, {"f": None}, {}])
    assert list(collection.find(query)) == []
    # Inside an or, it only removes its own branch.
    either = to_mongo(_filter({"or": [node, _leaf("eq", 1, "number")]}))
    assert [d["f"] for d in collection.find(either)] == [1]
