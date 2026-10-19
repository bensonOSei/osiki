def test_matches_returns_true_for_none_user_scope(scope_matcher) -> None:
    result = scope_matcher.matches(None, {"tenant_id": "t1"})
    assert result is True


def test_matches_returns_true_for_empty_user_scope(scope_matcher) -> None:
    result = scope_matcher.matches({}, {"tenant_id": "t1"})
    assert result is True


def test_matches_exact_scope_match(scope_matcher) -> None:
    result = scope_matcher.matches(
        {"tenant_id": "t1", "region": "us-east"},
        {"tenant_id": "t1", "region": "us-east"},
    )
    assert result is True


def test_matches_fails_missing_key(scope_matcher) -> None:
    result = scope_matcher.matches(
        {"tenant_id": "t1", "region": "us-east"},
        {"tenant_id": "t1"},
    )
    assert result is False


def test_matches_fails_wrong_value(scope_matcher) -> None:
    result = scope_matcher.matches(
        {"tenant_id": "t1"},
        {"tenant_id": "t2"},
    )
    assert result is False


def test_matches_subset_scope(scope_matcher) -> None:
    result = scope_matcher.matches(
        {"tenant_id": "t1"},
        {"tenant_id": "t1", "region": "us-east", "branch_id": "b1"},
    )
    assert result is True


def test_matches_with_extra_request_keys(scope_matcher) -> None:
    result = scope_matcher.matches(
        {"tenant_id": "t1"},
        {"tenant_id": "t1", "extra_key": "value"},
    )
    assert result is True


def test_matches_multiple_scope_keys(scope_matcher) -> None:
    result = scope_matcher.matches(
        {"tenant_id": "t1", "region": "us-east", "branch_id": "b1"},
        {
            "tenant_id": "t1",
            "region": "us-east",
            "branch_id": "b1",
            "department": "eng",
        },
    )
    assert result is True


# --- Tenant truth table (A = assignment scope, R = request scope) ---


def test_tenant_assignment_matches_same_tenant_request(scope_matcher) -> None:
    assert scope_matcher.matches({"tenant_id": "t"}, {"tenant_id": "t"}) is True


def test_tenant_assignment_requires_other_keys_to_match(scope_matcher) -> None:
    assignment = {"tenant_id": "t", "region": "eu"}
    assert (
        scope_matcher.matches(assignment, {"tenant_id": "t", "region": "us"}) is False
    )
    assert scope_matcher.matches(assignment, {"tenant_id": "t", "region": "eu"}) is True


def test_tenant_assignment_never_matches_other_tenant(scope_matcher) -> None:
    assert scope_matcher.matches({"tenant_id": "t"}, {"tenant_id": "u"}) is False


def test_tenant_assignment_never_matches_tenantless_request(scope_matcher) -> None:
    assert scope_matcher.matches({"tenant_id": "t"}, {}) is False
    assert scope_matcher.matches({"tenant_id": "t"}, {"region": "eu"}) is False


def test_project_wide_assignment_matches_tenant_request(scope_matcher) -> None:
    # Membership of the tenant is enforced by the authorization service.
    assert scope_matcher.matches({}, {"tenant_id": "t"}) is True
    assert scope_matcher.matches({"region": "eu"}, {"tenant_id": "t"}) is False
    assert (
        scope_matcher.matches({"region": "eu"}, {"tenant_id": "t", "region": "eu"})
        is True
    )


def test_project_wide_assignment_matches_tenantless_request(scope_matcher) -> None:
    assert scope_matcher.matches({}, {}) is True
    assert scope_matcher.matches({"region": "eu"}, {"region": "eu"}) is True
    assert scope_matcher.matches({"region": "eu"}, {}) is False
