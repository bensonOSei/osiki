from beanie import PydanticObjectId

from osiki.models.base import Scope
from osiki.models.constraint import ConstraintConfig, ConstraintType, ScopeLevel
from tests.conftest import make_constraint, make_user_role


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
