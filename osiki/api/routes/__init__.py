from osiki.api.routes.authorization import router as authorization_router
from osiki.api.routes.constraints import router as constraints_router
from osiki.api.routes.groups import router as groups_router
from osiki.api.routes.health import router as health_router
from osiki.api.routes.permissions import router as permissions_router
from osiki.api.routes.roles import router as roles_router
from osiki.api.routes.tenants import router as tenants_router
from osiki.api.routes.users import router as users_router

__all__ = [
    "authorization_router",
    "constraints_router",
    "groups_router",
    "health_router",
    "permissions_router",
    "roles_router",
    "tenants_router",
    "users_router",
]
