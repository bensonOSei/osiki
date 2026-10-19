"""Convert loader results into JSON-safe records for rule evaluation."""

import dataclasses
import datetime as dt
import enum
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


def _sqlalchemy_columns(obj: Any) -> dict[str, Any] | None:
    try:
        from sqlalchemy import inspect
    except ImportError:
        return None
    state = inspect(obj, raiseerr=False)
    if state is None or not hasattr(state, "mapper"):
        return None
    return {attr.key: getattr(obj, attr.key) for attr in state.mapper.column_attrs}


def _convert(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, uuid.UUID) or type(value).__name__ == "ObjectId":
        return str(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, enum.Enum):
        return _convert(value.value)
    if isinstance(value, Mapping):
        return {str(k): _convert(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_convert(v) for v in value]
    return str(value)


def to_record(obj: Any) -> dict[str, Any]:
    """Return a JSON-safe dict for a Mapping, pydantic model, dataclass or ORM row."""
    raw: Mapping[str, Any] | None
    if isinstance(obj, Mapping):
        raw = obj
    elif isinstance(obj, BaseModel):
        raw = obj.model_dump()
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        raw = {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}
    else:
        raw = _sqlalchemy_columns(obj)
    if raw is None:
        raise TypeError(f"cannot convert {type(obj).__name__} to a record")
    return {str(k): _convert(v) for k, v in raw.items()}
