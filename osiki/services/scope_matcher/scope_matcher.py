from loguru import logger

from osiki.decision.scope import scope_matches
from osiki.services.scope_matcher.base_scope_matcher import BaseScopeMatcher


class ScopeMatcher(BaseScopeMatcher):
    def matches(
        self, user_scope: dict[str, str] | None, request_scope: dict[str, str]
    ) -> bool:
        matched = scope_matches(user_scope or {}, request_scope)
        logger.trace(
            "Scope match result",
            user_scope=user_scope,
            request_scope=request_scope,
            matched=matched,
        )
        return matched
