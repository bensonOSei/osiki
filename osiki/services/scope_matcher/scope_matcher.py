from loguru import logger

from osiki.services.scope_matcher.base_scope_matcher import BaseScopeMatcher


class ScopeMatcher(BaseScopeMatcher):
    def matches(
        self, user_scope: dict[str, str] | None, request_scope: dict[str, str]
    ) -> bool:
        if not user_scope:
            logger.trace("Global scope match (no user scope restrictions)")
            return True
        matched = all(
            key in request_scope and request_scope[key] == value
            for key, value in user_scope.items()
        )
        logger.trace(
            "Scope match result",
            user_scope=user_scope,
            request_scope=request_scope,
            matched=matched,
        )
        return matched
