import pytest
from beanie import PydanticObjectId

from osiki.models.base import Scope
from osiki.models.constraint import ConstraintConfig, ConstraintType, ScopeLevel
from tests.conftest import (
    make_constraint,
    make_group_role,
    make_role,
    make_user_group,
    make_user_role,
)


async def test_validate_passes_no_constraints(constraint_validator) -> None:
    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(PydanticObjectId()),
        scope={},
    )
    assert result.valid is True


async def test_mutual_exclusion_passes_no_conflict(
    constraint_validator,
    mock_constraint_repository,
) -> None:
    role_a = PydanticObjectId()
    role_b = PydanticObjectId()
    role_c = PydanticObjectId()

    constraint = make_constraint(
        name="exclusive-roles",
        constraint_type=ConstraintType.MUTUAL_EXCLUSION,
        config=ConstraintConfig(role_ids=[role_a, role_b]),
    )
    await mock_constraint_repository.create(constraint)

    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(role_c),
        scope={},
    )
    assert result.valid is True


async def test_mutual_exclusion_passes_first_role(
    constraint_validator,
    mock_constraint_repository,
) -> None:
    role_a = PydanticObjectId()
    role_b = PydanticObjectId()

    constraint = make_constraint(
        name="exclusive-roles",
        constraint_type=ConstraintType.MUTUAL_EXCLUSION,
        config=ConstraintConfig(role_ids=[role_a, role_b]),
    )
    await mock_constraint_repository.create(constraint)

    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(role_a),
        scope={},
    )
    assert result.valid is True


async def test_mutual_exclusion_fails_has_conflicting_role(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    user_id = PydanticObjectId()
    role_a = PydanticObjectId()
    role_b = PydanticObjectId()

    constraint = make_constraint(
        name="exclusive-roles",
        constraint_type=ConstraintType.MUTUAL_EXCLUSION,
        config=ConstraintConfig(role_ids=[role_a, role_b]),
    )
    await mock_constraint_repository.create(constraint)

    user_role = make_user_role(user_id=user_id, role_id=role_a)
    await mock_user_role_repository.create(user_role)

    result = await constraint_validator.validate(
        user_id=str(user_id),
        role_id=str(role_b),
        scope={},
    )
    assert result.valid is False
    assert result.constraint_name == "exclusive-roles"
    assert result.reason == "User already has a mutually exclusive role"


async def test_mutual_exclusion_multiple_conflict_sets(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    user_id = PydanticObjectId()
    role_a = PydanticObjectId()
    role_b = PydanticObjectId()
    role_c = PydanticObjectId()
    role_d = PydanticObjectId()

    constraint1 = make_constraint(
        name="exclusive-1",
        constraint_type=ConstraintType.MUTUAL_EXCLUSION,
        config=ConstraintConfig(role_ids=[role_a, role_b]),
    )
    constraint2 = make_constraint(
        name="exclusive-2",
        constraint_type=ConstraintType.MUTUAL_EXCLUSION,
        config=ConstraintConfig(role_ids=[role_c, role_d]),
    )
    await mock_constraint_repository.create(constraint1)
    await mock_constraint_repository.create(constraint2)

    user_role = make_user_role(user_id=user_id, role_id=role_c)
    await mock_user_role_repository.create(user_role)

    result = await constraint_validator.validate(
        user_id=str(user_id),
        role_id=str(role_d),
        scope={},
    )
    assert result.valid is False
    assert result.constraint_name == "exclusive-2"


async def test_cardinality_passes_under_limit(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    role_id = PydanticObjectId()
    user1 = PydanticObjectId()
    user2 = PydanticObjectId()

    constraint = make_constraint(
        name="max-3-admins",
        constraint_type=ConstraintType.CARDINALITY,
        config=ConstraintConfig(
            role_id=role_id,
            max_assignments=3,
            scope_level=ScopeLevel.GLOBAL,
        ),
    )
    await mock_constraint_repository.create(constraint)

    ur1 = make_user_role(user_id=user1, role_id=role_id)
    await mock_user_role_repository.create(ur1)

    result = await constraint_validator.validate(
        user_id=str(user2),
        role_id=str(role_id),
        scope={},
    )
    assert result.valid is True


async def test_cardinality_fails_at_limit(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    role_id = PydanticObjectId()

    constraint = make_constraint(
        name="max-2-admins",
        constraint_type=ConstraintType.CARDINALITY,
        config=ConstraintConfig(
            role_id=role_id,
            max_assignments=2,
            scope_level=ScopeLevel.GLOBAL,
        ),
    )
    await mock_constraint_repository.create(constraint)

    for _ in range(2):
        ur = make_user_role(user_id=PydanticObjectId(), role_id=role_id)
        await mock_user_role_repository.create(ur)

    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(role_id),
        scope={},
    )
    assert result.valid is False
    assert result.constraint_name == "max-2-admins"
    assert "Maximum 2 assignments reached" in (result.reason or "")


async def test_cardinality_global_scope(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    role_id = PydanticObjectId()

    constraint = make_constraint(
        name="max-1-global",
        constraint_type=ConstraintType.CARDINALITY,
        config=ConstraintConfig(
            role_id=role_id,
            max_assignments=1,
            scope_level=ScopeLevel.GLOBAL,
        ),
    )
    await mock_constraint_repository.create(constraint)

    ur = make_user_role(
        user_id=PydanticObjectId(), role_id=role_id, scope=Scope(tenant_id="t1")
    )
    await mock_user_role_repository.create(ur)

    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(role_id),
        scope={"tenant_id": "t2"},
    )
    assert result.valid is False


async def test_cardinality_per_tenant_scope(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    role_id = PydanticObjectId()

    constraint = make_constraint(
        name="max-1-per-tenant",
        constraint_type=ConstraintType.CARDINALITY,
        config=ConstraintConfig(
            role_id=role_id,
            max_assignments=1,
            scope_level=ScopeLevel.PER_TENANT,
        ),
    )
    await mock_constraint_repository.create(constraint)

    ur = make_user_role(
        user_id=PydanticObjectId(), role_id=role_id, scope=Scope(tenant_id="t1")
    )
    await mock_user_role_repository.create(ur)

    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(role_id),
        scope={"tenant_id": "t2"},
    )
    assert result.valid is True


async def test_cardinality_per_tenant_no_tenant_id(
    constraint_validator,
    mock_constraint_repository,
) -> None:
    role_id = PydanticObjectId()

    constraint = make_constraint(
        name="max-1-per-tenant",
        constraint_type=ConstraintType.CARDINALITY,
        config=ConstraintConfig(
            role_id=role_id,
            max_assignments=1,
            scope_level=ScopeLevel.PER_TENANT,
        ),
    )
    await mock_constraint_repository.create(constraint)

    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(role_id),
        scope={},
    )
    assert result.valid is True


async def test_cardinality_ignores_other_roles(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    role_a = PydanticObjectId()
    role_b = PydanticObjectId()

    constraint = make_constraint(
        name="max-1-role-a",
        constraint_type=ConstraintType.CARDINALITY,
        config=ConstraintConfig(
            role_id=role_a,
            max_assignments=1,
            scope_level=ScopeLevel.GLOBAL,
        ),
    )
    await mock_constraint_repository.create(constraint)

    ur = make_user_role(user_id=PydanticObjectId(), role_id=role_a)
    await mock_user_role_repository.create(ur)

    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(role_b),
        scope={},
    )
    assert result.valid is True


async def test_prerequisite_passes_has_required_role(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    user_id = PydanticObjectId()
    prereq_role = PydanticObjectId()
    target_role = PydanticObjectId()

    constraint = make_constraint(
        name="requires-base",
        constraint_type=ConstraintType.PREREQUISITE,
        config=ConstraintConfig(role_id=target_role, requires_role_id=prereq_role),
    )
    await mock_constraint_repository.create(constraint)

    ur = make_user_role(user_id=user_id, role_id=prereq_role)
    await mock_user_role_repository.create(ur)

    result = await constraint_validator.validate(
        user_id=str(user_id),
        role_id=str(target_role),
        scope={},
    )
    assert result.valid is True


async def test_prerequisite_fails_missing_role(
    constraint_validator,
    mock_constraint_repository,
) -> None:
    prereq_role = PydanticObjectId()
    target_role = PydanticObjectId()

    constraint = make_constraint(
        name="requires-base",
        constraint_type=ConstraintType.PREREQUISITE,
        config=ConstraintConfig(role_id=target_role, requires_role_id=prereq_role),
    )
    await mock_constraint_repository.create(constraint)

    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(target_role),
        scope={},
    )
    assert result.valid is False
    assert result.constraint_name == "requires-base"
    assert result.reason == "Prerequisite role not assigned"


async def test_prerequisite_passes_no_required_role(
    constraint_validator,
    mock_constraint_repository,
) -> None:
    target_role = PydanticObjectId()

    constraint = make_constraint(
        name="no-prereq",
        constraint_type=ConstraintType.PREREQUISITE,
        config=ConstraintConfig(role_id=target_role, requires_role_id=None),
    )
    await mock_constraint_repository.create(constraint)

    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(target_role),
        scope={},
    )
    assert result.valid is True


async def test_prerequisite_different_user_same_role(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    user1 = PydanticObjectId()
    user2 = PydanticObjectId()
    prereq_role = PydanticObjectId()
    target_role = PydanticObjectId()

    constraint = make_constraint(
        name="requires-base",
        constraint_type=ConstraintType.PREREQUISITE,
        config=ConstraintConfig(role_id=target_role, requires_role_id=prereq_role),
    )
    await mock_constraint_repository.create(constraint)

    ur = make_user_role(user_id=user1, role_id=prereq_role)
    await mock_user_role_repository.create(ur)

    result = await constraint_validator.validate(
        user_id=str(user2),
        role_id=str(target_role),
        scope={},
    )
    assert result.valid is False


async def test_validate_checks_all_constraint_types(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    user_id = PydanticObjectId()
    role_a = PydanticObjectId()
    role_b = PydanticObjectId()
    prereq_role = PydanticObjectId()

    c1 = make_constraint(
        name="exclusive",
        constraint_type=ConstraintType.MUTUAL_EXCLUSION,
        config=ConstraintConfig(role_ids=[role_a, role_b]),
    )
    c2 = make_constraint(
        name="max-admins",
        constraint_type=ConstraintType.CARDINALITY,
        config=ConstraintConfig(
            role_id=role_a, max_assignments=10, scope_level=ScopeLevel.GLOBAL
        ),
    )
    c3 = make_constraint(
        name="requires-base",
        constraint_type=ConstraintType.PREREQUISITE,
        config=ConstraintConfig(role_id=role_a, requires_role_id=prereq_role),
    )
    await mock_constraint_repository.create(c1)
    await mock_constraint_repository.create(c2)
    await mock_constraint_repository.create(c3)

    ur = make_user_role(user_id=user_id, role_id=prereq_role)
    await mock_user_role_repository.create(ur)

    result = await constraint_validator.validate(
        user_id=str(user_id),
        role_id=str(role_a),
        scope={},
    )
    assert result.valid is True


async def test_validate_returns_first_violation(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    user_id = PydanticObjectId()
    role_a = PydanticObjectId()
    role_b = PydanticObjectId()
    prereq_role = PydanticObjectId()

    c1 = make_constraint(
        name="exclusive",
        constraint_type=ConstraintType.MUTUAL_EXCLUSION,
        config=ConstraintConfig(role_ids=[role_a, role_b]),
    )
    c2 = make_constraint(
        name="requires-base",
        constraint_type=ConstraintType.PREREQUISITE,
        config=ConstraintConfig(role_id=role_b, requires_role_id=prereq_role),
    )
    await mock_constraint_repository.create(c1)
    await mock_constraint_repository.create(c2)

    ur = make_user_role(user_id=user_id, role_id=role_a)
    await mock_user_role_repository.create(ur)

    result = await constraint_validator.validate(
        user_id=str(user_id),
        role_id=str(role_b),
        scope={},
    )
    assert result.valid is False
    assert result.constraint_name == "exclusive"


async def test_validate_success_all_pass(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
) -> None:
    user_id = PydanticObjectId()
    role_a = PydanticObjectId()
    prereq_role = PydanticObjectId()

    c1 = make_constraint(
        name="max-admins",
        constraint_type=ConstraintType.CARDINALITY,
        config=ConstraintConfig(
            role_id=role_a, max_assignments=10, scope_level=ScopeLevel.GLOBAL
        ),
    )
    c2 = make_constraint(
        name="requires-base",
        constraint_type=ConstraintType.PREREQUISITE,
        config=ConstraintConfig(role_id=role_a, requires_role_id=prereq_role),
    )
    await mock_constraint_repository.create(c1)
    await mock_constraint_repository.create(c2)

    ur = make_user_role(user_id=user_id, role_id=prereq_role)
    await mock_user_role_repository.create(ur)

    result = await constraint_validator.validate(
        user_id=str(user_id),
        role_id=str(role_a),
        scope={},
    )
    assert result.valid is True


async def test_cardinality_per_scope_level(
    constraint_validator,
    mock_constraint_repository,
) -> None:
    """Test cardinality with PER_SCOPE level"""
    role_id = PydanticObjectId()

    constraint = make_constraint(
        name="per-scope-constraint",
        constraint_type=ConstraintType.CARDINALITY,
        config=ConstraintConfig(
            role_id=role_id,
            max_assignments=1,
            scope_level=ScopeLevel.PER_SCOPE,
        ),
    )
    await mock_constraint_repository.create(constraint)

    result = await constraint_validator.validate(
        user_id=str(PydanticObjectId()),
        role_id=str(role_id),
        scope={"tenant_id": "t1", "region": "us"},
    )
    # PER_SCOPE not implemented, so count=0 and validation passes
    assert result.valid is True


# --- Tenant scope ---
# A held role counts when its scope overlaps the new assignment's. For a
# prerequisite (a permit) that means held project-wide or in the same tenant;
# a project-wide assignment needs a project-wide prerequisite. For mutual
# exclusion (a block) scopes overlap unless both are in different tenants.

PREREQ, TARGET = PydanticObjectId(), PydanticObjectId()
SCOPE_CASES = [
    # (held tenant, assigned tenant, prerequisite satisfied, exclusion blocks)
    ("b", "a", False, False),
    (None, "a", True, True),
    ("a", "a", True, True),
    ("a", None, False, True),
    (None, None, True, True),
]


async def _hold(repo, user_id: PydanticObjectId, tenant: str | None) -> None:
    await repo.create(
        make_user_role(user_id=user_id, role_id=PREREQ, scope=Scope(tenant_id=tenant))
    )


def _scope(tenant: str | None) -> dict[str, str]:
    return {"tenant_id": tenant} if tenant else {}


@pytest.mark.parametrize(("held", "assigned", "satisfied", "_"), SCOPE_CASES)
async def test_prerequisite_respects_tenant_scope(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
    held: str | None,
    assigned: str | None,
    satisfied: bool,
    _: bool,
) -> None:
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(
        make_constraint(
            name="target-requires-prereq",
            constraint_type=ConstraintType.PREREQUISITE,
            config=ConstraintConfig(role_id=TARGET, requires_role_id=PREREQ),
        )
    )
    await _hold(mock_user_role_repository, user_id, held)

    result = await constraint_validator.validate(
        str(user_id), str(TARGET), _scope(assigned)
    )

    assert result.valid is satisfied


@pytest.mark.parametrize(("held", "assigned", "_", "blocks"), SCOPE_CASES)
async def test_mutual_exclusion_respects_tenant_scope(
    constraint_validator,
    mock_constraint_repository,
    mock_user_role_repository,
    held: str | None,
    assigned: str | None,
    _: bool,
    blocks: bool,
) -> None:
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(
        make_constraint(
            name="exclusive",
            constraint_type=ConstraintType.MUTUAL_EXCLUSION,
            config=ConstraintConfig(role_ids=[PREREQ, TARGET]),
        )
    )
    await _hold(mock_user_role_repository, user_id, held)

    result = await constraint_validator.validate(
        str(user_id), str(TARGET), _scope(assigned)
    )

    assert result.valid is not blocks


# -- tenant roles, group-held roles, expiry, per_scope (M3a task 8) ----------


def _exclusive(role_a: PydanticObjectId, role_b: PydanticObjectId):
    return make_constraint(
        name="exclusive",
        constraint_type=ConstraintType.MUTUAL_EXCLUSION,
        config=ConstraintConfig(role_ids=[role_a, role_b]),
    )


async def _join_group_with_role(
    env, user_id: PydanticObjectId, role_id: PydanticObjectId, **kwargs
) -> None:
    group_id = PydanticObjectId()
    await env["user_groups"].create(make_user_group(user_id, group_id))
    group_role = make_group_role(group_id, role_id, **kwargs)
    await env["group_roles"].create(group_role)


@pytest.fixture
def env(mock_user_group_repository, mock_group_role_repository):
    return {
        "user_groups": mock_user_group_repository,
        "group_roles": mock_group_role_repository,
    }


async def test_mutual_exclusion_sees_group_held_role(
    constraint_validator, mock_constraint_repository, env
) -> None:
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(_exclusive(PREREQ, TARGET))
    await _join_group_with_role(env, user_id, PREREQ)

    result = await constraint_validator.validate(str(user_id), str(TARGET), {})

    assert result.valid is False
    assert result.constraint_name == "exclusive"
    assert result.reason == "User already has a mutually exclusive role"


async def test_mutual_exclusion_ignores_expired_group_role(
    constraint_validator, mock_constraint_repository, env
) -> None:
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(_exclusive(PREREQ, TARGET))
    await _join_group_with_role(env, user_id, PREREQ)
    group_role = env["group_roles"]._scoped()[0]
    group_role.expires_at = 50.0

    result = await constraint_validator.validate(
        str(user_id), str(TARGET), {}, now=100.0
    )
    assert result.valid is True

    held = await constraint_validator.validate(str(user_id), str(TARGET), {}, now=10.0)
    assert held.valid is False


async def test_mutual_exclusion_ignores_expired_direct_role(
    constraint_validator, mock_constraint_repository, mock_user_role_repository
) -> None:
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(_exclusive(PREREQ, TARGET))
    await mock_user_role_repository.create(
        make_user_role(user_id=user_id, role_id=PREREQ, expires_at=50.0)
    )

    expired = await constraint_validator.validate(
        str(user_id), str(TARGET), {}, now=100.0
    )
    live = await constraint_validator.validate(str(user_id), str(TARGET), {}, now=10.0)

    assert expired.valid is True
    assert live.valid is False


async def test_group_role_in_other_tenant_does_not_exclude(
    constraint_validator, mock_constraint_repository, env
) -> None:
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(_exclusive(PREREQ, TARGET))
    await _join_group_with_role(env, user_id, PREREQ, scope=Scope(tenant_id="other"))

    result = await constraint_validator.validate(
        str(user_id), str(TARGET), {"tenant_id": "acme"}
    )

    assert result.valid is True


async def test_prerequisite_satisfied_by_group_held_role(
    constraint_validator, mock_constraint_repository, env
) -> None:
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(
        make_constraint(
            name="target-requires-prereq",
            constraint_type=ConstraintType.PREREQUISITE,
            config=ConstraintConfig(role_id=TARGET, requires_role_id=PREREQ),
        )
    )

    missing = await constraint_validator.validate(str(user_id), str(TARGET), {})
    await _join_group_with_role(env, user_id, PREREQ)
    satisfied = await constraint_validator.validate(str(user_id), str(TARGET), {})

    assert missing.valid is False
    assert missing.reason == "Prerequisite role not assigned"
    assert satisfied.valid is True


async def test_prerequisite_not_satisfied_by_expired_direct_role(
    constraint_validator, mock_constraint_repository, mock_user_role_repository
) -> None:
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(
        make_constraint(
            name="target-requires-prereq",
            constraint_type=ConstraintType.PREREQUISITE,
            config=ConstraintConfig(role_id=TARGET, requires_role_id=PREREQ),
        )
    )
    await mock_user_role_repository.create(
        make_user_role(user_id=user_id, role_id=PREREQ, expires_at=50.0)
    )

    result = await constraint_validator.validate(
        str(user_id), str(TARGET), {}, now=100.0
    )

    assert result.valid is False


async def test_cardinality_ignores_expired(
    constraint_validator, mock_constraint_repository, mock_user_role_repository
) -> None:
    await mock_constraint_repository.create(
        make_constraint(
            name="one-owner",
            constraint_type=ConstraintType.CARDINALITY,
            config=ConstraintConfig(
                role_id=TARGET, max_assignments=1, scope_level=ScopeLevel.GLOBAL
            ),
        )
    )
    await mock_user_role_repository.create(
        make_user_role(user_id=PydanticObjectId(), role_id=TARGET, expires_at=50.0)
    )

    after_expiry = await constraint_validator.validate(
        str(PydanticObjectId()), str(TARGET), {}, now=100.0
    )
    before_expiry = await constraint_validator.validate(
        str(PydanticObjectId()), str(TARGET), {}, now=10.0
    )

    assert after_expiry.valid is True
    assert before_expiry.valid is False
    assert before_expiry.reason == "Maximum 1 assignments reached"


async def test_cardinality_per_tenant_ignores_expired(
    constraint_validator, mock_constraint_repository, mock_user_role_repository
) -> None:
    await mock_constraint_repository.create(
        make_constraint(
            name="one-per-tenant",
            constraint_type=ConstraintType.CARDINALITY,
            config=ConstraintConfig(
                role_id=TARGET, max_assignments=1, scope_level=ScopeLevel.PER_TENANT
            ),
        )
    )
    await mock_user_role_repository.create(
        make_user_role(
            user_id=PydanticObjectId(),
            role_id=TARGET,
            scope=Scope(tenant_id="acme"),
            expires_at=50.0,
        )
    )
    scope = {"tenant_id": "acme"}

    expired = await constraint_validator.validate(
        str(PydanticObjectId()), str(TARGET), scope, now=100.0
    )
    live = await constraint_validator.validate(
        str(PydanticObjectId()), str(TARGET), scope, now=10.0
    )

    assert expired.valid is True
    assert live.valid is False


async def test_cardinality_per_tenant_without_tenant_never_blocks(
    constraint_validator, mock_constraint_repository, mock_user_role_repository
) -> None:
    await mock_constraint_repository.create(
        make_constraint(
            name="one-per-tenant",
            constraint_type=ConstraintType.CARDINALITY,
            config=ConstraintConfig(
                role_id=TARGET, max_assignments=1, scope_level=ScopeLevel.PER_TENANT
            ),
        )
    )
    await mock_user_role_repository.create(
        make_user_role(user_id=PydanticObjectId(), role_id=TARGET)
    )

    result = await constraint_validator.validate(
        str(PydanticObjectId()), str(TARGET), {}
    )

    assert result.valid is True


async def test_per_scope_counts_matching_scope_only(
    constraint_validator, mock_constraint_repository, mock_user_role_repository
) -> None:
    await mock_constraint_repository.create(
        make_constraint(
            name="one-per-branch",
            constraint_type=ConstraintType.CARDINALITY,
            config=ConstraintConfig(
                role_id=TARGET, max_assignments=1, scope_level=ScopeLevel.PER_SCOPE
            ),
        )
    )
    # Same tenant, other branch; same branch, other tenant; a wider scope.
    for scope in (
        Scope(tenant_id="acme", branch_id="b2"),
        Scope(tenant_id="other", branch_id="b1"),
        Scope(tenant_id="acme", branch_id="b1", region="eu"),
    ):
        await mock_user_role_repository.create(
            make_user_role(user_id=PydanticObjectId(), role_id=TARGET, scope=scope)
        )
    wanted = {"tenant_id": "acme", "branch_id": "b1"}

    free = await constraint_validator.validate(
        str(PydanticObjectId()), str(TARGET), wanted
    )
    await mock_user_role_repository.create(
        make_user_role(
            user_id=PydanticObjectId(),
            role_id=TARGET,
            scope=Scope(tenant_id="acme", branch_id="b1"),
        )
    )
    taken = await constraint_validator.validate(
        str(PydanticObjectId()), str(TARGET), wanted
    )

    assert free.valid is True
    assert taken.valid is False
    assert taken.reason == "Maximum 1 assignments reached"


async def test_constraint_on_template_binds_copy(
    constraint_validator,
    mock_constraint_repository,
    mock_role_repository,
    mock_user_role_repository,
) -> None:
    template = make_role(name="Editor", is_template=True)
    other = make_role(name="Auditor")
    copy = make_role(name="Editor", tenant_id="acme", copied_from=template.id)
    for role in (template, other, copy):
        await mock_role_repository.create(role)
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(_exclusive(template.id, other.id))
    await mock_user_role_repository.create(
        make_user_role(user_id=user_id, role_id=other.id)
    )

    result = await constraint_validator.validate(
        str(user_id), str(copy.id), {"tenant_id": "acme"}
    )

    assert result.valid is False
    assert result.constraint_name == "exclusive"


async def test_held_copy_counts_as_its_template(
    constraint_validator,
    mock_constraint_repository,
    mock_role_repository,
    mock_user_role_repository,
) -> None:
    template = make_role(name="Editor", is_template=True)
    other = make_role(name="Auditor")
    copy = make_role(name="Editor", tenant_id="acme", copied_from=template.id)
    for role in (template, other, copy):
        await mock_role_repository.create(role)
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(_exclusive(template.id, other.id))
    await mock_user_role_repository.create(
        make_user_role(user_id=user_id, role_id=copy.id, scope=Scope(tenant_id="acme"))
    )

    result = await constraint_validator.validate(
        str(user_id), str(other.id), {"tenant_id": "acme"}
    )

    assert result.valid is False


async def test_prerequisite_on_template_satisfied_by_held_copy(
    constraint_validator,
    mock_constraint_repository,
    mock_role_repository,
    mock_user_role_repository,
) -> None:
    prereq_template = make_role(name="Member", is_template=True)
    prereq_copy = make_role(
        name="Member", tenant_id="acme", copied_from=prereq_template.id
    )
    for role in (prereq_template, prereq_copy):
        await mock_role_repository.create(role)
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(
        make_constraint(
            name="needs-member",
            constraint_type=ConstraintType.PREREQUISITE,
            config=ConstraintConfig(
                role_id=TARGET, requires_role_id=prereq_template.id
            ),
        )
    )
    await mock_user_role_repository.create(
        make_user_role(
            user_id=user_id, role_id=prereq_copy.id, scope=Scope(tenant_id="acme")
        )
    )

    result = await constraint_validator.validate(
        str(user_id), str(TARGET), {"tenant_id": "acme"}
    )

    assert result.valid is True


async def test_cardinality_on_template_counts_copies(
    constraint_validator,
    mock_constraint_repository,
    mock_role_repository,
    mock_user_role_repository,
) -> None:
    template = make_role(name="Editor", is_template=True)
    copy = make_role(name="Editor", tenant_id="acme", copied_from=template.id)
    unrelated = make_role(name="Editor", tenant_id="other")
    for role in (template, copy, unrelated):
        await mock_role_repository.create(role)
    await mock_constraint_repository.create(
        make_constraint(
            name="two-editors",
            constraint_type=ConstraintType.CARDINALITY,
            config=ConstraintConfig(
                role_id=template.id, max_assignments=2, scope_level=ScopeLevel.GLOBAL
            ),
        )
    )
    for role_id in (template.id, unrelated.id):
        await mock_user_role_repository.create(
            make_user_role(user_id=PydanticObjectId(), role_id=role_id)
        )

    room = await constraint_validator.validate(
        str(PydanticObjectId()), str(copy.id), {"tenant_id": "acme"}
    )
    await mock_user_role_repository.create(
        make_user_role(
            user_id=PydanticObjectId(),
            role_id=copy.id,
            scope=Scope(tenant_id="acme"),
        )
    )
    full = await constraint_validator.validate(
        str(PydanticObjectId()), str(copy.id), {"tenant_id": "acme"}
    )

    assert room.valid is True
    assert full.valid is False


async def test_deactivated_template_still_binds_existing_copies(
    constraint_validator,
    mock_constraint_repository,
    mock_role_repository,
    mock_user_role_repository,
) -> None:
    template = make_role(name="Editor", is_template=True, is_active=False)
    other = make_role(name="Auditor")
    copy = make_role(name="Editor", tenant_id="acme", copied_from=template.id)
    for role in (template, other, copy):
        await mock_role_repository.create(role)
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(_exclusive(template.id, other.id))
    await mock_user_role_repository.create(
        make_user_role(user_id=user_id, role_id=copy.id, scope=Scope(tenant_id="acme"))
    )

    result = await constraint_validator.validate(
        str(user_id), str(other.id), {"tenant_id": "acme"}
    )

    assert result.valid is False
    assert result.constraint_name == "exclusive"


async def test_held_role_that_is_gone_still_counts_as_itself(
    constraint_validator, mock_constraint_repository, mock_user_role_repository
) -> None:
    # No role document at all: the assignment keeps its own id (deny-safe).
    user_id = PydanticObjectId()
    await mock_constraint_repository.create(_exclusive(PREREQ, TARGET))
    await mock_user_role_repository.create(
        make_user_role(user_id=user_id, role_id=PREREQ)
    )

    result = await constraint_validator.validate(str(user_id), str(TARGET), {})

    assert result.valid is False


async def test_user_with_no_assignments_passes(
    constraint_validator, mock_constraint_repository
) -> None:
    # The dry run validates a not-yet-existing user under a fresh id.
    await mock_constraint_repository.create(_exclusive(PREREQ, TARGET))
    await mock_constraint_repository.create(
        make_constraint(
            name="needs-prereq",
            constraint_type=ConstraintType.PREREQUISITE,
            config=ConstraintConfig(role_id=PREREQ, requires_role_id=TARGET),
        )
    )

    mutual = await constraint_validator.validate(
        str(PydanticObjectId()), str(TARGET), {}
    )
    prereq = await constraint_validator.validate(
        str(PydanticObjectId()), str(PREREQ), {}
    )

    assert mutual.valid is True
    assert prereq.valid is False


async def test_malformed_role_id_is_not_a_constraint_error(
    constraint_validator,
) -> None:
    result = await constraint_validator.validate(
        str(PydanticObjectId()), "not-an-object-id", {}
    )

    assert result.valid is True
