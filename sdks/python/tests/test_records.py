import dataclasses
import datetime as dt
import enum
import json
import sys
import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from osiki_sdk.records import to_record


class ObjectId:
    def __str__(self) -> str:
        return "507f1f77bcf86cd799439011"


class Color(enum.Enum):
    RED = "red"


class Opaque:
    def __str__(self) -> str:
        return "opaque!"


def test_to_record_converts_objectid_uuid_datetime_decimal_enum() -> None:
    uid = uuid.uuid4()
    record = to_record(
        {
            "oid": ObjectId(),
            "uid": uid,
            "at": dt.datetime(2026, 1, 2, 3, 4, 5),
            "day": dt.date(2026, 1, 2),
            "amount": Decimal("1.5"),
            "color": Color.RED,
            "tags": {"a"},
            "pair": (1, 2),
            "nested": {"items": [{"id": uid}]},
            "other": Opaque(),
            "n": 1,
            "s": "x",
            "b": True,
            "none": None,
            "f": 1.5,
        }
    )
    assert record["oid"] == "507f1f77bcf86cd799439011"
    assert record["uid"] == str(uid)
    assert record["at"] == "2026-01-02T03:04:05"
    assert record["day"] == "2026-01-02"
    assert record["amount"] == 1.5 and isinstance(record["amount"], float)
    assert record["color"] == "red"
    assert record["tags"] == ["a"]
    assert record["pair"] == [1, 2]
    assert record["nested"] == {"items": [{"id": str(uid)}]}
    assert record["other"] == "opaque!"
    assert record["b"] is True and record["none"] is None
    json.dumps(record)


def test_to_record_non_string_keys() -> None:
    assert to_record({1: "a"}) == {"1": "a"}


class Item(BaseModel):
    id: uuid.UUID
    title: str


@dataclasses.dataclass
class Row:
    id: uuid.UUID
    amount: Decimal


def test_to_record_pydantic_and_dataclass() -> None:
    uid = uuid.uuid4()
    assert to_record(Item(id=uid, title="t")) == {"id": str(uid), "title": "t"}
    assert to_record(Row(id=uid, amount=Decimal("2"))) == {
        "id": str(uid),
        "amount": 2.0,
    }


class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String)


def test_to_record_sqlalchemy_model() -> None:
    assert to_record(Invoice(id=7, title="x")) == {"id": 7, "title": "x"}


def test_to_record_rejects_unsupported() -> None:
    import pytest

    bad: Any = Opaque()
    with pytest.raises(TypeError):
        to_record(bad)


def test_to_record_without_sqlalchemy(monkeypatch: Any) -> None:
    import pytest

    monkeypatch.setitem(sys.modules, "sqlalchemy", None)
    with pytest.raises(TypeError):
        to_record(Opaque())
