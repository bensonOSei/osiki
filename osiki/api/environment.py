import re
from typing import Annotated

from fastapi import Depends, Header

from osiki.api.exceptions import ValidationError

ENVIRONMENT_HEADER = "X-Osiki-Environment"
DEFAULT_ENVIRONMENT = "default"

_ENVIRONMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def get_environment_id(
    x_osiki_environment: Annotated[str | None, Header()] = None,
) -> str:
    if x_osiki_environment is None:
        return DEFAULT_ENVIRONMENT
    if not _ENVIRONMENT_PATTERN.fullmatch(x_osiki_environment):
        raise ValidationError(
            "Invalid environment identifier",
            details={"header": ENVIRONMENT_HEADER},
        )
    return x_osiki_environment


EnvironmentId = Annotated[str, Depends(get_environment_id)]
