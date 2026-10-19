"""The Task A3 scope truth table, minus the membership row (decide checks it)."""

import pytest

from osiki.decision.scope import scope_matches


@pytest.mark.parametrize(
    ("assignment_scope", "request_scope", "expected"),
    [
        # A.tenant_id == R.tenant_id: every other key in A must equal R's
        ({"tenant_id": "t"}, {"tenant_id": "t"}, True),
        ({"tenant_id": "t", "region": "us"}, {"tenant_id": "t", "region": "us"}, True),
        ({"tenant_id": "t", "region": "us"}, {"tenant_id": "t", "region": "eu"}, False),
        ({"tenant_id": "t", "region": "us"}, {"tenant_id": "t"}, False),
        # A.tenant_id != R.tenant_id: never
        ({"tenant_id": "t"}, {"tenant_id": "u"}, False),
        # A has a tenant, R has none: never
        ({"tenant_id": "t"}, {}, False),
        ({"tenant_id": "t"}, {"region": "us"}, False),
        # project-wide A in a tenant request (membership is checked by decide)
        ({}, {"tenant_id": "t"}, True),
        ({"region": "us"}, {"tenant_id": "t", "region": "us"}, True),
        ({"region": "us"}, {"tenant_id": "t", "region": "eu"}, False),
        # neither has a tenant
        ({}, {}, True),
        ({"region": "us"}, {"region": "us", "branch_id": "b"}, True),
        ({"region": "us"}, {}, False),
    ],
)
def test_scope_matches_truth_table(
    assignment_scope: dict[str, str], request_scope: dict[str, str], expected: bool
) -> None:
    assert scope_matches(assignment_scope, request_scope) is expected
