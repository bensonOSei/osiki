"""List-filter translators: ``to_mongo`` and ``to_sqlalchemy``."""

from typing import TYPE_CHECKING, Any

from osiki_sdk._decision import FilterResult
from osiki_sdk.filters.mongo import to_mongo

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement

__all__ = ["to_mongo", "to_sqlalchemy"]


def to_sqlalchemy(result: FilterResult, model: type[Any]) -> "ColumnElement[bool]":
    """Translate to a SQLAlchemy WHERE clause (needs the ``sqlalchemy`` extra)."""
    try:
        from osiki_sdk.filters.sqlalchemy import to_sqlalchemy as translate
    except ImportError as exc:
        raise ImportError(
            "to_sqlalchemy needs SQLAlchemy: pip install 'osiki-sdk[sqlalchemy]'"
        ) from exc
    return translate(result, model)
