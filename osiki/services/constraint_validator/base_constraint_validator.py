from abc import ABC, abstractmethod

from pydantic import BaseModel
from pymongo.asynchronous.client_session import AsyncClientSession


class ConstraintValidationResult(BaseModel):
    valid: bool
    constraint_name: str | None = None
    reason: str | None = None


class BaseConstraintValidator(ABC):
    @abstractmethod
    async def validate(
        self,
        user_id: str,
        role_id: str,
        scope: dict[str, str],
        *,
        now: float | None = None,
        session: AsyncClientSession | None = None,
        without_role_id: str | None = None,
    ) -> ConstraintValidationResult:
        """Whether ``user_id`` may be given ``role_id`` in ``scope``.

        ``without_role_id`` judges a replace on its end state: the user's
        direct assignment of that role in exactly ``scope`` counts as gone.
        """
