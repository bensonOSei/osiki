from abc import ABC, abstractmethod

from osiki.decision.models import EnvironmentSettings


class BaseEnvironmentStateRepository(ABC):
    @abstractmethod
    async def get_config_version(self) -> int:
        """The environment's config version; 0 when never bumped."""

    @abstractmethod
    async def bump_config_version(self) -> int:
        """Atomically increment the config version and return the new value."""

    @abstractmethod
    async def get_assignments_version(self) -> int:
        """The environment's assignments version; 0 when never bumped."""

    @abstractmethod
    async def bump_assignments_version(self) -> int:
        """Atomically increment the assignments version; return the new value."""

    @abstractmethod
    async def get_settings(self) -> EnvironmentSettings:
        """The environment's settings; defaults when none are stored."""

    @abstractmethod
    async def update_settings(
        self, settings: EnvironmentSettings
    ) -> EnvironmentSettings:
        """Store the settings and bump the config version."""
