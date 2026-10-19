import re
from typing import Annotated, Literal

from fastapi import Depends, Header
from pydantic import BaseModel, ConfigDict

from osiki.api.exceptions import ValidationError

_ACTOR_ID = re.compile(r"[A-Za-z0-9._@-]{1,128}")


class Actor(BaseModel):
    """Who performed an action, as asserted by a trusted front door."""

    model_config = ConfigDict(frozen=True)

    type: Literal["developer", "tenant_user"]
    id: str


def get_actor(x_osiki_actor: str | None = Header(None)) -> Actor:
    """Parse ``X-Osiki-Actor`` (``developer:<id>`` or ``tenant_user:<id>``).

    An absent header is the anonymous developer; anything else malformed is
    rejected rather than guessed at.
    """
    if x_osiki_actor is None:
        return Actor(type="developer", id="anonymous")
    actor_type, _, actor_id = x_osiki_actor.partition(":")
    if actor_type == "developer":
        parsed_type: Literal["developer", "tenant_user"] = "developer"
    elif actor_type == "tenant_user":
        parsed_type = "tenant_user"
    else:
        raise ValidationError(
            "X-Osiki-Actor must be 'developer:<id>' or 'tenant_user:<id>'"
        )
    if not _ACTOR_ID.fullmatch(actor_id):
        raise ValidationError("X-Osiki-Actor id is empty or has invalid characters")
    return Actor(type=parsed_type, id=actor_id)


ActorDep = Annotated[Actor, Depends(get_actor)]
