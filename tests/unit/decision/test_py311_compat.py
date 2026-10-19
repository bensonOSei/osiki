"""``osiki/decision`` is vendored into an SDK that supports Python 3.11."""

import ast
from pathlib import Path

import pytest

import osiki.decision

DECISION_DIR = Path(osiki.decision.__file__).parent
SOURCES = sorted(DECISION_DIR.glob("*.py"))


def test_decision_package_has_sources() -> None:
    assert SOURCES


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_decision_package_is_311_compatible(source: Path) -> None:
    tree = ast.parse(source.read_text(), feature_version=(3, 11))

    assert not [n for n in ast.walk(tree) if isinstance(n, ast.TypeAlias)]
    assert not [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.ClassDef) and n.type_params
    ]
