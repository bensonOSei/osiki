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
