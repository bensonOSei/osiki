"""``to_sqlalchemy`` on in-memory SQLite, plus the lazy-import failure path."""

import importlib
import sys
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import JSON, Boolean, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.types import NullType

from osiki_sdk._decision import FilterResult
from osiki_sdk.filters import to_sqlalchemy


class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    meta: Mapped[Any] = mapped_column(JSON, nullable=True)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add_all(
            [
                Invoice(id=1, team_id="t1", amount=10, paid=True, meta={"a": 1}),
                Invoice(id=2, team_id="t2", amount=20, paid=False, meta=None),
                Invoice(id=3, team_id="t1", amount=30, paid=None, meta=None),
                Invoice(id=4, team_id=None, amount=None, paid=True, meta=None),
            ]
        )
        s.commit()
        yield s
    engine.dispose()


def _ids(
    session: Session, node: dict[str, Any] | None, mode: str = "filter"
) -> set[int]:
    clause = to_sqlalchemy(FilterResult(mode=mode, filter=node), Invoice)  # type: ignore[arg-type]
    return set(session.scalars(select(Invoice.id).where(clause)))


def _leaf(field: str, op: str, value: Any, type_: str) -> dict[str, Any]:
    return {"field": field, "op": op, "value": value, "type": type_}


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        ("eq", 20, {2}),
        ("ne", 20, {1, 3}),
        ("lt", 20, {1}),
        ("lte", 20, {1, 2}),
        ("gt", 20, {3}),
        ("gte", 20, {2, 3}),
        ("in", [10, 30], {1, 3}),
        ("nin", [10, 30], {2}),
    ],
)
def test_each_op_on_real_rows(
    session: Session, op: str, value: Any, expected: set[int]
) -> None:
    assert _ids(session, _leaf("amount", op, value, "number")) == expected


def test_string_and_bool_columns(session: Session) -> None:
    assert _ids(session, _leaf("team_id", "eq", "t1", "string")) == {1, 3}
    assert _ids(session, _leaf("paid", "eq", True, "boolean")) == {1, 4}


def test_string_value_on_int_column_matches_nothing(session: Session) -> None:
    assert _ids(session, _leaf("amount", "eq", "10", "string")) == set()
    assert _ids(session, _leaf("amount", "ne", "10", "string")) == set()


def test_bool_never_matches_number(session: Session) -> None:
    assert _ids(session, _leaf("amount", "eq", True, "boolean")) == set()
    assert _ids(session, _leaf("paid", "eq", 1, "number")) == set()
    assert _ids(session, _leaf("paid", "ne", 1, "number")) == set()


def test_null_never_matches_ne(session: Session) -> None:
    assert 4 not in _ids(session, _leaf("amount", "ne", 99, "number"))
    assert 4 not in _ids(session, _leaf("team_id", "nin", ["x"], "string"))


def test_json_column_is_false(session: Session) -> None:
    assert _ids(session, _leaf("meta", "eq", "x", "string")) == set()


def test_unknown_field_false(session: Session) -> None:
    assert _ids(session, _leaf("nope", "eq", 1, "number")) == set()


def test_all_none_modes(session: Session) -> None:
    assert _ids(session, None, "all") == {1, 2, 3, 4}
    assert _ids(session, None, "none") == set()
    assert _ids(session, None, "filter") == set()


def test_and_or(session: Session) -> None:
    a = _leaf("team_id", "eq", "t1", "string")
    b = _leaf("amount", "gt", 15, "number")
    assert _ids(session, {"and": [a, b]}) == {3}
    assert _ids(session, {"or": [a, b]}) == {1, 2, 3}


def test_missing_sqlalchemy_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sqlalchemy", None)
    monkeypatch.delitem(sys.modules, "osiki_sdk.filters.sqlalchemy", raising=False)
    with pytest.raises(ImportError, match=r"osiki-sdk\[sqlalchemy\]"):
        to_sqlalchemy(FilterResult(mode="all"), Invoice)


def test_filters_package_imports_without_sqlalchemy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "sqlalchemy", None)
    monkeypatch.delitem(sys.modules, "osiki_sdk.filters", raising=False)
    monkeypatch.delitem(sys.modules, "osiki_sdk.filters.sqlalchemy", raising=False)
    assert importlib.import_module("osiki_sdk.filters").to_mongo is not None


def test_untyped_or_non_column_attribute_is_false() -> None:
    model = SimpleNamespace(untyped=SimpleNamespace(type=NullType()), plain=1)
    for field in ("untyped", "plain"):
        node = _leaf(field, "eq", 1, "number")
        clause = to_sqlalchemy(FilterResult(mode="filter", filter=node), model)  # type: ignore[arg-type]
        assert str(clause) == "false"
