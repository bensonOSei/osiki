import pytest
from pydantic import ValidationError as PydanticValidationError

from osiki.api.actor import Actor, get_actor
from osiki.api.exceptions import AuthorizationError, ValidationError
from osiki.configs.settings import get_settings


def test_absent_header_is_anonymous_developer() -> None:
    assert get_actor(None) == Actor(type="developer", id="anonymous")


def test_parses_tenant_user() -> None:
    assert get_actor("tenant_user:u-42") == Actor(type="tenant_user", id="u-42")


def test_parses_developer() -> None:
    assert get_actor("developer:dev@x.io") == Actor(type="developer", id="dev@x.io")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "tenant_user:",
        "admin:x",
        "developer",
        "tenant_user:a:b:c ",
        "tenant_user:a b",
        "tenant_user:u1\n",
        "tenant_user:" + "a" * 129,
    ],
)
def test_malformed_is_validation_error(raw: str) -> None:
    with pytest.raises(ValidationError):
        get_actor(raw)


def test_id_length_boundary_is_128() -> None:
    assert get_actor("tenant_user:" + "a" * 128).id == "a" * 128


def test_actor_is_frozen() -> None:
    actor = Actor(type="developer", id="x")
    with pytest.raises(PydanticValidationError):
        actor.id = "y"  # type: ignore[misc]


def test_absent_header_refused_when_actor_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRE_ACTOR", "true")
    get_settings.cache_clear()
    try:
        with pytest.raises(AuthorizationError) as exc:
            get_actor(None)
        assert exc.value.details == {"reason": "missing_actor"}
    finally:
        monkeypatch.delenv("REQUIRE_ACTOR")
        get_settings.cache_clear()


def test_header_still_parsed_when_actor_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRE_ACTOR", "true")
    get_settings.cache_clear()
    try:
        assert get_actor("developer:ci") == Actor(type="developer", id="ci")
    finally:
        monkeypatch.delenv("REQUIRE_ACTOR")
        get_settings.cache_clear()
