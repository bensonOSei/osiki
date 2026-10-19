from abc import ABC, abstractmethod


class BaseEnvironmentStateRepository(ABC):
    @abstractmethod
    async def get_config_version(self) -> int:
        """The environment's config version; 0 when never bumped."""

    @abstractmethod
    async def bump_config_version(self) -> int:
        """Atomically increment the config version and return the new value."""
