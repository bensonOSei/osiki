from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from osiki.api.exceptions import register_exception_handlers
from osiki.api.middleware import RequestIDMiddleware
from osiki.api.routes import (
    authorization_router,
    constraints_router,
    groups_router,
    health_router,
    permissions_router,
    roles_router,
    tenants_router,
    users_router,
)
from osiki.configs.database import initialize_database
from osiki.configs.logger import setup_logging
from osiki.configs.settings import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    setup_logging()
    await initialize_database(
        db_url=settings.mongodb_url, db_name=settings.mongodb_database
    )
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

# Middleware
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# Exception handlers
register_exception_handlers(app)

# Health routes (no prefix)
app.include_router(health_router)

# API v1 routes
app.include_router(users_router, prefix=settings.api_prefix)
app.include_router(groups_router, prefix=settings.api_prefix)
app.include_router(roles_router, prefix=settings.api_prefix)
app.include_router(permissions_router, prefix=settings.api_prefix)
app.include_router(constraints_router, prefix=settings.api_prefix)
app.include_router(tenants_router, prefix=settings.api_prefix)
app.include_router(authorization_router, prefix=settings.api_prefix)


@app.get("/")
async def read_root() -> dict[str, str]:
    return {"message": f"Welcome to {settings.app_name} API!"}
