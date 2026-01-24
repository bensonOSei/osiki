from abc import ABC, abstractmethod


class BaseScopeMatcher(ABC):
    @abstractmethod
    def matches(
        self, user_scope: dict[str, str] | None, request_scope: dict[str, str]
    ) -> bool: ...
