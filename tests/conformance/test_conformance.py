"""Run every JSON conformance fixture through the reference implementation.

SDK ports run the same files; see ``conformance/README.md``.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from osiki.decision.decide import decide, list_filter
from osiki.decision.models import (
    Decision,
    DecisionRequest,
    FilterResult,
    Snapshot,
    UserBundle,
)
from osiki.decision.rules import validate_rule

ROOT = Path(__file__).resolve().parents[2] / "conformance"
DECISIONS = sorted((ROOT / "decisions").glob("*.json"))
FILTERS = sorted((ROOT / "filters").glob("*.json"))
DECISION_KEYS = {"name", "snapshot", "bundle", "request", "expected"}
FILTER_KEYS = {
    "name",
    "snapshot",
    "bundle",
    "resource",
    "action",
    "scope",
    "now",
    "expected",
}


def _load(fixture: Path, keys: set[str]) -> dict[str, Any]:
    case: dict[str, Any] = json.loads(fixture.read_text())
    assert set(case) == keys
    assert case["name"] == fixture.stem
    for rule in case["snapshot"]["conditions"].values():
        validate_rule(rule)
    return case


def test_fixtures_exist() -> None:
    assert len(DECISIONS) >= 100
    assert len(FILTERS) >= 25


def _leaves(node: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("and", "or"):
        if key in node:
            return [leaf for child in node[key] for leaf in _leaves(child)]
    return [node]


def test_filter_fixtures_cover_every_leaf_op_and_type() -> None:
    leaves = [
        leaf
        for fixture in FILTERS
        if (expected := json.loads(fixture.read_text())["expected"])["filter"]
        for leaf in _leaves(expected["filter"])
    ]

    assert all(set(leaf) == {"field", "op", "value", "type"} for leaf in leaves)
    assert {leaf["op"] for leaf in leaves} == {
        "eq",
        "ne",
        "lt",
        "lte",
        "gt",
        "gte",
        "in",
        "nin",
    }
    assert {leaf["type"] for leaf in leaves} == {"string", "number", "boolean"}


@pytest.mark.parametrize("fixture", DECISIONS, ids=lambda f: f.stem)
def test_decision_fixture(fixture: Path) -> None:
    case = _load(fixture, DECISION_KEYS)
    assert set(case["expected"]) == set(Decision.model_fields)

    result = decide(
        Snapshot.model_validate(case["snapshot"]),
        UserBundle.model_validate(case["bundle"]),
        DecisionRequest.model_validate(case["request"]),
    )

    assert result == Decision.model_validate(case["expected"])


@pytest.mark.parametrize("fixture", FILTERS, ids=lambda f: f.stem)
def test_filter_fixture(fixture: Path) -> None:
    case = _load(fixture, FILTER_KEYS)
    assert set(case["expected"]) == set(FilterResult.model_fields)

    result = list_filter(
        Snapshot.model_validate(case["snapshot"]),
        UserBundle.model_validate(case["bundle"]),
        case["resource"],
        case["action"],
        case["scope"],
        case["now"],
    )

    assert result == FilterResult.model_validate(case["expected"])
