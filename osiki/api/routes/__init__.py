from osiki.api.routes.access_logs import router as access_logs_router
from osiki.api.routes.audit_logs import router as audit_logs_router
from osiki.api.routes.authorization import router as authorization_router
from osiki.api.routes.conditions import router as conditions_router
from osiki.api.routes.constraints import router as constraints_router
from osiki.api.routes.endpoints import router as endpoints_router
from osiki.api.routes.groups import router as groups_router
from osiki.api.routes.health import router as health_router
from osiki.api.routes.permissions import router as permissions_router
from osiki.api.routes.roles import router as roles_router
from osiki.api.routes.settings import router as settings_router
from osiki.api.routes.snapshot import router as snapshot_router
from osiki.api.routes.tenants import router as tenants_router
from osiki.api.routes.users import router as users_router

__all__ = [
    "access_logs_router",
    "audit_logs_router",
    "authorization_router",
    "conditions_router",
    "constraints_router",
    "endpoints_router",
    "groups_router",
    "health_router",
    "permissions_router",
    "roles_router",
    "settings_router",
    "snapshot_router",
    "tenants_router",
    "users_router",
]
