"""Assignment scope matching (the Task A3 truth table).

An assignment applies to a request when every key of the assignment's scope
is present in the request's scope with the same value. So a tenant-scoped
assignment never applies to a request for another tenant or for no tenant,
and a project-wide (empty) scope applies everywhere. Tenant membership for a
request that names a tenant is checked separately, by ``decide``.
"""

from collections.abc import Mapping


def scope_matches(
    assignment_scope: Mapping[str, str], request_scope: Mapping[str, str]
) -> bool:
    return all(
        key in request_scope and request_scope[key] == value
        for key, value in assignment_scope.items()
    )
