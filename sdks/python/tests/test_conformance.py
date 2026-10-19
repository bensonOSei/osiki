"""Run every shared JSON conformance fixture through the vendored decision core.

Mirrors the engine's runner (``tests/conformance/test_conformance.py``): exact
keys and full model equality. See ``conformance/README.md``.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from osiki_sdk._decision import (
    Decision,
    DecisionRequest,
    FilterResult,
    Snapshot,
    UserBundle,
    decide,
    list_filter,
    validate_rule,
)

ROOT = Path(__file__).resolve().parents[3] / "conformance"
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
